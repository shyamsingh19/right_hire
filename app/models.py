from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CandidateStatus(str, PyEnum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Verdict(str, PyEnum):
    Fit = "Fit"
    Maybe = "Maybe"
    Reject = "Reject"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    jd_raw: Mapped[str] = mapped_column(Text, nullable=False)
    jd_parsed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    thresholds: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    candidates: Mapped[list[Candidate]] = relationship(
        "Candidate", back_populates="job", lazy="selectin"
    )
    evaluations: Mapped[list[Evaluation]] = relationship(
        "Evaluation", back_populates="job", lazy="selectin"
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    yoe: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resume_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary().with_variant(LONGBLOB, "mysql"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(CandidateStatus),
        default=CandidateStatus.pending,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    job: Mapped[Job] = relationship("Job", back_populates="candidates")
    evaluation: Mapped[Evaluation | None] = relationship(
        "Evaluation", back_populates="candidate", uselist=False, lazy="selectin"
    )


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("candidates.id"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id"), nullable=False)
    rubric: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(
        Enum(Verdict), nullable=True
    )
    reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    candidate: Mapped[Candidate] = relationship("Candidate", back_populates="evaluation")
    job: Mapped[Job] = relationship("Job", back_populates="evaluations")
