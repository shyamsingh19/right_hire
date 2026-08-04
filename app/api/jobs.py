from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.llm.factory import get_provider
from app.models import Candidate, Evaluation, Job
from app.pipeline.parse import parse_jd
from app.schemas import JobCreate, JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)):
    provider = get_provider()
    parsed_jd = parse_jd(body.jd_raw, provider)

    job = Job(
        title=body.title,
        jd_raw=body.jd_raw,
        jd_parsed=parsed_jd.model_dump(),
        weights=body.weights,
        thresholds=body.thresholds,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return JobResponse(
        id=job.id,
        title=job.title,
        jd_raw=job.jd_raw,
        jd_parsed=job.jd_parsed,
        weights=job.weights,
        thresholds=job.thresholds,
        created_at=job.created_at,
        candidate_count=0,
        eval_stats=None,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    candidate_count_result = await db.execute(
        select(func.count()).where(Candidate.job_id == job_id)
    )
    candidate_count = candidate_count_result.scalar() or 0

    eval_stats_result = await db.execute(
        select(Evaluation.verdict, func.count())
        .where(Evaluation.job_id == job_id)
        .group_by(Evaluation.verdict)
    )
    eval_stats = {row[0]: row[1] for row in eval_stats_result.fetchall()}

    return JobResponse(
        id=job.id,
        title=job.title,
        jd_raw=job.jd_raw,
        jd_parsed=job.jd_parsed,
        weights=job.weights,
        thresholds=job.thresholds,
        created_at=job.created_at,
        candidate_count=candidate_count,
        eval_stats=eval_stats or None,
    )
