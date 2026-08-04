from __future__ import annotations

import logging
import uuid

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Candidate, CandidateStatus, Job
from app.pipeline.ingest import parse_excel
from app.schemas import BulkIngestResponse

router = APIRouter(prefix="/jobs", tags=["ingest"])
logger = logging.getLogger(__name__)


def _get_queue() -> Queue:
    r = redis_lib.from_url(settings.redis_url)
    return Queue("default", connection=r)


@router.post("/{job_id}/candidates", response_model=BulkIngestResponse, status_code=202)
async def ingest_candidates(
    job_id: str,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")

    content = await file.read()
    try:
        rows = parse_excel(content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse Excel: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=422, detail="Excel file contains no data rows")

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
            )
        except Exception as exc:
            logger.warning("Failed to enqueue candidate %s: %s", cid, exc)

    return BulkIngestResponse(job_id=job_id, queued_count=len(candidate_ids), candidate_ids=candidate_ids)
