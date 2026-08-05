from __future__ import annotations

import asyncio
from typing import Any

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState

VERDICT_FILTERS = ["All", "Fit", "Maybe", "Reject"]

_ACTIVE_STATUSES = ("pending", "processing")
_POLL_INTERVAL_SECONDS = 5
_POLL_MAX_ITERATIONS = 24  # ~2 minutes, then the user can hit "Load Results" again


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
        labels = {
            "skill_overlap": "Skill overlap",
            "cosine_sim": "Semantic similarity",
            "judge_score": "LLM judge",
        }
        weights = breakdown.get("weights", {})
        contribs = breakdown.get("contributions", {})
        for key, label in labels.items():
            raw_key = key.replace("_score", "").replace("cosine_sim", "cosine")
            breakdown_rows.append(
                {
                    "signal": label,
                    "raw": f"{breakdown.get(key, 0):.2f}",
                    "weight": f"{weights.get(raw_key, weights.get(key, 0)):.0%}",
                    "contribution": f"{contribs.get(raw_key, contribs.get(key, 0)):.2f}",
                }
            )

    # Per-criterion rubric rows
    rubric_rows: list[dict] = []
    if e and e.get("rubric"):
        criterion_reasons = (rc.get("criterion_reasons") or {}) if rc else {}
        reasons = e.get("reasons") or {}
        for criterion, crit_score in e["rubric"].items():
            rubric_rows.append(
                {
                    "criterion": criterion,
                    "score": f"{crit_score:.2f}",
                    "reason": criterion_reasons.get(criterion) or reasons.get(criterion, ""),
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
    offset: int = 0
    page_size: int = 50
    has_more: bool = True

    def set_selected_job_id(self, value: str) -> None:
        self.selected_job_id = value

    def set_verdict_filter(self, value: str) -> None:
        self.verdict_filter = value

    async def load_results(self):
        """Fresh load from the top — resets pagination, then kicks off background polling
        so candidates that are still pending/processing update without a manual refresh
        (GET /jobs/{id}/results supports offset/limit; this is the page that uses it)."""
        if not self.selected_job_id:
            return

        self.offset = 0
        self.results = []
        self.has_more = True
        self.load_error = ""
        self.is_loading = True
        yield

        try:
            page = await api_client.get_results(
                self.api_key, self.selected_job_id, self.verdict_filter, 0, self.page_size
            )
            self.results = page
            self.offset = len(page)
            self.has_more = len(page) == self.page_size
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.load_error = str(e)
            self.results = []
            yield rx.toast.error(self.load_error)
        finally:
            self.is_loading = False
            self.has_loaded = True

        yield ResultsState.poll_for_updates

    async def load_more(self):
        if not self.selected_job_id or not self.has_more:
            return
        self.is_loading = True
        yield

        try:
            page = await api_client.get_results(
                self.api_key, self.selected_job_id, self.verdict_filter, self.offset, self.page_size
            )
            self.results = self.results + page
            self.offset += len(page)
            self.has_more = len(page) == self.page_size
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.load_error = str(e)
            yield rx.toast.error(self.load_error)
        finally:
            self.is_loading = False

    @rx.event(background=True)
    async def poll_for_updates(self):
        """Re-fetches the currently-loaded window every few seconds while any candidate
        is still pending/processing, so results show up without the user hitting reload."""
        for _ in range(_POLL_MAX_ITERATIONS):
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            async with self:
                if not self.selected_job_id:
                    return
                still_active = any(
                    row["candidate"]["status"] in _ACTIVE_STATUSES for row in self.results
                )
                if not still_active:
                    return
                job_id = self.selected_job_id
                verdict_filter = self.verdict_filter
                api_key = self.api_key
                window = max(len(self.results), self.page_size)

            try:
                page = await api_client.get_results(api_key, job_id, verdict_filter, 0, window)
            except (httpx.HTTPError, api_client.ApiError):
                continue

            async with self:
                self.results = page
                self.offset = len(page)

    @rx.var
    def display_rows(self) -> list[dict[str, Any]]:
        return [_build_row(item) for item in self.results]
