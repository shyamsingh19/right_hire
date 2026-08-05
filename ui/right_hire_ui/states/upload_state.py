from __future__ import annotations

import httpx
import reflex as rx

from right_hire_ui import api_client
from right_hire_ui.states.app_state import AppState


class UploadState(AppState):
    selected_job_id: str = ""
    is_uploading: bool = False
    upload_result_message: str = ""
    upload_error: str = ""

    def set_selected_job_id(self, value: str) -> None:
        self.selected_job_id = value

    async def handle_upload(self, files: list[rx.UploadFile]):
        if not self.selected_job_id or not files:
            return

        self.upload_result_message = ""
        self.upload_error = ""
        self.is_uploading = True
        yield

        try:
            file = files[0]
            filename = file.filename or "upload"
            data = await file.read()
            content_type = api_client.infer_content_type(filename)
            result = await api_client.upload_candidates(
                self.selected_job_id, filename, data, content_type
            )
            self.upload_result_message = (
                f"Enqueued {result['queued_count']} candidates for evaluation."
            )
            yield rx.toast.success(self.upload_result_message)
        except httpx.HTTPError as e:
            self.upload_error = f"Upload failed: {e}"
            yield rx.toast.error(self.upload_error)
        finally:
            self.is_uploading = False
