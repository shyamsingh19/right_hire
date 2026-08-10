from __future__ import annotations

import csv
import io
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.jobs import _get_owned_job
from app.auth import get_current_user
from app.db import get_db
from app.models import Candidate, Evaluation, User
from app.pipeline.score import _DEFAULT_THRESHOLDS
from app.schemas import (
    BatchStats,
    CandidateResponse,
    CandidateWithEval,
    EvaluationResponse,
    EvaluationUpdate,
    ReasoningCard,
    ScoreBreakdown,
)

router = APIRouter(tags=["results"])

# Below this many scored peers a percentile is noise — "top 100%" out of one candidate
# tells a recruiter nothing. Rank ("#2 of 3") stays honest at any size and is shown instead.
_MIN_COHORT_FOR_PERCENTILE = 10


def _friendly_error(raw: str | None) -> str:
    """Turn an internal exception string into something a recruiter can act on.

    These reach a customer's screen, so they must say what to do next — never leak a
    Python traceback fragment as if it were a hiring signal.
    """
    text = (raw or "").strip()
    if not text:
        return "This candidate could not be processed. Try re-queuing them."
    lowered = text.lower()
    if "no resume_text and no resume_url" in lowered:
        return (
            "No resume was provided for this candidate — the uploaded sheet had no "
            "resume link. Attach a resume file below to evaluate them."
        )
    if "could not resolve resume file" in lowered:
        return (
            "The resume link couldn't be opened. It may be private, expired, or not a "
            "direct file link. Attach the resume file below instead."
        )
    if "no extractable text" in lowered or "too little text" in lowered:
        return (
            "The resume file was downloaded but too little text could be read from it — it "
            "may be a scanned image or an unsupported format. Try a text-based PDF."
        )
    if "too short to evaluate" in lowered:
        return (
            "This candidate's resume is too short to assess. Attach the full resume file "
            "below and re-queue them."
        )
    if "failed to queue" in lowered:
        return "This candidate was never queued for processing. Re-queue them to try again."
    if "complete_json failed" in lowered or "embed failed" in lowered:
        # Infrastructure, not the candidate — say so, and keep the technical detail for
        # whoever has to fix it rather than hiding it behind a vague message.
        return (
            "The AI model couldn't complete this evaluation — this is a system issue, not "
            f"a reflection of the candidate. Re-queue them to retry. Details: {text}"
        )
    return f"Processing failed: {text}"


# ── helpers ──────────────────────────────────────────────────────────────────


def _build_reasoning_card(
    eval_obj: Evaluation,
    all_scores: list[float],
) -> ReasoningCard:
    """Build a human-readable reasoning card from stored evaluation data."""
    reasons: dict = eval_obj.reasons or {}
    rubric: dict = eval_obj.rubric or {}
    score = float(eval_obj.score or 0.0)

    # A missing verdict means the pipeline never reached a decision — the candidate
    # failed to process. Presenting that as "Reject" would tell a recruiter this person
    # was assessed and turned down, which is false and could discard a real candidate.
    if eval_obj.verdict is None:
        return ReasoningCard(
            verdict="Unprocessed",
            final_score=0.0,
            cohort_size=len(all_scores),
            summary=_friendly_error(reasons.get("error") if isinstance(reasons, dict) else None),
            error=_friendly_error(reasons.get("error") if isinstance(reasons, dict) else None),
        )

    verdict = eval_obj.verdict

    # Rank within this job's scored batch (1 = best). Percentile only once it means something.
    rank: int | None = None
    percentile: float | None = None
    cohort_size = len(all_scores)
    if cohort_size:
        rank = 1 + sum(1 for s in all_scores if s > score)
        if cohort_size >= _MIN_COHORT_FOR_PERCENTILE:
            below = sum(1 for s in all_scores if s < score)
            percentile = round(below / cohort_size * 100, 1)

    # Score breakdown stored under _score_breakdown key in reasons
    breakdown_data: dict = reasons.pop("_score_breakdown", {}) if isinstance(reasons, dict) else {}
    score_breakdown: ScoreBreakdown | None = None
    if breakdown_data:
        score_breakdown = ScoreBreakdown(
            skill_overlap=breakdown_data.get("skill_overlap", 0.0),
            cosine_sim=breakdown_data.get("cosine_sim", 0.0),
            judge_score=breakdown_data.get("judge_score", 0.0),
            weights=breakdown_data.get("weights", {}),
            contributions=breakdown_data.get("contributions", {}),
        )

    matched_skills: list[str] = []
    if isinstance(reasons, dict):
        raw = reasons.get("matched_skills", [])
        matched_skills = raw if isinstance(raw, list) else []

    criterion_reasons = {
        k: v for k, v in reasons.items() if k not in ("matched_skills",) and isinstance(v, str)
    }

    # One-line summary. Rank is only worth stating when there's someone to rank against.
    top_skill = matched_skills[0] if matched_skills else None
    rank_str = f"ranked #{rank} of {cohort_size}" if rank and cohort_size > 1 else ""
    skills_str = (
        f"{len(matched_skills)} required skill{'s' if len(matched_skills) != 1 else ''} confirmed"
        if matched_skills
        else "no required skills matched"
    )
    if verdict == "Fit":
        lead = f"Strong match (incl. {top_skill})" if top_skill else "Strong match"
        summary = f"{lead} — {skills_str}"
    elif verdict == "Maybe":
        summary = f"Borderline candidate — {skills_str}. Review manually before deciding"
    else:
        summary = "Does not meet the minimum requirements for this role"
    summary = f"{summary}{f' ({rank_str})' if rank_str else ''}."

    return ReasoningCard(
        verdict=verdict,
        final_score=score,
        rank=rank,
        cohort_size=cohort_size,
        percentile=percentile,
        score_breakdown=score_breakdown,
        criterion_scores={k: float(v) for k, v in rubric.items() if isinstance(v, (int, float))},
        criterion_reasons=criterion_reasons,
        matched_skills=matched_skills,
        summary=summary,
    )


def _build_histogram(scores: list[float], buckets: int = 10) -> list[dict]:
    if not scores:
        return []
    step = 1.0 / buckets
    hist: dict[str, int] = {}
    for i in range(buckets):
        lo = round(i * step, 1)
        hi = round((i + 1) * step, 1)
        label = f"{lo}–{hi}"
        hist[label] = 0
    for s in scores:
        idx = min(int(s / step), buckets - 1)
        lo = round(idx * step, 1)
        hi = round((idx + 1) * step, 1)
        hist[f"{lo}–{hi}"] += 1
    return [{"bucket": k, "count": v} for k, v in hist.items()]


def _percentile(scores: list[float], p: float) -> float:
    if not scores:
        return 0.0
    s = sorted(scores)
    idx = (len(s) - 1) * p / 100
    lo, hi = int(idx), math.ceil(idx)
    return round(s[lo] + (s[hi] - s[lo]) * (idx - lo), 4) if lo != hi else round(s[lo], 4)


def _suggest_thresholds(scores: list[float]) -> dict[str, float]:
    """Derive fit/maybe thresholds from distribution (top-30% fit, next-40% maybe)."""
    if len(scores) < 3:
        return dict(_DEFAULT_THRESHOLDS)
    s = sorted(scores)
    fit_idx = max(0, int(len(s) * 0.70))  # top 30%
    maybe_idx = max(0, int(len(s) * 0.30))  # top 70%
    return {
        "fit": round(s[fit_idx], 2),
        "maybe": round(s[maybe_idx], 2),
    }


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}/results", response_model=list[CandidateWithEval])
async def list_results(
    job_id: str,
    verdict: str | None = Query(default=None, description="Filter by verdict: Fit, Maybe, Reject"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_job(db, job_id, user)

    # Fetch ALL scores for this job upfront (needed for percentile)
    all_evals_result = await db.execute(
        select(Evaluation.score).where(
            Evaluation.job_id == job_id,
            Evaluation.score.is_not(None),
        )
    )
    all_scores: list[float] = [float(r) for r in all_evals_result.scalars().all()]

    stmt = select(Candidate).where(Candidate.job_id == job_id).offset(offset).limit(limit)
    candidates = (await db.execute(stmt)).scalars().all()

    out: list[CandidateWithEval] = []
    for c in candidates:
        eval_obj: Evaluation | None = (
            await db.execute(
                select(Evaluation)
                .where(Evaluation.candidate_id == c.id)
                .order_by(Evaluation.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if verdict and (not eval_obj or eval_obj.verdict != verdict):
            continue

        eval_response: EvaluationResponse | None = None
        if eval_obj:
            eval_response = EvaluationResponse.model_validate(eval_obj)
            eval_response.reasoning_card = _build_reasoning_card(eval_obj, all_scores)

        out.append(
            CandidateWithEval(
                candidate=CandidateResponse.model_validate(c),
                evaluation=eval_response,
            )
        )

    return out


@router.get("/jobs/{job_id}/results/export")
async def export_results_csv(
    job_id: str,
    verdict: str | None = Query(default=None, description="Filter by verdict: Fit, Maybe, Reject"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """CSV of every candidate + evaluation for a job — for sharing with a hiring manager."""
    await _get_owned_job(db, job_id, user)

    stmt = select(Candidate).where(Candidate.job_id == job_id)
    candidates = (await db.execute(stmt)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["name", "email", "yoe", "location", "status", "verdict", "score", "notes", "model_used"]
    )
    for c in candidates:
        eval_obj: Evaluation | None = (
            await db.execute(
                select(Evaluation)
                .where(Evaluation.candidate_id == c.id)
                .order_by(Evaluation.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if verdict and (not eval_obj or eval_obj.verdict != verdict):
            continue

        # A blank verdict column reads as "rejected" to whoever opens this in Excel.
        # Say plainly that the candidate was never assessed, and why.
        if eval_obj is None:
            verdict_cell, notes = "Not evaluated", "Still queued for processing."
        elif eval_obj.verdict is None:
            verdict_cell = "Unprocessed"
            notes = _friendly_error((eval_obj.reasons or {}).get("error"))
        else:
            verdict_cell, notes = eval_obj.verdict, ""

        writer.writerow(
            [
                c.name or "",
                c.email or "",
                c.yoe if c.yoe is not None else "",
                c.location or "",
                c.status,
                verdict_cell,
                f"{eval_obj.score:.4f}" if eval_obj and eval_obj.score is not None else "",
                notes,
                eval_obj.model_used if eval_obj else "",
            ]
        )

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="job_{job_id}_results.csv"'},
    )


@router.get("/jobs/{job_id}/stats", response_model=BatchStats)
async def batch_stats(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Score distribution, verdict breakdown, and data-driven threshold suggestions."""
    job = await _get_owned_job(db, job_id, user)

    total_result = await db.execute(select(Candidate).where(Candidate.job_id == job_id))
    total = len(total_result.scalars().all())

    evals_result = await db.execute(select(Evaluation).where(Evaluation.job_id == job_id))
    evals: list[Evaluation] = evals_result.scalars().all()

    scores = [float(e.score) for e in evals if e.score is not None]
    verdict_counts: dict[str, int] = {"Fit": 0, "Maybe": 0, "Reject": 0}
    for e in evals:
        if e.verdict in verdict_counts:
            verdict_counts[e.verdict] += 1

    current_thresholds = {
        **_DEFAULT_THRESHOLDS,
        **(job.thresholds or {}),
    }

    return BatchStats(
        job_id=job_id,
        total_candidates=total,
        evaluated=len(evals),
        verdict_counts=verdict_counts,
        percentiles={
            "p25": _percentile(scores, 25),
            "p50": _percentile(scores, 50),
            "p75": _percentile(scores, 75),
            "p90": _percentile(scores, 90),
        },
        histogram=_build_histogram(scores),
        suggested_thresholds=_suggest_thresholds(scores),
        current_thresholds=current_thresholds,
    )


@router.get("/evaluations/{eval_id}", response_model=EvaluationResponse)
async def get_evaluation(
    eval_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    eval_obj = await db.get(Evaluation, eval_id)
    if not eval_obj:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    await _get_owned_job(db, eval_obj.job_id, user)  # 404s if the eval belongs to another user

    # Fetch sibling scores for percentile
    all_scores_result = await db.execute(
        select(Evaluation.score).where(
            Evaluation.job_id == eval_obj.job_id,
            Evaluation.score.is_not(None),
        )
    )
    all_scores = [float(r) for r in all_scores_result.scalars().all()]

    response = EvaluationResponse.model_validate(eval_obj)
    response.reasoning_card = _build_reasoning_card(eval_obj, all_scores)
    return response


@router.patch("/evaluations/{eval_id}", response_model=EvaluationResponse)
async def update_evaluation(
    eval_id: str,
    body: EvaluationUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manual recruiter override of a stored verdict/score. Does not re-run the pipeline
    or touch the cache_key, so a later re-evaluation with the same inputs will still
    serve the original (unedited) cached result."""
    eval_obj = await db.get(Evaluation, eval_id)
    if not eval_obj:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    await _get_owned_job(db, eval_obj.job_id, user)

    if body.verdict is not None:
        eval_obj.verdict = body.verdict
    if body.score is not None:
        eval_obj.score = body.score

    db.add(eval_obj)
    await db.commit()
    await db.refresh(eval_obj)

    all_scores_result = await db.execute(
        select(Evaluation.score).where(
            Evaluation.job_id == eval_obj.job_id,
            Evaluation.score.is_not(None),
        )
    )
    all_scores = [float(r) for r in all_scores_result.scalars().all()]

    response = EvaluationResponse.model_validate(eval_obj)
    response.reasoning_card = _build_reasoning_card(eval_obj, all_scores)
    return response


@router.delete("/evaluations/{eval_id}", status_code=204)
async def delete_evaluation(
    eval_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete an evaluation record. The candidate itself is untouched and can be
    re-queued (e.g. by re-uploading its resume) to generate a fresh evaluation."""
    eval_obj = await db.get(Evaluation, eval_id)
    if not eval_obj:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    await _get_owned_job(db, eval_obj.job_id, user)

    await db.delete(eval_obj)
    await db.commit()
