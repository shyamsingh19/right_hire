from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Candidate, Evaluation
from app.schemas import CandidateResponse, CandidateWithEval, EvaluationResponse

router = APIRouter(tags=["results"])


@router.get("/jobs/{job_id}/results", response_model=list[CandidateWithEval])
async def list_results(
    job_id: str,
    verdict: str | None = Query(default=None, description="Filter by verdict: Fit, Maybe, Reject"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Candidate).where(Candidate.job_id == job_id).offset(offset).limit(limit)
    result = await db.execute(stmt)
    candidates = result.scalars().all()

    if not candidates and offset == 0:
        # Verify job exists
        from app.models import Job
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

    out: list[CandidateWithEval] = []
    for c in candidates:
        eval_result = await db.execute(
            select(Evaluation).where(Evaluation.candidate_id == c.id)
        )
        eval_obj: Evaluation | None = eval_result.scalar_one_or_none()

        if verdict and eval_obj and eval_obj.verdict != verdict:
            continue
        if verdict and not eval_obj:
            continue

        out.append(
            CandidateWithEval(
                candidate=CandidateResponse.model_validate(c),
                evaluation=EvaluationResponse.model_validate(eval_obj) if eval_obj else None,
            )
        )

    return out


@router.get("/evaluations/{eval_id}", response_model=EvaluationResponse)
async def get_evaluation(eval_id: str, db: AsyncSession = Depends(get_db)):
    eval_obj = await db.get(Evaluation, eval_id)
    if not eval_obj:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return EvaluationResponse.model_validate(eval_obj)
