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
    ReasoningCard,
    ScoreBreakdown,
)

router = APIRouter(tags=["results"])


# ── helpers ──────────────────────────────────────────────────────────────────


def _build_reasoning_card(
    eval_obj: Evaluation,
    all_scores: list[float],
) -> ReasoningCard:
    """Build a human-readable reasoning card from stored evaluation data."""
    reasons: dict = eval_obj.reasons or {}
    rubric: dict = eval_obj.rubric or {}
    score = float(eval_obj.score or 0.0)
    verdict = eval_obj.verdict or "Reject"

    # Percentile within this job's evaluated batch
    percentile: float | None = None
    if all_scores:
        below = sum(1 for s in all_scores if s < score)
        percentile = round(below / len(all_scores) * 100, 1)

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

    # One-line summary
    top_skill = matched_skills[0] if matched_skills else None
    pct_str = f"top {100 - int(percentile or 0)}%" if percentile is not None else ""
    if verdict == "Fit":
        summary = f"Strong match — {pct_str}{',' if pct_str else ''} {len(matched_skills)} required skills confirmed."
    elif verdict == "Maybe":
        summary = f"Borderline candidate{(' — ' + pct_str) if pct_str else ''}. Review manually before deciding."
    else:
        summary = "Does not meet minimum requirements for this role."
    if top_skill:
        summary = summary.replace("Strong match", f"Strong match (incl. {top_skill})")

    return ReasoningCard(
        verdict=verdict,
        final_score=score,
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
            await db.execute(select(Evaluation).where(Evaluation.candidate_id == c.id))
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
        ["name", "email", "yoe", "location", "status", "verdict", "score", "model_used"]
    )
    for c in candidates:
        eval_obj: Evaluation | None = (
            await db.execute(select(Evaluation).where(Evaluation.candidate_id == c.id))
        ).scalar_one_or_none()
        if verdict and (not eval_obj or eval_obj.verdict != verdict):
            continue
        writer.writerow(
            [
                c.name or "",
                c.email or "",
                c.yoe if c.yoe is not None else "",
                c.location or "",
                c.status,
                eval_obj.verdict if eval_obj else "",
                f"{eval_obj.score:.4f}" if eval_obj and eval_obj.score is not None else "",
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
