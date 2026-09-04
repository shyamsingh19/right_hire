from __future__ import annotations

import asyncio
from typing import Any

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.formatting import bucket_tone, shortlist_csv
from right_hire_ui.states.app_state import AppState

VERDICT_FILTERS = ["All", "Fit", "Maybe", "Reject"]

_ACTIVE_STATUSES = ("pending", "processing")
_POLL_INTERVAL_SECONDS = 5
_POLL_MAX_ITERATIONS = 24  # ~2 minutes, then the user can hit "Load Results" again


def _build_row(item: dict, required_skills: list[str] | None = None) -> dict:
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
    score_pct_display = f"{score:.0%}" if score is not None else ""

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

    # Missing skills = job's required skills the candidate wasn't credited with matching.
    # Only meaningful once an evaluation exists — an unprocessed candidate's skills are
    # unknown, not "missing".
    missing_skills: list[str] = []
    if required_skills and not is_error and e is not None:
        matched_lower = {s.lower() for s in matched_skills}
        missing_skills = [s for s in required_skills if s.lower() not in matched_lower]

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
        "score_pct_display": score_pct_display,
        "rank_display": rank_display,
        "summary": summary,
        "confidence": confidence,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
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
    "score_pct_display": "",
    "rank_display": "",
    "summary": "",
    "confidence": "",
    "matched_skills": [],
    "missing_skills": [],
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
    is_deleting_all: bool = False
    is_deleting_job: bool = False
    deleting_candidate_id: str = ""
    retrying_candidate_id: str = ""
    is_retrying_all: bool = False

    batch_stats: dict = {}  # noqa: RUF012 — BatchStats.model_dump()
    is_loading_stats: bool = False
    draft_fit_threshold: float = 0.70
    draft_maybe_threshold: float = 0.40
    is_recalibrating: bool = False

    inspect_candidate_id: str = ""

    # Client-side tab over the already-loaded batch — instant, unlike verdict_filter which
    # re-queries the server. Keeps all four tab counts visible at once (mirrors the summary
    # panel), rather than only the counts for whichever filter was last loaded.
    queue_tab: str = "All"

    # Analytics (histogram + threshold sliders) are secondary to the queue, so they
    # stay collapsed until asked for.
    show_calibrate: bool = False
    # The attach-a-resume form is only relevant once a candidate has been picked for it.
    show_attach: bool = False

    def set_queue_tab(self, value: str) -> None:
        self.queue_tab = value

    def toggle_calibrate(self) -> None:
        self.show_calibrate = not self.show_calibrate

    def toggle_attach(self) -> None:
        self.show_attach = not self.show_attach

    # Destructive actions live in ⋯ menus, and a Radix dialog nested inside an open
    # menu unmounts with it — so the confirm dialogs are controlled by these instead.
    pending_delete_candidate_id: str = ""
    confirm_job_action: str = ""  # "" | "candidates" | "job"

    def ask_delete_candidate(self, candidate_id: str) -> None:
        self.pending_delete_candidate_id = candidate_id

    def cancel_delete_candidate(self) -> None:
        self.pending_delete_candidate_id = ""

    @rx.var
    def pending_delete_candidate_name(self) -> str:
        for r in self.display_rows:
            if r["candidate_id"] == self.pending_delete_candidate_id:
                return r["name"]
        return "This candidate"

    def ask_job_action(self, kind: str) -> None:
        self.confirm_job_action = kind

    def cancel_job_action(self) -> None:
        self.confirm_job_action = ""

    def run_job_action(self):
        kind = self.confirm_job_action
        self.confirm_job_action = ""
        if kind == "job":
            return ResultsState.delete_job(self.selected_job_id)
        if kind == "candidates":
            return ResultsState.delete_all_candidates
        return None

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
    def histogram(self) -> list[dict]:
        return self.batch_stats.get("histogram") or []

    @rx.var
    def max_histogram_count(self) -> int:
        buckets = self.histogram
        return max((b.get("count", 0) for b in buckets), default=0)

    @rx.var
    def histogram_bars(self) -> list[dict]:
        """Buckets with a bar height and a Fit/Maybe/Reject tone, recomputed from the
        *draft* sliders so colors track the thresholds as they are dragged."""
        buckets = self.histogram
        top = max((b.get("count", 0) for b in buckets), default=0)
        return [
            {
                "bucket": b["bucket"],
                "count": b.get("count", 0),
                "height_pct": (b.get("count", 0) / top * 100) if top else 0,
                "tone": bucket_tone(
                    b["bucket"], self.draft_fit_threshold, self.draft_maybe_threshold
                ),
            }
            for b in buckets
        ]

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

    def set_selected_job_id(self, value: str):
        self.selected_job_id = value
        self.results = []
        self.batch_stats = {}
        self.has_loaded = False
        return ResultsState.load_results

    async def init_from_query(self):
        """Pre-selects the job passed as ?job=<id> (how the Create Job and Upload
        pages hand off) and loads it, so the user lands on results, not a picker."""
        job_id = self.router.url.query_parameters.get("job", "")
        if job_id and any(j["id"] == job_id for j in self.jobs):
            self.selected_job_id = job_id
        if self.selected_job_id and not self.has_loaded:
            yield ResultsState.load_results

    def set_verdict_filter(self, value: str) -> None:
        self.verdict_filter = value

    def set_resume_target_id(self, value: str) -> None:
        self.resume_target_id = value
        self.show_attach = True

    @rx.var
    def selected_job_title(self) -> str:
        for j in self.jobs:
            if j["id"] == self.selected_job_id:
                return j["title"]
        return ""

    @rx.var
    def candidate_options(self) -> list[tuple[str, str]]:
        return [
            (item["candidate"]["id"], item["candidate"].get("name") or item["candidate"]["id"])
            for item in self.results
        ]

    async def delete_job(self, job_id: str):
        """Permanently delete the job and all its data, then clear the results view."""
        self.is_deleting_job = True
        yield
        try:
            await api_client.delete_job(self.api_key, job_id)
            self.jobs = [j for j in self.jobs if j["id"] != job_id]
            self.results = []
            self.has_loaded = False
            self.selected_job_id = ""
            yield rx.toast.success("Job deleted.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Delete failed: {e}")
        finally:
            self.is_deleting_job = False

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

    async def retry_candidate(self, candidate_id: str):
        """Re-queue a single failed candidate using its existing resume — no re-upload,
        no extra credit charge. For candidates with no resume on file, the backend rejects
        this and the UI falls back to prompting for an attachment instead."""
        if not self.selected_job_id:
            return
        self.retrying_candidate_id = candidate_id
        yield
        try:
            await api_client.retry_candidate(self.api_key, self.selected_job_id, candidate_id)
            yield rx.toast.info("Candidate re-queued for evaluation.")
            yield ResultsState.load_results
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(str(e))
        finally:
            self.retrying_candidate_id = ""

    async def retry_all_failed(self):
        """Re-queue every failed candidate in this job that still has a resume on file."""
        if not self.selected_job_id:
            return
        self.is_retrying_all = True
        yield
        try:
            result = await api_client.retry_failed_candidates(self.api_key, self.selected_job_id)
            retried = result.get("retried_count", 0)
            skipped = result.get("skipped_count", 0)
            if retried:
                msg = f"Re-queued {retried} candidate{'s' if retried != 1 else ''} for retry."
                if skipped:
                    msg += f" {skipped} skipped — no resume on file."
                yield rx.toast.success(msg)
                yield ResultsState.load_results
            elif skipped:
                yield rx.toast.info(
                    f"Nothing to retry — {skipped} failed candidate{'s' if skipped != 1 else ''} "
                    "have no resume on file. Attach a resume to retry them."
                )
            else:
                yield rx.toast.info("No failed candidates to retry.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Retry failed: {e}")
        finally:
            self.is_retrying_all = False

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

    def export_shortlist(self):
        """Bulk-triage shortcut: every Fit and Maybe candidate in the loaded batch,
        built client-side from the rows already on screen (no extra API round-trip),
        regardless of which queue tab is active."""
        rows = [r for r in self.display_rows if r["verdict"] in ("Fit", "Maybe")]
        if not rows:
            return rx.toast.info("Nothing to export — no Fit or Maybe candidates yet.")
        title = (self.selected_job_title or "job").lower().replace(" ", "_")
        return rx.download(data=shortlist_csv(rows), filename=f"right_hire_{title}_shortlist.csv")

    async def delete_candidate(self, candidate_id: str):
        """Permanently removes the candidate and their evaluation — the UI gates this
        behind a confirm dialog since it's the GDPR-style deletion path."""
        if not self.selected_job_id:
            return
        self.deleting_candidate_id = candidate_id
        yield
        try:
            await api_client.delete_candidate(self.api_key, self.selected_job_id, candidate_id)
            self.results = [r for r in self.results if r["candidate"]["id"] != candidate_id]
            self.offset = len(self.results)
            yield rx.toast.success("Candidate deleted.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Delete failed: {e}")
        finally:
            self.deleting_candidate_id = ""
            self.pending_delete_candidate_id = ""

    async def delete_all_candidates(self):
        """Wipe every candidate for the selected job, keeping the job (JD, weights,
        thresholds) intact so a fresh batch can be uploaded. Gated behind a confirm dialog."""
        if not self.selected_job_id:
            return
        self.is_deleting_all = True
        yield
        try:
            result = await api_client.delete_all_candidates(self.api_key, self.selected_job_id)
            n = result.get("deleted_count", 0)
            self.results = []
            self.offset = 0
            self.has_more = False
            self.batch_stats = {}
            if n:
                yield rx.toast.success(f"Deleted {n} candidate{'s' if n != 1 else ''}.")
            else:
                yield rx.toast.info("No candidates to delete.")
        except (httpx.HTTPError, api_client.ApiError) as e:
            yield rx.toast.error(f"Delete failed: {e}")
        finally:
            self.is_deleting_all = False

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
    def selected_job_required_skills(self) -> list[str]:
        for j in self.jobs:
            if j["id"] == self.selected_job_id:
                jd = j.get("jd_parsed") or {}
                return jd.get("required_skills") or []
        return []

    @rx.var
    def display_rows(self) -> list[dict[str, Any]]:
        required_skills = self.selected_job_required_skills
        return [_build_row(item, required_skills) for item in self.results]

    @rx.var
    def queue_rows(self) -> list[dict[str, Any]]:
        rows = self.display_rows
        if self.queue_tab == "All":
            return rows
        return [r for r in rows if r["verdict"] == self.queue_tab]

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
