from __future__ import annotations

import asyncio

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState

_PROGRESS_POLL_SECONDS = 4
_PROGRESS_POLL_MAX_ITERATIONS = 45  # ~3 minutes, matches a typical small-batch turnaround

CANONICAL_FIELDS = ["name", "email", "resume_url", "yoe", "location"]
FIELD_LABELS = {
    "name": "Candidate Name",
    "email": "Email",
    "resume_url": "Resume / CV Link",
    "yoe": "Years of Experience",
    "location": "Location",
}
# Must be non-empty for a row to be worth evaluating at all — kept in sync with the
# "required"/"optional" badges rendered per-row in pages/upload_candidates.py.
REQUIRED_FIELDS = ["name", "email"]


class UploadState(AppState):
    selected_job_id: str = ""
    is_uploading: bool = False
    upload_result_message: str = ""
    upload_error: str = ""

    # Preview / mapping state
    _pending_filename: str = ""
    _pending_data: bytes = b""
    _pending_content_type: str = ""

    is_previewing: bool = False
    show_mapping: bool = False
    raw_columns: list[str] = []
    # mapping: canonical_field -> raw column name (empty string = unmapped)
    mapping: dict[str, str] = {}

    # Live progress for the batch just uploaded — polled via GET /jobs/{id}/progress
    # (cheap counts-only endpoint) rather than the full results list this page doesn't
    # otherwise need. Cleared when the user starts a new upload.
    progress: dict = {}  # noqa: RUF012
    show_progress: bool = False

    def set_selected_job_id(self, value: str) -> None:
        self.selected_job_id = value

    def set_mapping_field(self, field: str, value: str) -> None:
        self.mapping[field] = value

    @rx.var
    def missing_required_fields(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if not self.mapping.get(f)]

    @rx.var
    def mapping_error(self) -> str:
        missing = self.missing_required_fields
        if not missing:
            return ""
        labels = ", ".join(FIELD_LABELS.get(f, f) for f in missing)
        return f"Map a column for {labels} before uploading — these fields are required."

    @rx.var
    def mapping_is_valid(self) -> bool:
        return not self.missing_required_fields

    def cancel_mapping(self) -> None:
        self.show_mapping = False
        self._pending_filename = ""
        self._pending_data = b""
        self._pending_content_type = ""
        self.raw_columns = []
        self.mapping = {}
        self.upload_error = ""

    async def handle_upload(self, files: list[rx.UploadFile]):
        if not self.selected_job_id or not files:
            return

        self.upload_result_message = ""
        self.upload_error = ""
        self.show_mapping = False
        self.show_progress = False
        self.progress = {}
        self.is_previewing = True
        yield

        try:
            file = files[0]
            filename = file.filename or "upload"
            data = await file.read()
            content_type = api_client.infer_content_type(filename)

            # Store for later use in confirm_upload
            self._pending_filename = filename
            self._pending_data = data
            self._pending_content_type = content_type

            result = await api_client.preview_candidates(
                self.api_key, self.selected_job_id, filename, data, content_type
            )
            self.raw_columns = result["columns"]
            # Convert None values to empty string for Reflex state compatibility
            self.mapping = {
                field: (result["mapping"].get(field) or "") for field in CANONICAL_FIELDS
            }
            self.show_mapping = True
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.upload_error = str(e)
            yield rx.toast.error(self.upload_error)
        finally:
            self.is_previewing = False

    async def confirm_upload(self):
        if not self._pending_filename:
            return
        if not self.mapping_is_valid:
            self.upload_error = self.mapping_error
            yield rx.toast.error(self.upload_error)
            return

        self.is_uploading = True
        self.upload_error = ""
        yield

        try:
            # Convert empty strings back to None before sending
            final_mapping = {field: (col if col else None) for field, col in self.mapping.items()}
            result = await api_client.upload_candidates(
                self.api_key,
                self.selected_job_id,
                self._pending_filename,
                self._pending_data,
                self._pending_content_type,
                column_mapping=final_mapping,
            )
            self.upload_result_message = (
                f"Enqueued {result['queued_count']} candidates for evaluation."
            )
            if result.get("failed_count"):
                self.upload_result_message += (
                    f" {result['failed_count']} could not be queued — check the queue service."
                )
            self.show_mapping = False
            self._pending_filename = ""
            self._pending_data = b""
            await self.load_credits()
            yield rx.toast.success(self.upload_result_message)
            self.show_progress = True
            yield UploadState.poll_progress
        except (httpx.HTTPError, api_client.ApiError) as e:
            self.upload_error = str(e)
            yield rx.toast.error(self.upload_error)
        finally:
            self.is_uploading = False

    @rx.event(background=True)
    async def poll_progress(self):
        """Live pending/processing/done/failed counts for the job just uploaded to,
        via the lightweight GET /jobs/{id}/progress endpoint (see app/api/jobs.py)."""
        async with self:
            job_id = self.selected_job_id
            api_key = self.api_key
        if not job_id:
            return

        for _ in range(_PROGRESS_POLL_MAX_ITERATIONS):
            try:
                progress = await api_client.get_job_progress(api_key, job_id)
            except (httpx.HTTPError, api_client.ApiError):
                await asyncio.sleep(_PROGRESS_POLL_SECONDS)
                continue

            async with self:
                self.progress = progress
                still_active = progress.get("pending", 0) > 0 or progress.get("processing", 0) > 0
            if not still_active:
                return
            await asyncio.sleep(_PROGRESS_POLL_SECONDS)
