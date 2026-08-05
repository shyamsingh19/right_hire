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
) -> tuple[float, str, dict]:
    """Combine judge score with retrieval signals into a final 0–1 score.

    Returns (final_score, verdict, breakdown) where breakdown exposes every
    weighted component so callers can build an explainable reasoning card.
    """
    w = {**_DEFAULT_WEIGHTS, **(weights or {})}

    skill_overlap = max(0.0, min(1.0, float(match_result.get("skill_overlap", 0.0))))
    cosine_sim = max(0.0, min(1.0, float(match_result.get("cosine_sim", 0.0))))
    judge_score = max(0.0, min(1.0, float(judge_output.overall_score)))

    total_weight = w["skill_overlap"] + w["cosine"] + w["judge"]
    final = (
        w["skill_overlap"] * skill_overlap + w["cosine"] * cosine_sim + w["judge"] * judge_score
    ) / total_weight

    final = round(final, 4)
    verdict = apply_thresholds(final, {})

    breakdown = {
        "skill_overlap": round(skill_overlap, 4),
        "cosine_sim": round(cosine_sim, 4),
        "judge_score": round(judge_score, 4),
        "weights": {k: w[k] for k in ("skill_overlap", "cosine", "judge")},
        # weighted contribution of each signal (sums to final * total_weight before normalise)
        "contributions": {
            "skill_overlap": round(w["skill_overlap"] * skill_overlap / total_weight, 4),
            "cosine": round(w["cosine"] * cosine_sim / total_weight, 4),
            "judge": round(w["judge"] * judge_score / total_weight, 4),
        },
    }

    return final, verdict, breakdown


def apply_thresholds(score: float, thresholds: dict) -> str:
    """Map a 0–1 score to Fit / Maybe / Reject using configurable thresholds."""
    t = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}
    if score >= t["fit"]:
        return "Fit"
    if score >= t["maybe"]:
        return "Maybe"
    return "Reject"
