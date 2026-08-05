from __future__ import annotations

from typing import Any

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState

VERDICT_FILTERS = ["All", "Fit", "Maybe", "Reject"]


def _build_row(item: dict) -> dict:
    """Flatten a CandidateWithEval dict into a display-ready row.

    Score formatting is standardized to 2 decimal places everywhere (the old
    Streamlit page mixed :.2f in the expander title with :.3f in the body —
    an unintentional inconsistency, fixed here rather than preserved).
    """
    c = item["candidate"]
    e = item.get("evaluation")
    verdict = e["verdict"] if e else c["status"]
    score = e.get("score") if e else None
    score_display = f"{score:.2f}" if score is not None else "N/A"

    rubric_rows = []
    if e and e.get("rubric"):
        reasons = e.get("reasons") or {}
        for criterion, crit_score in e["rubric"].items():
            rubric_rows.append(
                {
                    "criterion": criterion,
                    "score": f"{crit_score:.2f}",
                    "reason": reasons.get(criterion, ""),
                }
            )

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
