from __future__ import annotations

from typing import Any

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState

VERDICT_FILTERS = ["All", "Fit", "Maybe", "Reject"]


def _build_row(item: dict) -> dict:
    c = item["candidate"]
    e = item.get("evaluation")
    rc = e.get("reasoning_card") if e else None

    verdict = e["verdict"] if e else c["status"]
    score = e.get("score") if e else None
    score_display = f"{score:.2f}" if score is not None else "N/A"

    # Percentile from reasoning card
    percentile = rc.get("percentile") if rc else None
    percentile_display = f"Top {100 - int(percentile)}%" if percentile is not None else ""

    # Summary sentence
    summary = rc.get("summary", "") if rc else ""

    # Matched skills from reasoning card (preferred) or reasons fallback
    matched_skills: list[str] = []
    if rc and rc.get("matched_skills"):
        matched_skills = rc["matched_skills"]
    elif e and e.get("reasons"):
        matched_skills = e["reasons"].get("matched_skills", [])

    # Score breakdown
    breakdown: dict = (rc.get("score_breakdown") or {}) if rc else {}
    breakdown_rows: list[dict] = []
    if breakdown:
        labels = {"skill_overlap": "Skill overlap", "cosine_sim": "Semantic similarity", "judge_score": "LLM judge"}
        weights = breakdown.get("weights", {})
        contribs = breakdown.get("contributions", {})
        for key, label in labels.items():
            raw_key = key.replace("_score", "").replace("cosine_sim", "cosine")
            breakdown_rows.append({
                "signal": label,
                "raw": f"{breakdown.get(key, 0):.2f}",
                "weight": f"{weights.get(raw_key, weights.get(key, 0)):.0%}",
                "contribution": f"{contribs.get(raw_key, contribs.get(key, 0)):.2f}",
            })

    # Per-criterion rubric rows
    rubric_rows: list[dict] = []
    if e and e.get("rubric"):
        criterion_reasons = (rc.get("criterion_reasons") or {}) if rc else {}
        reasons = e.get("reasons") or {}
        for criterion, crit_score in e["rubric"].items():
            rubric_rows.append({
                "criterion": criterion,
                "score": f"{crit_score:.2f}",
                "reason": criterion_reasons.get(criterion) or reasons.get(criterion, ""),
            })

    return {
        "candidate_id": c["id"],
        "name": c.get("name") or "Unknown",
        "email": c.get("email") or "N/A",
        "yoe": str(c.get("yoe")) if c.get("yoe") is not None else "N/A",
        "location": c.get("location") or "N/A",
        "status": c["status"],
        "has_eval": e is not None,
        "verdict": verdict,
        "score_display": score_display,
        "percentile_display": percentile_display,
        "summary": summary,
        "matched_skills": matched_skills,
        "breakdown_rows": breakdown_rows,
        "model_used": (e.get("model_used") or "N/A") if e else "N/A",
        "rubric_rows": rubric_rows,
    }


class ResultsState(AppState):
    selected_job_id: str = ""
    verdict_filter: str = "All"
    results: list[dict] = []  # noqa: RUF012 — Reflex rx.State vars use plain mutable defaults
    is_loading: bool = False
    load_error: str = ""
    has_loaded: bool = False

    def set_selected_job_id(self, value: str) -> None:
        self.selected_job_id = value

    def set_verdict_filter(self, value: str) -> None:
        self.verdict_filter = value

    async def load_results(self):
        if not self.selected_job_id:
            return

        self.load_error = ""
        self.is_loading = True
        yield

        try:
            self.results = await api_client.get_results(self.selected_job_id, self.verdict_filter)
        except httpx.HTTPError as e:
            self.load_error = f"API error: {e}"
            self.results = []
            yield rx.toast.error(self.load_error)
        finally:
            self.is_loading = False
            self.has_loaded = True

    @rx.var
    def display_rows(self) -> list[dict[str, Any]]:
        return [_build_row(item) for item in self.results]
