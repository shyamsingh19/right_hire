from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── LLM output schemas ──────────────────────────────────────────────────────

class ParsedResume(BaseModel):
    name: str = ""
    email: str = ""
    yoe: float = 0.0
    location: str = ""
    skills: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class ParsedJD(BaseModel):
    title: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_yoe: float = 0.0
    location: str = ""
    must_haves: list[str] = Field(default_factory=list)


class JudgeOutput(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    reasons: dict[str, str] = Field(default_factory=dict)
    overall_score: float = 0.0
    verdict: Literal["Fit", "Maybe", "Reject"] = "Reject"


# ── Request schemas ──────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    title: str
    jd_raw: str
    weights: dict[str, float] | None = None
    thresholds: dict[str, float] | None = None


# ── Response schemas ─────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    jd_raw: str
    jd_parsed: dict | None = None
    weights: dict | None = None
    thresholds: dict | None = None
    created_at: datetime
    candidate_count: int = 0
    eval_stats: dict | None = None


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    name: str | None = None
    email: str | None = None
    yoe: float | None = None
    location: str | None = None
    resume_url: str | None = None
    status: str
    parsed: dict | None = None
    created_at: datetime


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    candidate_id: str
    job_id: str
    rubric: dict | None = None
    score: float | None = None
    verdict: str | None = None
    reasons: dict | None = None
    model_used: str | None = None
    cache_key: str | None = None
    created_at: datetime


class CandidateWithEval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate: CandidateResponse
    evaluation: EvaluationResponse | None = None


class BulkIngestResponse(BaseModel):
    job_id: str
    queued_count: int
    candidate_ids: list[str] = Field(default_factory=list)
