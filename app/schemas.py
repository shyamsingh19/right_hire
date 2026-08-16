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


class JdParseRequest(BaseModel):
    jd_raw: str


class JobCreate(BaseModel):
    title: str
    jd_raw: str
    weights: dict[str, float] | None = None
    thresholds: dict[str, float] | None = None
    # Set by the create-job wizard after the recruiter reviews/edits the auto-parsed
    # criteria in the Step 1 -> Step 2 preview (POST /jobs/parse-jd). When present, this
    # is stored as-is instead of re-parsing jd_raw, so wizard edits aren't discarded.
    jd_parsed_override: ParsedJD | None = None


class JobUpdate(BaseModel):
    """All fields optional — only provided fields are changed. `jd_raw` is intentionally
    excluded: editing it would require re-running parse_jd, which is a create, not an
    update (see CLAUDE.md: workers read jd_parsed, they never re-parse)."""

    title: str | None = None
    weights: dict[str, float] | None = None
    thresholds: dict[str, float] | None = None


class CandidateUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    yoe: float | None = None
    location: str | None = None


class EvaluationUpdate(BaseModel):
    """Manual recruiter override of a stored verdict/score — does not re-run the pipeline."""

    verdict: Literal["Fit", "Maybe", "Reject"] | None = None
    score: float | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    credits: int
    created_at: datetime


class UserUpdate(BaseModel):
    email: str | None = None
    credits: int | None = None


class ApiKeyResetResponse(BaseModel):
    user_id: str
    email: str
    api_key: str  # shown once — only the hash is stored server-side


# ── Response schemas ─────────────────────────────────────────────────────────


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    jd_raw: str
    jd_parsed: dict | None = None
    jd_parse_pending: bool = False
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
    resume_text: str | None = None
    status: str
    parsed: dict | None = None
    created_at: datetime


class ScoreBreakdown(BaseModel):
    """Weighted component scores that produced the final verdict."""

    skill_overlap: float
    cosine_sim: float
    judge_score: float
    weights: dict[str, float]
    contributions: dict[str, float]


class ReasoningCard(BaseModel):
    """Human-readable explanation of why a candidate received their verdict."""

    verdict: str
    final_score: float
    # Rank is honest at any cohort size; percentile is only populated once the batch is
    # big enough for it to mean anything (see _MIN_COHORT_FOR_PERCENTILE in api/results.py).
    rank: int | None = None
    cohort_size: int = 0
    percentile: float | None = None  # 0–100, position within this job's batch
    score_breakdown: ScoreBreakdown | None = None
    criterion_scores: dict[str, float] = Field(default_factory=dict)
    criterion_reasons: dict[str, str] = Field(default_factory=dict)
    matched_skills: list[str] = Field(default_factory=list)
    summary: str = ""
    # How close the score is to the nearest Fit/Maybe cutoff — "Low" means this verdict
    # could easily flip with minor rubric variance and deserves a manual look before acting.
    confidence: Literal["High", "Medium", "Low"] | None = None
    # Set only when the candidate could not be processed at all. A card with `error`
    # set is NOT a merit-based rejection and must never be presented as one.
    error: str | None = None


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
    reasoning_card: ReasoningCard | None = None  # populated at read time, not stored


class CandidateWithEval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate: CandidateResponse
    evaluation: EvaluationResponse | None = None


class BatchStats(BaseModel):
    """Score distribution and derived thresholds for a job's candidate pool."""

    job_id: str
    total_candidates: int
    evaluated: int
    verdict_counts: dict[str, int]
    percentiles: dict[str, float]  # p25, p50, p75, p90
    histogram: list[dict]  # [{bucket: "0.6–0.7", count: 12}, ...]
    suggested_thresholds: dict[str, float]  # data-driven fit/maybe cutoffs
    current_thresholds: dict[str, float]


class BulkIngestResponse(BaseModel):
    job_id: str
    queued_count: int
    candidate_ids: list[str] = Field(default_factory=list)
    failed_count: int = 0


class ColumnPreviewResponse(BaseModel):
    """Returned by the /preview endpoint before final upload."""

    columns: list[str]  # raw column names from the file
    mapping: dict[str, str | None]  # canonical_field → raw_column (None = undetected)
    sample_rows: list[dict]  # first 3 raw rows for user preview


class CancelPendingResponse(BaseModel):
    cancelled_count: int


class RetryCandidatesResponse(BaseModel):
    retried_count: int
    skipped_count: int = 0
    candidate_ids: list[str] = Field(default_factory=list)


class DeleteAllCandidatesResponse(BaseModel):
    deleted_count: int


class JobProgress(BaseModel):
    """Lightweight per-status counts for GET /jobs/{id}/progress — cheaper than fetching
    full results just to render a progress bar, and safe to poll frequently."""

    job_id: str
    total: int
    pending: int
    processing: int
    done: int
    failed: int
    last_updated: datetime | None = None


class CreditRequestItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
