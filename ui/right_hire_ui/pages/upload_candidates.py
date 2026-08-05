from __future__ import annotations

import reflex as rx

from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.job_picker import job_picker
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.upload_state import UploadState

UPLOAD_ID = "candidate_upload"

_COLUMNS_DOC = """
**Expected columns** (case-insensitive, .xlsx or .csv):

| Column | Required |
|---|---|
| `name` | Yes |
| `email` | Yes |
| `resume_url` | Yes (Google Drive or direct link) |
| `yoe` | No |
| `location` | No |
"""


def upload_candidates_page() -> rx.Component:
    return page_shell(
        section_card(
            "Upload Candidates",
            rx.cond(
                UploadState.jobs.length() == 0,
                empty_state("No jobs found. Create one on the 'Create Job' page first."),
                rx.vstack(
                    job_picker(
                        UploadState.job_options,
                        UploadState.selected_job_id,
                        UploadState.set_selected_job_id,
                    ),
                    rx.upload(
                        rx.vstack(
                            rx.icon("cloud-upload", size=28, color=rx.color("gray", 9)),
                            rx.text("Drag & drop, or click to select a file", size="2"),
                            rx.text(".xlsx or .csv", size="1", color=rx.color("gray", 10)),
                            align="center",
                            spacing="1",
                        ),
                        rx.foreach(
                            rx.selected_files(UPLOAD_ID),
                            lambda f: rx.badge(f, variant="soft", color_scheme="violet"),
                        ),
                        id=UPLOAD_ID,
                        multiple=False,
                        max_files=1,
                        accept={
                            "text/csv": [".csv"],
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [
                                ".xlsx"
                            ],
                        },
                        border=f"1.5px dashed {rx.color('gray', 7)}",
                        border_radius="var(--radius-4)",
                        padding="2em",
                        width="100%",
                    ),
                    rx.cond(
                        UploadState.upload_error != "",
                        rx.callout(
                            UploadState.upload_error, icon="triangle-alert", color_scheme="red"
                        ),
                    ),
                    rx.cond(
                        UploadState.upload_result_message != "",
                        rx.callout(
                            UploadState.upload_result_message, icon="check", color_scheme="green"
                        ),
                    ),
                    rx.button(
                        "Upload & Enqueue",
                        on_click=UploadState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                        loading=UploadState.is_uploading,
                        size="3",
                        width="fit-content",
                    ),
                    width="100%",
                    spacing="4",
                ),
            ),
            rx.divider(),
            rx.markdown(_COLUMNS_DOC),
        ),
    )
