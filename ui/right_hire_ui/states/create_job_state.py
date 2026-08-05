from __future__ import annotations

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState


class CreateJobState(AppState):
    title: str = ""
    jd_raw: str = ""
    fit_threshold: float = 0.70
    maybe_threshold: float = 0.40
    is_submitting: bool = False
    error_message: str = ""
    created_job_id: str = ""
    created_job_jd_parsed: dict = {}  # noqa: RUF012 — Reflex rx.State vars use plain mutable defaults

    def set_title(self, value: str) -> None:
        self.title = value

    def set_jd_raw(self, value: str) -> None:
        self.jd_raw = value

    def set_fit_threshold(self, value: list[float]) -> None:
        self.fit_threshold = value[0]

    def set_maybe_threshold(self, value: list[float]) -> None:
        self.maybe_threshold = value[0]

    async def submit(self):
        self.error_message = ""
        if not self.title or not self.jd_raw:
            self.error_message = "Title and job description are required."
            return

        self.is_submitting = True
        self.created_job_id = ""
        self.created_job_jd_parsed = {}
        yield

        try:
            job = await api_client.create_job(
                self.title, self.jd_raw, self.fit_threshold, self.maybe_threshold
            )
            self.created_job_id = job["id"]
            self.created_job_jd_parsed = job.get("jd_parsed") or {}
            yield rx.toast.success(f"Job created! ID: {job['id']}")
        except httpx.HTTPError as e:
            self.error_message = f"API error: {e}"
            yield rx.toast.error(self.error_message)
        finally:
            self.is_submitting = False
