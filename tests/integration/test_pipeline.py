"""Integration test: full pipeline with FakeLLMProvider — no network, no GPU."""
from __future__ import annotations

import numpy as np
import pytest

from app.pipeline.filters import apply_filters
from app.pipeline.judge import judge_candidate
from app.pipeline.match import match_candidate
from app.pipeline.score import aggregate_score
from app.schemas import ParsedJD, ParsedResume


@pytest.fixture
def sample_jd() -> ParsedJD:
    return ParsedJD(
        title="Senior Python Engineer",
        required_skills=["Python", "PostgreSQL", "Docker"],
        preferred_skills=["Redis", "Kubernetes"],
        min_yoe=4.0,
        location="San Francisco, CA",
        must_haves=[],
    )


@pytest.fixture
def sample_resume() -> ParsedResume:
    return ParsedResume(
        name="Alice Dev",
        email="alice@example.com",
        yoe=5.0,
        location="San Francisco, CA",
        skills=["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
        bullets=[
            "Built REST API serving 10k req/s using FastAPI and PostgreSQL",
            "Containerised entire stack with Docker Compose",
        ],
    )


def test_filter_pass(sample_resume, sample_jd):
    passed, reason = apply_filters(sample_resume, sample_jd, {})
    assert passed is True
    assert reason is None


def test_filter_yoe_fail(sample_jd):
    junior = ParsedResume(
        name="Bob", email="b@b.com", yoe=1.0, location="SF",
        skills=["Python", "PostgreSQL", "Docker"], bullets=[]
    )
    passed, reason = apply_filters(junior, sample_jd, {})
    assert passed is False
    assert "experience" in reason.lower()


def test_match_signals(sample_resume, sample_jd):
    vec = np.array([0.1] * 384, dtype=np.float32)
    result = match_candidate(sample_resume, sample_jd, vec, vec)
    assert result["skill_overlap"] > 0.0
    assert 0.0 <= result["cosine_sim"] <= 1.0
    assert "Python" in result["matched_skills"]


def test_judge_with_fake(fake_provider, sample_resume, sample_jd):
    vec = np.array([0.1] * 384, dtype=np.float32)
    match = match_candidate(sample_resume, sample_jd, vec, vec)
    rubric = {"technical_fit": 1.0, "experience_depth": 1.0}
    judge_out = judge_candidate(match, sample_jd, rubric, fake_provider)
    assert judge_out.verdict in ("Fit", "Maybe", "Reject")
    assert 0.0 <= judge_out.overall_score <= 1.0


def test_full_pipeline_fit(fake_provider, sample_resume, sample_jd):
    passed, _ = apply_filters(sample_resume, sample_jd, {})
    assert passed

    vec = np.array([0.1] * 384, dtype=np.float32)
    match = match_candidate(sample_resume, sample_jd, vec, vec)
    rubric = {"technical_fit": 1.0}
    judge_out = judge_candidate(match, sample_jd, rubric, fake_provider)
    score, verdict = aggregate_score(judge_out, match, {})

    assert verdict in ("Fit", "Maybe", "Reject")
    assert 0.0 <= score <= 1.0
