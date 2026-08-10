from __future__ import annotations

import reflex as rx

from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.job_picker import job_picker
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.upload_state import CANONICAL_FIELDS, FIELD_LABELS, UploadState

UPLOAD_ID = "candidate_upload"


def _mapping_row(field: str) -> rx.Component:
    label = FIELD_LABELS.get(field, field)
    required = (field == "name") | (field == "email")
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.text(label, size="2", weight="medium"),
                rx.cond(
                    required,
                    rx.badge("required", color_scheme="red", variant="soft", size="1"),
                    rx.badge("optional", color_scheme="gray", variant="soft", size="1"),
                ),
                spacing="2",
                align="center",
            ),
            rx.text(field, size="1", color=rx.color("gray", 10)),
            spacing="0",
            min_width="160px",
        ),
        rx.icon("arrow-right", size=14, color=rx.color("gray", 8)),
        rx.select.root(
            rx.select.trigger(placeholder="— not mapped —", width="240px"),
            rx.select.content(
                rx.foreach(
                    UploadState.raw_columns,
                    lambda col: rx.select.item(col, value=col),  # type: ignore[call-arg]
                ),
            ),
            value=UploadState.mapping[field],
            on_change=lambda v: UploadState.set_mapping_field(field, v),
            size="2",
        ),
        spacing="4",
        align="center",
        width="100%",
        padding_y="2",
    )


def _mapping_panel() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon("table-2", size=18, color=rx.color("violet", 9)),
            rx.text("Map your columns", size="3", weight="bold"),
            spacing="2",
            align="center",
        ),
        rx.text(
            "We detected these columns from your file. Confirm or adjust the mapping before uploading.",
            size="2",
            color=rx.color("gray", 11),
        ),
        rx.divider(),
        rx.vstack(
            rx.foreach(
                CANONICAL_FIELDS,
                _mapping_row,
            ),
            width="100%",
            spacing="1",
        ),
        rx.divider(),
        rx.hstack(
            rx.button(
                "Cancel",
                variant="soft",
                color_scheme="gray",
                on_click=UploadState.cancel_mapping,
                size="2",
            ),
            rx.button(
                rx.icon("upload", size=16),
                "Confirm & Upload",
                on_click=UploadState.confirm_upload,
                loading=UploadState.is_uploading,
                size="2",
                color_scheme="violet",
            ),
            spacing="3",
            justify="end",
            width="100%",
        ),
        width="100%",
        spacing="3",
        padding="4",
        border=f"1px solid {rx.color('violet', 5)}",
        border_radius="var(--radius-4)",
        background=rx.color("violet", 1),
    )


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
                    rx.cond(
                        ~UploadState.show_mapping,
                        rx.vstack(
                            rx.upload(
                                rx.vstack(
                                    rx.icon("cloud-upload", size=28, color=rx.color("gray", 9)),
                                    rx.text(
                                        "Drag & drop, or click to select a file", size="2"
                                    ),
                                    rx.text(
                                        ".xlsx or .csv", size="1", color=rx.color("gray", 10)
                                    ),
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
                            rx.button(
                                rx.cond(
                                    UploadState.is_previewing,
                                    rx.spinner(size="2"),
                                    rx.icon("scan", size=16),
                                ),
                                rx.cond(
                                    UploadState.is_previewing,
                                    "Detecting columns…",
                                    "Preview & Map Columns",
                                ),
                                on_click=UploadState.handle_upload(
                                    rx.upload_files(upload_id=UPLOAD_ID)
                                ),
                                loading=UploadState.is_previewing,
                                size="3",
                                width="fit-content",
                                color_scheme="violet",
                            ),
                            width="100%",
                            spacing="4",
                        ),
                        _mapping_panel(),
                    ),
                    rx.cond(
                        UploadState.upload_error != "",
                        rx.callout(
                            UploadState.upload_error,
                            icon="triangle-alert",
                            color_scheme="red",
                        ),
                    ),
                    rx.cond(
                        UploadState.upload_result_message != "",
                        rx.callout(
                            UploadState.upload_result_message,
                            icon="check",
                            color_scheme="green",
                        ),
                    ),
                    width="100%",
                    spacing="4",
                ),
            ),
        ),
    )
