from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import redis as redis_lib
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from rq import Queue, Retry
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.jobs import _get_owned_job
from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import Candidate, CandidateStatus, Evaluation, User
from app.pipeline.ingest import (
    apply_column_mapping,
    detect_column_mapping,
    parse_csv,
    parse_csv_raw,
    parse_excel,
    parse_excel_raw,
    save_resume,
)
from app.schemas import (
    BulkIngestResponse,
    CancelPendingResponse,
    CandidateResponse,
    CandidateUpdate,
    ColumnPreviewResponse,
    DeleteAllCandidatesResponse,
    RetryCandidatesResponse,
)

router = APIRouter(prefix="/jobs", tags=["ingest"])
logger = logging.getLogger(__name__)

_RESUME_EXTENSIONS = {".pdf", ".txt", ".md"}  # must match app/pipeline/parse.py:extract_text


def _get_queue() -> Queue:
    r = redis_lib.from_url(settings.effective_redis_url)
    return Queue("ats", connection=r)


def _validate_sheet_signature(filename: str, content: bytes) -> None:
    """Extension-independent sanity check — catches renamed/corrupt uploads early."""
    if filename.endswith(".xlsx"):
        if content[:4] != b"PK\x03\x04":
            raise HTTPException(
                status_code=422, detail="File does not look like a valid .xlsx (bad zip header)"
            )
    elif filename.endswith(".csv"):
        try:
            content[:4096].decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=422, detail="File does not look like valid UTF-8 CSV text"
            ) from exc


def _enqueue_candidates(
    queue: Queue, job_id: str, candidate_ids: list[str]
) -> tuple[list[str], list[str]]:
    """Enqueue each candidate; returns (queued_ids, failed_ids). Never raises."""
    queued: list[str] = []
    failed: list[str] = []
    for cid in candidate_ids:
        try:
            queue.enqueue(
                "app.workers.tasks.process_candidate",
                cid,
                job_id,
                job_timeout=600,
                retry=Retry(max=3, interval=[10, 30, 60]),
            )
            queued.append(cid)
        except Exception as exc:
            logger.warning("Failed to enqueue candidate %s: %s", cid, exc)
            failed.append(cid)
    return queued, failed


@router.post("/{job_id}/candidates/cancel-pending", response_model=CancelPendingResponse)
async def cancel_pending_candidates(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark all pending candidates for this job as cancelled (failed with a user-cancel reason).

    Only affects candidates still in 'pending' status — those already being processed by a
    worker are mid-flight and cannot be interrupted. Credits are NOT refunded since the
    candidates were already deducted on ingest.
    """
    from sqlalchemy import select as sa_select

    await _get_owned_job(db, job_id, user)

    result = await db.execute(
        sa_select(Candidate.id).where(
            Candidate.job_id == job_id,
            Candidate.status == CandidateStatus.pending,
        )
    )
    pending_ids = [row[0] for row in result.all()]

    if not pending_ids:
        return CancelPendingResponse(cancelled_count=0)

    await db.execute(
        update(Candidate).where(Candidate.id.in_(pending_ids)).values(status=CandidateStatus.failed)
    )
    for cid in pending_ids:
        db.add(
            Evaluation(
                candidate_id=cid,
                job_id=job_id,
                reasons={"error": "Cancelled by user before processing started"},
                model_used="cancelled",
            )
        )
    await db.commit()
    logger.info(
        "User %s cancelled %d pending candidates for job %s", user.id, len(pending_ids), job_id
    )
    return CancelPendingResponse(cancelled_count=len(pending_ids))


@router.post("/{job_id}/candidates/{candidate_id}/retry", response_model=CandidateResponse)
async def retry_candidate(
    job_id: str,
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-queue a single failed candidate using the resume already on file — no new upload,
    no additional credit charge (it was already deducted on first ingest). Use this for
    transient failures (rate limits, timeouts); if there's no resume on file at all, the
    caller should attach one via POST .../candidates/{id}/resume instead."""
    candidate = await _get_owned_candidate(db, job_id, candidate_id, user)

    if candidate.status != CandidateStatus.failed:
        raise HTTPException(status_code=400, detail="Only failed candidates can be retried")
    if not candidate.resume_text and not candidate.resume_url:
        raise HTTPException(
            status_code=400,
            detail="No resume on file for this candidate — attach a resume file to retry them",
        )

    candidate.status = CandidateStatus.pending
    await db.commit()

    queue = _get_queue()
    queued_ids, failed_ids = _enqueue_candidates(queue, job_id, [candidate.id])
    if failed_ids:
        candidate.status = CandidateStatus.failed
        await db.commit()
        raise HTTPException(status_code=503, detail="Could not queue candidate for retry")

    await db.refresh(candidate)
    return candidate


@router.post("/{job_id}/candidates/retry-failed", response_model=RetryCandidatesResponse)
async def retry_failed_candidates(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-queue every failed candidate in this job that still has a resume on file.
    Candidates with no resume at all (never downloaded/attached) are skipped — they need a
    file attached first. No additional credits are charged."""
    await _get_owned_job(db, job_id, user)

    result = await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.status == CandidateStatus.failed,
        )
    )
    failed_candidates = list(result.scalars().all())
    retryable = [c for c in failed_candidates if c.resume_text or c.resume_url]
    skipped_count = len(failed_candidates) - len(retryable)

    if not retryable:
        return RetryCandidatesResponse(retried_count=0, skipped_count=skipped_count)

    retryable_ids = [c.id for c in retryable]
    await db.execute(
        update(Candidate)
        .where(Candidate.id.in_(retryable_ids))
        .values(status=CandidateStatus.pending)
    )
    await db.commit()

    queue = _get_queue()
    queued_ids, failed_ids = _enqueue_candidates(queue, job_id, retryable_ids)
    if failed_ids:
        await db.execute(
            update(Candidate).where(Candidate.id.in_(failed_ids)).values(status=CandidateStatus.failed)
        )
        await db.commit()

    logger.info(
        "User %s retried %d failed candidates for job %s (%d skipped, no resume)",
        user.id,
        len(queued_ids),
        job_id,
        skipped_count,
    )
    return RetryCandidatesResponse(
        retried_count=len(queued_ids), skipped_count=skipped_count, candidate_ids=queued_ids
    )


@router.post("/{job_id}/candidates/preview", response_model=ColumnPreviewResponse)
async def preview_columns(
    job_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Parse file headers and return auto-detected column mapping + sample rows.

    No candidates are created; this is a read-only preview step before the user
    confirms the mapping and calls POST /{job_id}/candidates.
    """
    await _get_owned_job(db, job_id, user)

    filename = file.filename or ""
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds max upload size ({settings.max_upload_mb} MB)"
        )
    _validate_sheet_signature(filename, content)

    try:
        if filename.endswith(".xlsx"):
            raw_headers, raw_rows = parse_excel_raw(content)
        elif filename.endswith(".csv"):
            raw_headers, raw_rows = parse_csv_raw(content)
        else:
            raise HTTPException(status_code=400, detail="Only .xlsx or .csv files are accepted")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    mapping = detect_column_mapping(raw_headers)
    return ColumnPreviewResponse(
        columns=raw_headers,
        mapping=mapping,
        sample_rows=raw_rows[:3],
    )


@router.post("/{job_id}/candidates", response_model=BulkIngestResponse, status_code=202)
async def ingest_candidates(
    job_id: str,
    file: UploadFile,
    column_mapping: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = await _get_owned_job(db, job_id, user)
    if job.jd_parse_pending:
        raise HTTPException(
            status_code=409,
            detail="This job's description is still being parsed (the AI backend was "
            "unavailable when it was created) — try again in a minute.",
        )

    filename = file.filename or ""
    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds max upload size ({settings.max_upload_mb} MB)"
        )
    _validate_sheet_signature(filename, content)

    # Parse explicit mapping from form field (sent by the UI after the preview step)
    explicit_mapping: dict[str, str | None] | None = None
    if column_mapping:
        try:
            explicit_mapping = json.loads(column_mapping)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Invalid column_mapping JSON") from exc

    try:
        if filename.endswith(".xlsx"):
            if explicit_mapping is not None:
                _, raw_rows = parse_excel_raw(content)
                rows = apply_column_mapping(raw_rows, explicit_mapping)
            else:
                rows = parse_excel(content)
        elif filename.endswith(".csv"):
            if explicit_mapping is not None:
                _, raw_rows = parse_csv_raw(content)
                rows = apply_column_mapping(raw_rows, explicit_mapping)
            else:
                rows = parse_csv(content)
        else:
            raise HTTPException(status_code=400, detail="Only .xlsx or .csv files are accepted")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=422, detail="File contains no data rows")

    if user.credits < len(rows):
        raise HTTPException(
            status_code=402,
            detail=(
                f"Not enough credits: {user.credits} available, {len(rows)} required for this "
                "batch (1 credit = 1 candidate). Request more via POST /billing/request-credits."
            ),
        )

    candidate_ids: list[str] = []

    for row in rows:
        cid = str(uuid.uuid4())
        yoe_raw = row.get("yoe")
        try:
            yoe = float(yoe_raw) if yoe_raw is not None else None
        except (ValueError, TypeError):
            yoe = None

        candidate = Candidate(
            id=cid,
            job_id=job_id,
            name=str(row.get("name", "")) or None,
            email=str(row.get("email", "")) or None,
            yoe=yoe,
            location=str(row.get("location", "")) or None,
            resume_url=str(row.get("resume_url", "")) or None,
            status=CandidateStatus.pending,
        )
        db.add(candidate)
        candidate_ids.append(cid)

    await db.commit()

    # Enqueue after commit so IDs are persisted
    queue = _get_queue()
    queued_ids, failed_ids = _enqueue_candidates(queue, job_id, candidate_ids)

    if failed_ids:
        # Don't leave these silently "pending" forever — mark them failed with a reason
        # visible in the Results UI, same pattern as worker-side failures.
        await db.execute(
            update(Candidate)
            .where(Candidate.id.in_(failed_ids))
            .values(status=CandidateStatus.failed)
        )
        for fid in failed_ids:
            db.add(
                Evaluation(
                    candidate_id=fid,
                    job_id=job_id,
                    reasons={"error": "Failed to queue for processing — check Redis connectivity"},
                    model_used="error",
                )
            )

    user.credits -= len(queued_ids)
    db.add(user)
    await db.commit()

    if not queued_ids and failed_ids:
        raise HTTPException(
            status_code=503,
            detail="Could not queue any candidates for processing — the queue service is "
            "unreachable. Candidates were saved as 'failed'; retry once Redis is back up.",
        )

    return BulkIngestResponse(
        job_id=job_id,
        queued_count=len(queued_ids),
        candidate_ids=queued_ids,
        failed_count=len(failed_ids),
    )


@router.get("/{job_id}/candidates", response_model=list[CandidateResponse])
async def list_candidates(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_job(db, job_id, user)
    result = await db.execute(
        select(Candidate).where(Candidate.job_id == job_id).order_by(Candidate.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{job_id}/candidates/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    job_id: str,
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    candidate = await _get_owned_candidate(db, job_id, candidate_id, user)
    return candidate


@router.patch("/{job_id}/candidates/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    job_id: str,
    candidate_id: str,
    body: CandidateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit candidate contact/profile fields. Does not touch resume_text, parsed, status,
    or trigger re-evaluation — use the resume upload endpoint to re-queue a candidate."""
    candidate = await _get_owned_candidate(db, job_id, candidate_id, user)

    if body.name is not None:
        candidate.name = body.name
    if body.email is not None:
        candidate.email = body.email
    if body.yoe is not None:
        candidate.yoe = body.yoe
    if body.location is not None:
        candidate.location = body.location

    db.add(candidate)
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def _get_owned_candidate(
    db: AsyncSession, job_id: str, candidate_id: str, user: User
) -> Candidate:
    await _get_owned_job(db, job_id, user)
    candidate = await db.get(Candidate, candidate_id)
    if not candidate or candidate.job_id != job_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post("/{job_id}/candidates/{candidate_id}/resume", response_model=BulkIngestResponse)
async def upload_candidate_resume(
    job_id: str,
    candidate_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Attach a resume file directly to a candidate (alternative to resume_url), then
    re-queue it. Costs 1 credit, same as a sheet row."""
    candidate = await _get_owned_candidate(db, job_id, candidate_id, user)

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in _RESUME_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported resume type {ext!r}. Accepted: {sorted(_RESUME_EXTENSIONS)}",
        )

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds max upload size ({settings.max_upload_mb} MB)"
        )

    if user.credits < 1:
        raise HTTPException(status_code=402, detail="Not enough credits to evaluate this resume")

    path = save_resume(candidate.id, content, ext)
    candidate.resume_url = path
    candidate.resume_text = None
    candidate.status = CandidateStatus.pending
    user.credits -= 1
    db.add(user)
    await db.commit()

    queue = _get_queue()
    queued_ids, failed_ids = _enqueue_candidates(queue, job_id, [candidate.id])
    if failed_ids:
        user.credits += 1  # refund — never got queued
        db.add(user)
        await db.commit()
        raise HTTPException(status_code=503, detail="Could not queue candidate for processing")

    return BulkIngestResponse(
        job_id=job_id, queued_count=1, candidate_ids=queued_ids, failed_count=0
    )


@router.delete("/{job_id}/candidates", response_model=DeleteAllCandidatesResponse)
async def delete_all_candidates(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete every candidate (and their evaluations/resume files) for this job, leaving the
    job itself — its JD, weights, and thresholds — intact so a fresh batch can be uploaded.
    Credits already deducted on ingest are not refunded, same as cancel-pending."""
    await _get_owned_job(db, job_id, user)

    result = await db.execute(select(Candidate).where(Candidate.job_id == job_id))
    candidates = result.scalars().all()

    if not candidates:
        return DeleteAllCandidatesResponse(deleted_count=0)

    storage_root = Path(settings.storage_dir).resolve()
    for candidate in candidates:
        if candidate.resume_url:
            resume_path = Path(candidate.resume_url)
            try:
                if resume_path.exists() and resume_path.resolve().is_relative_to(storage_root):
                    resume_path.unlink()
            except OSError:
                logger.warning(
                    "Could not delete stored resume file for candidate %s", candidate.id
                )

    await db.execute(delete(Evaluation).where(Evaluation.job_id == job_id))
    await db.execute(delete(Candidate).where(Candidate.job_id == job_id))
    await db.commit()

    logger.info("User %s deleted all %d candidates for job %s", user.id, len(candidates), job_id)
    return DeleteAllCandidatesResponse(deleted_count=len(candidates))


@router.delete("/{job_id}/candidates/{candidate_id}", status_code=204)
async def delete_candidate(
    job_id: str,
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a candidate and their evaluation — for GDPR-style removal requests."""
    candidate = await _get_owned_candidate(db, job_id, candidate_id, user)

    if candidate.resume_url:
        resume_path = Path(candidate.resume_url)
        storage_root = Path(settings.storage_dir).resolve()
        try:
            if resume_path.exists() and resume_path.resolve().is_relative_to(storage_root):
                resume_path.unlink()
        except OSError:
            logger.warning("Could not delete stored resume file for candidate %s", candidate_id)

    # No ORM cascade configured on the Evaluation FK — delete it explicitly first.
    await db.execute(delete(Evaluation).where(Evaluation.candidate_id == candidate_id))
    await db.delete(candidate)
    await db.commit()
