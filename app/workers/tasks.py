from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.llm.factory import get_provider
from app.logging_config import configure_logging
from app.models import Candidate, CandidateStatus, Evaluation, Job
from app.pipeline.embed import embed_texts, vec_to_bytes
from app.pipeline.filters import apply_filters
from app.pipeline.ingest import fetch_drive_file
from app.pipeline.judge import judge_candidate
from app.pipeline.match import match_candidate
from app.pipeline.parse import extract_text, parse_jd, parse_resume
from app.pipeline.score import aggregate_score, apply_thresholds
from app.schemas import ParsedJD, ParsedResume
from app.skills.canonicalize import canonicalize_skill

configure_logging("worker.log")
logger = logging.getLogger(__name__)


# RQ tasks are sync — use a sync SQLAlchemy engine.
# Built once per worker process and reused across tasks: a fresh create_engine() per call
# (the previous behavior) opens a brand new connection pool every time, which exhausts the
# hosted MySQL's small concurrent-connection cap instead of reusing existing connections.
_sync_engine = create_engine(
    settings.database_url, pool_pre_ping=True, pool_recycle=280, pool_size=2, max_overflow=0
)
_SyncSessionLocal = sessionmaker(bind=_sync_engine, expire_on_commit=False)


def _sync_session() -> Session:
    return _SyncSessionLocal()


def _cache_key(resume_text: str, jd_parsed: dict, weights: dict, thresholds: dict) -> str:
    # Weights/thresholds are part of the key so recalibrating a job's thresholds
    # (a workflow CLAUDE.md encourages) doesn't serve a stale cached verdict.
    payload = (
        resume_text
        + json.dumps(jd_parsed, sort_keys=True)
        + json.dumps(weights, sort_keys=True)
        + json.dumps(thresholds, sort_keys=True)
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# Below this, there isn't enough text for the LLM to parse — and given near-empty input it
# does not return empty fields, it *invents* a plausible candidate (verified: an empty
# resume yields yoe=7.5 and a full skills list). Failing here is the only safe option.
_MIN_RESUME_CHARS = 100


def _resolve_resume_text(candidate: Candidate) -> str:
    """Get resume text for *candidate*, fetching from resume_url if needed.

    Raises if no usable text can be produced — callers must not silently score an
    empty resume against a JD (see CLAUDE.md's fastest-path note on this).
    """
    if candidate.resume_text and len(candidate.resume_text.strip()) >= _MIN_RESUME_CHARS:
        return candidate.resume_text
    if not candidate.resume_url:
        if candidate.resume_text:
            raise RuntimeError(
                f"Resume text is too short to evaluate "
                f"({len(candidate.resume_text.strip())} chars, minimum {_MIN_RESUME_CHARS})"
            )
        raise RuntimeError("Candidate has no resume_text and no resume_url")

    resume_path = candidate.resume_url
    local_file = Path(resume_path)
    if not local_file.exists() and resume_path.startswith(("http://", "https://")):
        ext = Path(resume_path.split("?")[0]).suffix or ".pdf"
        dest = Path(settings.storage_dir) / f"{candidate.id}{ext}"
        fetch_drive_file(resume_path, str(dest))
        local_file = dest

    if not local_file.exists():
        raise RuntimeError(f"Could not resolve resume file for resume_url={resume_path!r}")

    text = extract_text(str(local_file))
    if len(text.strip()) < _MIN_RESUME_CHARS:
        raise RuntimeError(
            f"Resume file at {local_file} produced too little text to evaluate "
            f"({len(text.strip())} chars, minimum {_MIN_RESUME_CHARS})"
        )
    return text


def _get_redis():
    import redis as redis_lib

    return redis_lib.from_url(settings.effective_redis_url, decode_responses=True)


def parse_job_description(job_id: str) -> None:
    """Deferred JD parse for a job created while the LLM backend was down (see
    app/api/jobs.py:create_job's LLMUnavailableError fallback). Runs inside an RQ
    worker; leaves jd_parse_pending=True on failure so RQ's own retry policy —
    passed at enqueue time — can try again rather than silently giving up.
    """
    session = _sync_session()
    try:
        job = session.get(Job, job_id)
        if not job:
            logger.error("parse_job_description: missing job=%s", job_id)
            return
        if not job.jd_parse_pending:
            return  # already parsed (e.g. a retried enqueue landed twice)

        provider = get_provider()
        parsed = parse_jd(job.jd_raw, provider)
        job.jd_parsed = parsed.model_dump()
        job.jd_parse_pending = False
        session.commit()
    except Exception as exc:
        logger.warning("parse_job_description failed for job=%s: %s", job_id, exc)
    finally:
        session.close()


def process_candidate(candidate_id: str, job_id: str) -> None:
    """Full pipeline for a single candidate. Runs inside an RQ worker."""
    session = _sync_session()
    candidate: Candidate | None = None
    try:
        candidate = session.get(Candidate, candidate_id)
        job: Job | None = session.get(Job, job_id)

        if not candidate or not job:
            logger.error("process_candidate: missing candidate=%s or job=%s", candidate_id, job_id)
            return

        candidate.status = CandidateStatus.processing
        session.commit()

        jd_parsed_dict: dict = job.jd_parsed or {}
        weights: dict = job.weights or {}
        thresholds: dict = job.thresholds or {}

        # ── Step 1: Resolve resume text (local file, or fetch from resume_url) ─
        resume_text = _resolve_resume_text(candidate)
        if resume_text != candidate.resume_text:
            candidate.resume_text = resume_text
            session.commit()

        # ── Verdict cache check ───────────────────────────────────────────────
        ck = _cache_key(resume_text, jd_parsed_dict, weights, thresholds)
        try:
            r = _get_redis()
            cached = r.get(f"verdict:{ck}")
            if cached:
                cached_data = json.loads(cached)
                _write_evaluation(session, candidate, job, cached_data, ck, from_cache=True)
                return
        except Exception as exc:
            logger.warning("Redis cache check failed: %s", exc)

        # ── Step 2: Parse resume & JD ────────────────────────────────────────
        provider = get_provider()
        parsed_resume: ParsedResume = (
            ParsedResume.model_validate(candidate.parsed)
            if candidate.parsed
            else parse_resume(resume_text, provider)
        )

        parsed_jd: ParsedJD = (
            ParsedJD.model_validate(jd_parsed_dict)
            if jd_parsed_dict
            else parse_jd(job.jd_raw, provider)
        )

        candidate.parsed = parsed_resume.model_dump()
        # Backfill columns the uploaded sheet left blank — the resume itself is the better
        # source, and without this the results table shows "N/A" for every candidate whose
        # sheet only had name+email. Never overwrite a value the recruiter supplied.
        if candidate.yoe is None and parsed_resume.yoe:
            candidate.yoe = parsed_resume.yoe
        if not candidate.location and parsed_resume.location:
            candidate.location = parsed_resume.location
        if not candidate.name and parsed_resume.name:
            candidate.name = parsed_resume.name
        session.commit()

        # ── Step 3: Hard filters ─────────────────────────────────────────────
        passed, reason = apply_filters(parsed_resume, parsed_jd, thresholds)
        if not passed:
            result = {
                "verdict": "Reject",
                "score": 0.0,
                "rubric": {},
                "reasons": {"filter": reason},
                "model_used": "filter",
            }
            _write_evaluation(session, candidate, job, result, ck)
            _cache_verdict(ck, result)
            return

        # ── Step 4: Embed ────────────────────────────────────────────────────
        bullets_to_embed = parsed_resume.bullets or [resume_text[:500]]
        candidate_vecs = embed_texts(bullets_to_embed)
        candidate_vec = (
            candidate_vecs.mean(axis=0) if len(candidate_vecs) > 1 else candidate_vecs[0]
        )
        candidate.embedding = vec_to_bytes(candidate_vec)
        session.commit()

        jd_text = " ".join(
            parsed_jd.required_skills + parsed_jd.preferred_skills + [parsed_jd.title]
        )
        jd_vec = embed_texts([jd_text])[0]

        # ── Step 5: Match ────────────────────────────────────────────────────
        match_result = match_candidate(
            parsed_resume, parsed_jd, jd_vec, candidate_vec, canonicalize_skill
        )

        # ── Step 6: Judge ────────────────────────────────────────────────────
        rubric = thresholds.get("rubric", {"technical_fit": 1.0, "experience_depth": 1.0})
        judge_out = judge_candidate(match_result, parsed_jd, rubric, provider)

        # ── Step 7: Score ────────────────────────────────────────────────────
        final_score, _default_verdict, breakdown = aggregate_score(judge_out, match_result, weights)
        # re-apply with job-level thresholds (overrides default 0.70/0.40)
        verdict = apply_thresholds(final_score, thresholds)

        result = {
            "verdict": verdict,
            "score": final_score,
            "rubric": judge_out.scores,
            "reasons": {
                **judge_out.reasons,
                "matched_skills": match_result.get("matched_skills", []),
            },
            "score_breakdown": breakdown,
            "model_used": getattr(provider, "model", settings.judge_model),
        }
        _write_evaluation(session, candidate, job, result, ck)
        _cache_verdict(ck, result)

    except Exception as exc:
        logger.exception("process_candidate failed for %s: %s", candidate_id, exc)
        if candidate:
            try:
                candidate.status = CandidateStatus.failed
                session.add(
                    Evaluation(
                        candidate_id=candidate.id,
                        job_id=job_id,
                        reasons={"error": str(exc)[:500]},
                        model_used="error",
                    )
                )
                session.commit()
            except Exception:
                logger.exception("Failed to record failure for candidate %s", candidate_id)
                session.rollback()
    finally:
        session.close()


def _write_evaluation(
    session: Session,
    candidate: Candidate,
    job: Job,
    result: dict,
    cache_key: str,
    from_cache: bool = False,
) -> None:
    reasons = result.get("reasons") or {}
    if result.get("score_breakdown"):
        reasons = {**reasons, "_score_breakdown": result["score_breakdown"]}

    eval_obj = Evaluation(
        candidate_id=candidate.id,
        job_id=job.id,
        rubric=result.get("rubric"),
        score=result.get("score"),
        verdict=result.get("verdict"),
        reasons=reasons,
        model_used=result.get("model_used", "cache" if from_cache else None),
        cache_key=cache_key,
    )
    session.add(eval_obj)
    candidate.status = CandidateStatus.done
    session.commit()


def _cache_verdict(cache_key: str, result: dict) -> None:
    try:
        r = _get_redis()
        r.setex(f"verdict:{cache_key}", 86400 * 7, json.dumps(result))
    except Exception as exc:
        logger.warning("Failed to cache verdict: %s", exc)
