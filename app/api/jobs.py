from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db
from app.llm.base import LLMProvider, LLMUnavailableError
from app.llm.factory import get_provider
from app.models import Candidate, CandidateStatus, Evaluation, Job, User
from app.pipeline.parse import parse_jd
from app.queue import get_ats_queue
from app.schemas import JdParseRequest, JobCreate, JobProgress, JobResponse, JobUpdate, ParsedJD

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


def _enqueue_jd_parse(job_id: str) -> bool:
    """Best-effort enqueue of the deferred JD parse. Returns False (never raises) if
    the queue itself is unreachable — the job still exists with jd_parse_pending=True
    and can be retried by re-saving it, so this must not turn into a request failure."""
    try:
        from rq import Retry

        get_ats_queue().enqueue(
            "app.workers.tasks.parse_job_description",
            job_id,
            job_timeout=120,
            retry=Retry(max=3, interval=[30, 60, 120]),
        )
        return True
    except Exception as exc:
        logger.warning("Failed to enqueue JD parse for job=%s: %s", job_id, exc)
        return False


@router.post("/parse-jd", response_model=ParsedJD)
async def parse_jd_preview(
    body: JdParseRequest,
    user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
):
    """Pre-flight JD parse for the job creation wizard — lets a recruiter review and
    edit extracted skills/YOE/thresholds before a Job row (and its immutable jd_parsed
    snapshot) is created. Does not touch the DB or spend credits."""
    return parse_jd(body.jd_raw, provider)


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    provider: LLMProvider = Depends(get_provider),
):
    parsed_jd: ParsedJD | None = body.jd_parsed_override
    jd_parse_pending = False

    if parsed_jd is None:
        # No wizard-reviewed override was supplied — parse jd_raw now. If the LLM
        # backend is down, don't block job creation on it: save the job with an
        # empty jd_parsed and let a queued worker task fill it in once the backend
        # recovers (see app/workers/tasks.py:parse_job_description). Candidates can't
        # usefully be scored against an empty jd_parsed, but the job/title/jd_raw are
        # preserved and visible immediately rather than losing the recruiter's input.
        try:
            parsed_jd = parse_jd(body.jd_raw, provider)
        except LLMUnavailableError:
            parsed_jd = ParsedJD()
            jd_parse_pending = True

    job = Job(
        user_id=user.id,
        title=body.title,
        jd_raw=body.jd_raw,
        jd_parsed=parsed_jd.model_dump(),
        jd_parse_pending=jd_parse_pending,
        weights=body.weights,
        thresholds=body.thresholds,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    if jd_parse_pending:
        _enqueue_jd_parse(job.id)

    return JobResponse(
        id=job.id,
        title=job.title,
        jd_raw=job.jd_raw,
        jd_parsed=job.jd_parsed,
        jd_parse_pending=job.jd_parse_pending,
        weights=job.weights,
        thresholds=job.thresholds,
        created_at=job.created_at,
        candidate_count=0,
        eval_stats=None,
    )


async def _job_response(db: AsyncSession, job: Job) -> JobResponse:
    candidate_count_result = await db.execute(
        select(func.count()).where(Candidate.job_id == job.id)
    )
    candidate_count = candidate_count_result.scalar() or 0

    eval_stats_result = await db.execute(
        select(Evaluation.verdict, func.count())
        .where(Evaluation.job_id == job.id)
        .group_by(Evaluation.verdict)
    )
    eval_stats = {row[0]: row[1] for row in eval_stats_result.fetchall()}

    return JobResponse(
        id=job.id,
        title=job.title,
        jd_raw=job.jd_raw,
        jd_parsed=job.jd_parsed,
        jd_parse_pending=job.jd_parse_pending,
        weights=job.weights,
        thresholds=job.thresholds,
        created_at=job.created_at,
        candidate_count=candidate_count,
        eval_stats=eval_stats or None,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc())
    )
    jobs = result.scalars().all()
    return [await _job_response(db, job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _job_response(db, job)


@router.get("/{job_id}/progress", response_model=JobProgress)
async def job_progress(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-status candidate counts for this job — cheap enough to poll every few
    seconds from the UI without pulling full result payloads (see GET /jobs/{id}/results
    for that). Powers the upload/results pages' live progress indicator."""
    await _get_owned_job(db, job_id, user)

    status_counts_result = await db.execute(
        select(Candidate.status, func.count())
        .where(Candidate.job_id == job_id)
        .group_by(Candidate.status)
    )
    counts = {status: count for status, count in status_counts_result.fetchall()}

    last_candidate_result = await db.execute(
        select(func.max(Candidate.created_at)).where(Candidate.job_id == job_id)
    )
    last_eval_result = await db.execute(
        select(func.max(Evaluation.created_at)).where(Evaluation.job_id == job_id)
    )
    timestamps = [t for t in (last_candidate_result.scalar(), last_eval_result.scalar()) if t]
    last_updated = max(timestamps) if timestamps else None

    return JobProgress(
        job_id=job_id,
        total=sum(counts.values()),
        pending=counts.get(CandidateStatus.pending, 0),
        processing=counts.get(CandidateStatus.processing, 0),
        done=counts.get(CandidateStatus.done, 0),
        failed=counts.get(CandidateStatus.failed, 0),
        last_updated=last_updated,
    )


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: str,
    body: JobUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a job's title, weights, or thresholds. jd_raw can't be edited here —
    changing it requires re-parsing, which is a new job, not an update."""
    job = await _get_owned_job(db, job_id, user)

    if body.title is not None:
        job.title = body.title
    if body.weights is not None:
        job.weights = body.weights
    if body.thresholds is not None:
        job.thresholds = body.thresholds

    db.add(job)
    await db.commit()
    await db.refresh(job)
    return await _job_response(db, job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a job and all its candidates and evaluations."""
    job = await _get_owned_job(db, job_id, user)

    # Must delete evaluations before candidates (no DB-level cascade)
    cand_ids_result = await db.execute(select(Candidate.id).where(Candidate.job_id == job_id))
    cand_ids = [r for r in cand_ids_result.scalars().all()]

    if cand_ids:
        await db.execute(sa_delete(Evaluation).where(Evaluation.candidate_id.in_(cand_ids)))

    await db.execute(sa_delete(Candidate).where(Candidate.job_id == job_id))
    await db.delete(job)
    await db.commit()


async def _get_owned_job(db: AsyncSession, job_id: str, user: User) -> Job:
    """Shared ownership check — 404s (not 403) if the job isn't the caller's, to avoid
    leaking whether a given job_id exists at all."""
    job = await db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
