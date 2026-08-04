import pytest
from app.pipeline.filters import apply_filters
from app.schemas import ParsedJD, ParsedResume


def _resume(**kwargs) -> ParsedResume:
    defaults = dict(name="Alice", email="a@b.com", yoe=5.0, location="SF", skills=["Python", "Docker"], bullets=[])
    return ParsedResume(**{**defaults, **kwargs})


def _jd(**kwargs) -> ParsedJD:
    defaults = dict(title="Eng", required_skills=["Python"], preferred_skills=[], min_yoe=3.0, location="SF", must_haves=[])
    return ParsedJD(**{**defaults, **kwargs})


def test_passing_candidate():
    passed, reason = apply_filters(_resume(), _jd(), {})
    assert passed is True
    assert reason is None


def test_insufficient_yoe():
    passed, reason = apply_filters(_resume(yoe=1.0), _jd(min_yoe=3.0), {})
    assert passed is False
    assert "experience" in reason.lower()


def test_missing_must_have():
    jd = _jd(must_haves=["Kubernetes"])
    passed, reason = apply_filters(_resume(skills=["Python"]), jd, {})
    assert passed is False
    assert "Kubernetes" in reason


def test_location_strict_mismatch():
    jd = _jd(location="New York")
    passed, reason = apply_filters(_resume(location="London"), jd, {"location_strict": True})
    assert passed is False
    assert "location" in reason.lower()


def test_location_strict_match():
    jd = _jd(location="San Francisco")
    passed, reason = apply_filters(_resume(location="San Francisco, CA"), jd, {"location_strict": True})
    assert passed is True


def test_location_not_strict_by_default():
    jd = _jd(location="New York")
    passed, _ = apply_filters(_resume(location="London"), jd, {})
    assert passed is True


def test_zero_min_yoe_skips_check():
    passed, reason = apply_filters(_resume(yoe=0.0), _jd(min_yoe=0.0), {})
    assert passed is True
