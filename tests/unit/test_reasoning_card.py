"""Reasoning-card presentation rules.

These strings go straight onto a recruiter's screen, so the rules under test are
product guarantees, not implementation details: a candidate we failed to process
must never be shown as rejected, and a rank must never be stated when there is
nobody to rank against.
"""

from __future__ import annotations

from app.api.results import _build_reasoning_card, _friendly_error
from app.models import Evaluation


def _eval(**kw) -> Evaluation:
    return Evaluation(candidate_id="c1", job_id="j1", **kw)


# ── Processing failures ───────────────────────────────────────────────────────


def test_failed_candidate_is_not_presented_as_a_rejection():
    card = _build_reasoning_card(
        _eval(
            verdict=None,
            score=None,
            reasons={"error": "Candidate has no resume_text and no resume_url"},
        ),
        all_scores=[0.45],
    )

    assert card.verdict == "Unprocessed"
    assert card.verdict != "Reject"
    assert card.error
    assert "does not meet" not in card.summary.lower()
    assert "no resume was provided" in card.summary.lower()


def test_failed_candidate_gets_no_rank_or_score():
    card = _build_reasoning_card(
        _eval(verdict=None, score=None, reasons={"error": "boom"}),
        all_scores=[0.9, 0.5, 0.1],
    )
    assert card.rank is None
    assert card.percentile is None
    assert card.final_score == 0.0


def test_friendly_error_explains_each_known_failure():
    assert "no resume link" in _friendly_error("Candidate has no resume_text and no resume_url")
    assert "private, expired" in _friendly_error("Could not resolve resume file for resume_url=...")
    assert "scanned image" in _friendly_error("Resume file at /x.pdf produced no extractable text")
    assert "Re-queue" in _friendly_error("Failed to queue for processing")


def test_friendly_error_never_returns_empty_for_missing_reason():
    assert _friendly_error(None)
    assert _friendly_error("")


# ── Rank vs percentile ────────────────────────────────────────────────────────


def test_no_percentile_for_a_tiny_cohort():
    """The 'Top 100%' bug: with one scored candidate every percentile computes to 0,
    which rendered as 'Top 100%'. Below the cohort floor we show rank instead."""
    card = _build_reasoning_card(_eval(verdict="Maybe", score=0.45), all_scores=[0.45])

    assert card.percentile is None
    assert card.cohort_size == 1
    assert "top 100%" not in card.summary.lower()
    assert "#1 of 1" not in card.summary  # a rank of one is not worth stating


def test_rank_is_reported_once_there_are_peers():
    card = _build_reasoning_card(_eval(verdict="Fit", score=0.80), all_scores=[0.90, 0.80, 0.20])
    assert card.rank == 2
    assert card.cohort_size == 3
    assert "ranked #2 of 3" in card.summary


def test_percentile_appears_only_for_a_large_enough_cohort():
    scores = [i / 10 for i in range(10)]  # 10 scored candidates
    card = _build_reasoning_card(_eval(verdict="Fit", score=0.9), all_scores=scores)
    assert card.percentile == 90.0
    assert card.rank == 1


def test_best_candidate_ranks_first():
    card = _build_reasoning_card(_eval(verdict="Fit", score=0.99), all_scores=[0.99, 0.5, 0.1])
    assert card.rank == 1


def test_summary_pluralises_and_handles_zero_matched_skills():
    no_skills = _build_reasoning_card(_eval(verdict="Maybe", score=0.4, reasons={}), all_scores=[])
    assert "no required skills matched" in no_skills.summary

    one_skill = _build_reasoning_card(
        _eval(verdict="Fit", score=0.9, reasons={"matched_skills": ["Python"]}), all_scores=[]
    )
    assert "1 required skill confirmed" in one_skill.summary
    assert "incl. Python" in one_skill.summary
