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

    # An evaluation with no verdict is a processing failure, not a rejection — surface it
    # as its own state so a recruiter never reads "Reject" for a resume we couldn't open.
    error = (rc.get("error") if rc else None) or ""
    is_error = bool(error)

    verdict = ("Unprocessed" if is_error else e["verdict"]) if e else c["status"]
    score = None if is_error else (e.get("score") if e else None)
    score_display = f"{score:.2f}" if score is not None else "—"

    # Rank beats percentile: "#2 of 3" is honest, "Top 100%" out of one candidate is noise.
    rank = rc.get("rank") if rc else None
    cohort_size = (rc.get("cohort_size") or 0) if rc else 0
    rank_display = f"#{rank} of {cohort_size}" if rank and cohort_size > 1 and not is_error else ""

    # Summary sentence
    summary = rc.get("summary", "") if rc else ""
    confidence = (rc.get("confidence") if rc else None) or ""

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
        "has_eval": e is not None and not is_error,
        "is_error": is_error,
        "error": error,
        "verdict": verdict,
        "score_display": score_display,
        "rank_display": rank_display,
        "summary": summary,
        "confidence": confidence,
        "matched_skills": matched_skills,
        "breakdown_rows": breakdown_rows,
        "model_used": (e.get("model_used") or "N/A") if e else "N/A",
        "rubric_rows": rubric_rows,
    }


_EMPTY_INSPECT_ROW: dict = {
    "candidate_id": "",
    "name": "",
    "email": "",
    "yoe": "",
    "location": "",
    "status": "",
    "has_eval": False,
    "is_error": False,
    "error": "",
    "verdict": "",
    "score_display": "—",
    "rank_display": "",
    "summary": "",
    "confidence": "",
    "matched_skills": [],
    "breakdown_rows": [],
    "model_used": "",
    "rubric_rows": [],
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
    resume_target_id: str = ""
    is_exporting: bool = False
    is_attaching: bool = False
    is_cancelling: bool = False

    batch_stats: dict = {}  # noqa: RUF012 — BatchStats.model_dump()
    is_loading_stats: bool = False
    draft_fit_threshold: float = 0.70
    draft_maybe_threshold: float = 0.40
    is_recalibrating: bool = False

    inspect_candidate_id: str = ""

    @rx.var
    def inspect_row(self) -> dict:
        for row in self.display_rows:
            if row["candidate_id"] == self.inspect_candidate_id:
                return row
        return _EMPTY_INSPECT_ROW

    @rx.var
    def inspect_resume_text(self) -> str:
        for item in self.results:
            if item["candidate"]["id"] == self.inspect_candidate_id:
                return item["candidate"].get("resume_text") or "No resume text available."
        return ""

    def open_inspector(self, candidate_id: str) -> None:
        self.inspect_candidate_id = candidate_id

    def close_inspector(self) -> None:
        self.inspect_candidate_id = ""

    def set_draft_fit_threshold(self, value: list[float]) -> None:
        self.draft_fit_threshold = value[0]

    def set_draft_maybe_threshold(self, value: list[float]) -> None:
        self.draft_maybe_threshold = value[0]

    @rx.var
    def max_histogram_count(self) -> int:
        buckets = self.batch_stats.get("histogram") or []
        return max((b.get("count", 0) for b in buckets), default=0)

    async def load_stats(self):
        if not self.selected_job_id:
            return
        self.is_loading_stats = True
        yield
        try:
            stats = await api_client.get_job_stats(self.api_key, self.selected_job_id)
            self.batch_stats = stats
            current = stats.get("current_thresholds") or {}
            self.draft_fit_threshold = current.get("fit", 0.70)
            self.draft_maybe_threshold = current.get("maybe", 0.40)
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Couldn't load score distribution: {e}")
        finally:
            self.is_loading_stats = False

    async def recalibrate_thresholds(self):
        """Applies the draft Fit/Maybe sliders via PATCH /jobs/{id}, then reloads both
        the stats card and results so verdicts reflect the new cutoffs immediately."""
        if not self.selected_job_id:
            return
        if self.draft_maybe_threshold >= self.draft_fit_threshold:
            yield rx.toast.error("Maybe threshold must be lower than Fit threshold.")
            return
        self.is_recalibrating = True
        yield
        try:
            await api_client.update_job_thresholds(
                self.api_key,
                self.selected_job_id,
                {"fit": self.draft_fit_threshold, "maybe": self.draft_maybe_threshold},
            )
            yield rx.toast.success("Thresholds updated.")
            yield ResultsState.load_stats
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Recalibration failed: {e}")
        finally:
            self.is_recalibrating = False

    @rx.var
    def pending_count(self) -> int:
        return sum(1 for r in self.results if r["candidate"]["status"] == "pending")

    @rx.var
    def processing_count(self) -> int:
        return sum(1 for r in self.results if r["candidate"]["status"] == "processing")

    @rx.var
    def done_count(self) -> int:
        return sum(1 for r in self.results if r["candidate"]["status"] == "done")

    @rx.var
    def total_count(self) -> int:
        return len(self.results)

    @rx.var
    def has_active(self) -> bool:
        return self.pending_count > 0 or self.processing_count > 0

    def set_selected_job_id(self, value: str) -> None:
        self.selected_job_id = value

    def set_verdict_filter(self, value: str) -> None:
        self.verdict_filter = value

    def set_resume_target_id(self, value: str) -> None:
        self.resume_target_id = value

    @rx.var
    def candidate_options(self) -> list[tuple[str, str]]:
        return [
            (item["candidate"]["id"], item["candidate"].get("name") or item["candidate"]["id"])
            for item in self.results
        ]

    async def delete_job(self, job_id: str):
        """Permanently delete the job and all its data, then clear the results view."""
        try:
            await api_client.delete_job(self.api_key, job_id)
            self.jobs = [j for j in self.jobs if j["id"] != job_id]
            self.results = []
            self.has_loaded = False
            self.selected_job_id = ""
            yield rx.toast.success("Job deleted.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Delete failed: {e}")

    async def cancel_pending(self):
        """Mark all queued-but-not-started candidates as cancelled.

        Only 'pending' candidates are affected — ones already picked up by a worker
        are mid-flight and cannot be interrupted without killing the worker process.
        """
        if not self.selected_job_id:
            return
        self.is_cancelling = True
        yield
        try:
            result = await api_client.cancel_pending_candidates(self.api_key, self.selected_job_id)
            n = result.get("cancelled_count", 0)
            if n:
                yield rx.toast.info(f"Cancelled {n} pending candidate{'s' if n != 1 else ''}.")
            else:
                yield rx.toast.info("No pending candidates to cancel.")
            # Refresh so the UI reflects the new 'failed' statuses immediately
            yield ResultsState.load_results
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Cancel failed: {e}")
        finally:
            self.is_cancelling = False

    async def export_csv(self):
        if not self.selected_job_id:
            return
        self.is_exporting = True
        yield
        try:
            csv_text = await api_client.export_results_csv(
                self.api_key, self.selected_job_id, self.verdict_filter
            )
            yield rx.download(
                data=csv_text, filename=f"right_hire_{self.selected_job_id}_results.csv"
            )
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Export failed: {e}")
        finally:
            self.is_exporting = False

    async def delete_candidate(self, candidate_id: str):
        """Permanently removes the candidate and their evaluation — the UI gates this
        behind a confirm dialog since it's the GDPR-style deletion path."""
        if not self.selected_job_id:
            return
        try:
            await api_client.delete_candidate(self.api_key, self.selected_job_id, candidate_id)
            self.results = [r for r in self.results if r["candidate"]["id"] != candidate_id]
            self.offset = len(self.results)
            yield rx.toast.success("Candidate deleted.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Delete failed: {e}")

    async def attach_resume(self, files: list[rx.UploadFile]):
        if not self.selected_job_id or not self.resume_target_id or not files:
            yield rx.toast.error("Pick a candidate and a file first.")
            return

        self.is_attaching = True
        yield
        try:
            file = files[0]
            filename = file.filename or "resume.pdf"
            data = await file.read()
            await api_client.upload_resume(
                self.api_key,
                self.selected_job_id,
                self.resume_target_id,
                filename,
                data,
                api_client.infer_resume_content_type(filename),
            )
            await self.load_credits()  # attaching a resume costs 1 credit
            yield rx.toast.success("Resume attached — candidate re-queued for evaluation.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(str(e))
        finally:
            self.is_attaching = False

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
        yield ResultsState.load_stats

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

    @rx.var
    def needs_attention_count(self) -> int:
        return sum(1 for r in self.display_rows if r["is_error"])

    @rx.var
    def fit_count(self) -> int:
        return sum(1 for r in self.display_rows if r["verdict"] == "Fit")

    @rx.var
    def maybe_count(self) -> int:
        return sum(1 for r in self.display_rows if r["verdict"] == "Maybe")

    @rx.var
    def reject_count(self) -> int:
        return sum(1 for r in self.display_rows if r["verdict"] == "Reject")

    @rx.var
    def failure_reason_counts(self) -> list[dict]:
        """Buckets processing-failure messages into broad categories so the summary
        panel can show *why* candidates need attention, not just how many."""
        counts: dict[str, int] = {}
        for r in self.display_rows:
            if not r["is_error"]:
                continue
            err = r["error"]
            if "Google Drive link is PRIVATE" in err:
                label = "Private Google Drive link"
            elif "LLM provider unavailable" in err:
                label = "Temporarily unavailable — retry processing"
            elif err:
                label = "Other error"
            else:
                label = "Unknown error"
            counts[label] = counts.get(label, 0) + 1
        return [
            {"label": label, "count": count}
            for label, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
