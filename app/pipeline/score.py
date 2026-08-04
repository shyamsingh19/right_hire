from __future__ import annotations

from app.schemas import JudgeOutput

_DEFAULT_WEIGHTS = {
    "skill_overlap": 0.30,
    "cosine": 0.20,
    "judge": 0.50,
}

_DEFAULT_THRESHOLDS = {
    "fit": 0.70,
    "maybe": 0.40,
}


def aggregate_score(
    judge_output: JudgeOutput,
    match_result: dict,
    weights: dict,
) -> tuple[float, str]:
    """Combine judge score with retrieval signals into a final 0–1 score."""
    w = {**_DEFAULT_WEIGHTS, **(weights or {})}

    skill_overlap = float(match_result.get("skill_overlap", 0.0))
    cosine_sim = float(match_result.get("cosine_sim", 0.0))
    judge_score = float(judge_output.overall_score)

    # Clamp all components to [0, 1]
    skill_overlap = max(0.0, min(1.0, skill_overlap))
    cosine_sim = max(0.0, min(1.0, cosine_sim))
    judge_score = max(0.0, min(1.0, judge_score))

    total_weight = w["skill_overlap"] + w["cosine"] + w["judge"]
    final = (
        w["skill_overlap"] * skill_overlap
        + w["cosine"] * cosine_sim
        + w["judge"] * judge_score
    ) / total_weight

    verdict = apply_thresholds(final, {})
    return round(final, 4), verdict


def apply_thresholds(score: float, thresholds: dict) -> str:
    """Map a 0–1 score to Fit / Maybe / Reject using configurable thresholds."""
    t = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}
    if score >= t["fit"]:
        return "Fit"
    if score >= t["maybe"]:
        return "Maybe"
    return "Reject"
