from app.pipeline.score import aggregate_score, apply_thresholds
from app.schemas import JudgeOutput


def _judge(overall: float = 0.8, verdict: str = "Fit") -> JudgeOutput:
    return JudgeOutput(
        scores={"technical_fit": overall},
        reasons={"technical_fit": "test"},
        overall_score=overall,
        verdict=verdict,
    )


def test_fit_verdict():
    score, verdict, _ = aggregate_score(_judge(0.9), {"skill_overlap": 0.9, "cosine_sim": 0.85}, {})
    assert verdict == "Fit"
    assert 0.0 <= score <= 1.0


def test_reject_verdict():
    score, verdict, _ = aggregate_score(_judge(0.1), {"skill_overlap": 0.05, "cosine_sim": 0.1}, {})
    assert verdict == "Reject"


def test_maybe_verdict():
    score, verdict, _ = aggregate_score(_judge(0.55), {"skill_overlap": 0.5, "cosine_sim": 0.5}, {})
    assert verdict == "Maybe"


def test_custom_weights():
    # With judge weight = 1.0 only, score should be judge's overall_score
    score, _, _bd = aggregate_score(
        _judge(0.8),
        {"skill_overlap": 0.0, "cosine_sim": 0.0},
        {"skill_overlap": 0.0, "cosine": 0.0, "judge": 1.0},
    )
    assert abs(score - 0.8) < 0.01


def test_apply_thresholds_fit():
    assert apply_thresholds(0.75, {}) == "Fit"


def test_apply_thresholds_maybe():
    assert apply_thresholds(0.5, {}) == "Maybe"


def test_apply_thresholds_reject():
    assert apply_thresholds(0.2, {}) == "Reject"


def test_apply_thresholds_custom():
    assert apply_thresholds(0.6, {"fit": 0.8, "maybe": 0.5}) == "Maybe"
    assert apply_thresholds(0.85, {"fit": 0.8, "maybe": 0.5}) == "Fit"
