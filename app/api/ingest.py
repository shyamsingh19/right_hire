from __future__ import annotations

import logging
import uuid

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from rq import Retry, Queue
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.jobs import _get_owned_job
from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import Candidate, CandidateStatus, User
from app.pipeline.ingest import parse_csv, parse_excel
from app.schemas import BulkIngestResponse

router = APIRouter(prefix="/jobs", tags=["ingest"])
logger = logging.getLogger(__name__)


def _get_queue() -> Queue:
    r = redis_lib.from_url(settings.redis_url)
    return Queue("ats", connection=r)


@router.post("/{job_id}/candidates", response_model=BulkIngestResponse, status_code=202)
async def ingest_candidates(
    job_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_job(db, job_id, user)

    filename = file.filename or ""
    if filename.endswith(".xlsx"):
        parser = parse_excel
    elif filename.endswith(".csv"):
        parser = parse_csv
    else:
        raise HTTPException(status_code=400, detail="Only .xlsx or .csv files are accepted")

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"File exceeds max upload size ({settings.max_upload_mb} MB)"
        )
    try:
        rows = parser(content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=422, detail="File contains no data rows")

    queue = _get_queue()
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
    for cid in candidate_ids:
        try:
            queue.enqueue(
                "app.workers.tasks.process_candidate",
                cid,
                job_id,
                job_timeout=600,
                retry=Retry(max=3, interval=[10, 30, 60]),
            )
        except Exception as exc:
            logger.warning("Failed to enqueue candidate %s: %s", cid, exc)

    return BulkIngestResponse(
        job_id=job_id, queued_count=len(candidate_ids), candidate_ids=candidate_ids
    )
