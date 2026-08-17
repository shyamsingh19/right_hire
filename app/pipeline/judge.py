from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.llm.base import LLMProvider
from app.schemas import JudgeOutput, ParsedJD

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def build_judge_prompt(matched: dict, parsed_jd: ParsedJD, rubric: dict) -> str:
    template = _load_prompt("judge.txt")

    required = ", ".join(parsed_jd.required_skills[:10]) or "N/A"
    matched_skills_str = ", ".join(matched.get("matched_skills", [])[:10]) or "none"
    matched_bullets_str = (
        "\n".join(f"- {b}" for b in matched.get("matched_bullets", [])[:5]) or "- (none)"
    )
    criteria_str = (
        ", ".join(rubric.keys()) if rubric else "technical_fit, communication, leadership"
    )

    return (
        template.replace("{{REQUIRED_SKILLS}}", required)
        .replace("{{MATCHED_SKILLS}}", matched_skills_str)
        .replace("{{MATCHED_BULLETS}}", matched_bullets_str)
        .replace("{{RUBRIC_CRITERIA}}", criteria_str)
    )


def judge_candidate(
    matched: dict,
    parsed_jd: ParsedJD,
    rubric: dict,
    provider: LLMProvider,
) -> JudgeOutput:
    """Call the LLM judge and return a structured JudgeOutput."""
    prompt = build_judge_prompt(matched, parsed_jd, rubric)
    try:
        return provider.complete_json(prompt, JudgeOutput, max_tokens=settings.judge_max_tokens)
    except Exception as exc:
        logger.error(
            "Judge LLM call failed [backend=%s model=%s]: %s",
            type(provider).__name__,
            getattr(provider, "model", "?"),
            exc,
            exc_info=True,
        )
        # Graceful fallback: derive verdict from skill_overlap
        overlap = matched.get("skill_overlap", 0.0)
        score = round(float(overlap), 4)
        verdict = "Fit" if score >= 0.7 else ("Maybe" if score >= 0.4 else "Reject")
        return JudgeOutput(
            scores={"technical_fit": score},
            reasons={"technical_fit": "LLM judge unavailable; score derived from skill overlap"},
            overall_score=score,
            verdict=verdict,
        )
