from __future__ import annotations

import reflex as rx

from right_hire_ui.components.buttons import button
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.job_picker import job_picker
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.upload_state import CANONICAL_FIELDS, FIELD_LABELS, UploadState

UPLOAD_ID = "candidate_upload"

# Client-side view of the file input — rx.selected_files exposes names only, so the
# byte size shown in the audit spec isn't available without custom JS. Name + Remove
# is the honest subset.
_has_file = rx.selected_files(UPLOAD_ID).length() > 0


def _selected_file_row() -> rx.Component:
    return rx.hstack(
        rx.icon("file-spreadsheet", size=20, color=rx.color("violet", 9)),
        rx.text(rx.selected_files(UPLOAD_ID)[0], size="2", weight="medium"),
        button(
            "Remove",
            tier="danger",
            size="1",
            on_click=rx.clear_selected_files(UPLOAD_ID),
        ),
        spacing="3",
        align="center",
    )


def _mapping_row(field: str) -> rx.Component:
    label = FIELD_LABELS.get(field, field)
    required = (field == "name") | (field == "email")
    unmapped = required & (UploadState.mapping[field] == "")
    return rx.vstack(
        rx.hstack(
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
                rx.text(f"Right Hire field key: {field}", size="1", color=rx.color("gray", 11)),
                spacing="0",
                min_width="160px",
            ),
            rx.icon("arrow-right", size=14, color=rx.color("gray", 8)),
            rx.select.root(
                rx.select.trigger(
                    placeholder="— not mapped —",
                    width="240px",
                    color=rx.cond(unmapped, rx.color("red", 9), None),
                ),
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
        ),
        rx.cond(
            unmapped,
            rx.text(
                "Required — pick a column",
                size="1",
                color=rx.color("red", 9),
                aria_live="polite",
            ),
        ),
        spacing="1",
        width="100%",
        padding_y="0.85em",
        border_bottom=f"1px solid {rx.color('gray', 5)}",
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
        rx.hstack(
            rx.text(
                "SYSTEM FIELD",
                size="1",
                weight="bold",
                color=rx.color("gray", 11),
                letter_spacing="0.03em",
                min_width="160px",
            ),
            rx.box(width="14px"),
            rx.text(
                "MATCHED COLUMN FROM YOUR FILE",
                size="1",
                weight="bold",
                color=rx.color("violet", 10),
                letter_spacing="0.03em",
                width="240px",
            ),
            spacing="4",
            align="center",
            width="100%",
        ),
        rx.vstack(
            rx.foreach(
                CANONICAL_FIELDS,
                _mapping_row,
            ),
            width="100%",
            spacing="3",
        ),
        rx.cond(
            UploadState.mapping_error != "",
            rx.callout(
                UploadState.mapping_error,
                icon="triangle-alert",
                color_scheme="red",
                size="2",
                role="alert",
                padding="3",
            ),
        ),
        rx.divider(),
        rx.hstack(
            button(
                "Cancel",
                tier="ghost",
                on_click=UploadState.cancel_mapping,
                size="2",
            ),
            rx.tooltip(
                button(
                    rx.icon("upload", size=16),
                    "Confirm & Upload",
                    on_click=UploadState.confirm_upload,
                    loading=UploadState.is_uploading,
                    disabled=~UploadState.mapping_is_valid,
                    size="2",
                ),
                content=rx.cond(
                    UploadState.mapping_error != "",
                    UploadState.mapping_error,
                    "Ready to upload",
                ),
            ),
            spacing="3",
            justify="end",
            width="100%",
        ),
        width="100%",
        spacing="4",
        padding="1.5em",
        border=f"1px solid {rx.color('violet', 5)}",
        border_radius="var(--radius-4)",
        background="var(--rh-inset)",
    )


def _progress_panel() -> rx.Component:
    """Live pending/processing/done/failed counts for the batch just uploaded — polled
    via GET /jobs/{id}/progress (see UploadState.poll_progress). Text-labeled badges,
    not color-only, so the state reads correctly without relying on color perception."""
    p = UploadState.progress
    return rx.cond(
        UploadState.show_progress,
        rx.vstack(
            rx.hstack(
                rx.spinner(size="1"),
                rx.text("Processing this batch", size="2", weight="medium"),
                spacing="2",
                align="center",
            ),
            rx.hstack(
                rx.badge(
                    rx.icon("clock", size=10),
                    p["pending"].to_string() + " pending",
                    color_scheme="gray",
                    variant="soft",
                    size="1",
                    aria_label=p["pending"].to_string() + " candidates pending",
                ),
                rx.badge(
                    rx.icon("loader", size=10),
                    p["processing"].to_string() + " processing",
                    color_scheme="blue",
                    variant="soft",
                    size="1",
                    aria_label=p["processing"].to_string() + " candidates processing",
                ),
                rx.badge(
                    rx.icon("check", size=10),
                    p["done"].to_string() + " done",
                    color_scheme="green",
                    variant="soft",
                    size="1",
                    aria_label=p["done"].to_string() + " candidates done",
                ),
                rx.cond(
                    p["failed"].to(int) > 0,
                    rx.badge(
                        rx.icon("triangle-alert", size=10),
                        p["failed"].to_string() + " failed",
                        color_scheme="red",
                        variant="soft",
                        size="1",
                        aria_label=p["failed"].to_string() + " candidates failed",
                    ),
                ),
                spacing="2",
                flex_wrap="wrap",
            ),
            spacing="2",
            padding="3",
            border=f"1px solid {rx.color('violet', 5)}",
            border_radius="var(--radius-3)",
            background=rx.color("violet", 2),
            width="100%",
        ),
    )


def upload_candidates_page() -> rx.Component:
    return page_shell(
        section_card(
            "Upload Candidates",
            rx.cond(
                UploadState.is_loading_jobs,
                rx.center(rx.spinner(size="3"), padding="2em"),
                rx.cond(
                    UploadState.jobs.length() == 0,
                    empty_state(
                        "Create a job first",
                        "Before uploading candidates, you need a job with screening criteria "
                        "for them to be evaluated against.",
                        icon="file-plus",
                        cta_label="Create a Job →",
                        cta_href="/",
                    ),
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
                                    # Prompt is replaced by the filename once a file is
                                    # picked, so the zone always reflects its own state.
                                    rx.cond(
                                        _has_file,
                                        _selected_file_row(),
                                        rx.vstack(
                                            rx.icon(
                                                "cloud-upload", size=28, color=rx.color("gray", 9)
                                            ),
                                            rx.text(
                                                "Drag a .xlsx or .csv file here, or click to "
                                                "browse",
                                                size="2",
                                            ),
                                            rx.text(
                                                "Each row should be one candidate.",
                                                size="1",
                                                color=rx.color("gray", 11),
                                            ),
                                            align="center",
                                            spacing="1",
                                        ),
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
                                    min_height="200px",
                                    display="flex",
                                    align_items="center",
                                    justify_content="center",
                                    width="100%",
                                ),
                                rx.hstack(
                                    button(
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
                                        # A primary button that can only error is worse
                                        # than one that is visibly not ready yet.
                                        disabled=~_has_file,
                                        size="3",
                                    ),
                                    rx.spacer(),
                                    rx.link(
                                        "Download template (.csv)",
                                        href="/candidates_template.csv",
                                        download=True,
                                        size="2",
                                        color=rx.color("violet", 11),
                                    ),
                                    width="100%",
                                    align="center",
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
                            rx.vstack(
                                rx.callout(
                                    UploadState.upload_result_message,
                                    icon="check",
                                    color_scheme="green",
                                    width="100%",
                                ),
                                rx.hstack(
                                    rx.link(
                                        button("View Results →", size="3"),
                                        href="/results?job=" + UploadState.selected_job_id,
                                    ),
                                    button(
                                        "Upload more candidates",
                                        tier="tertiary",
                                        on_click=UploadState.upload_another,
                                        size="3",
                                    ),
                                    spacing="3",
                                    align="center",
                                ),
                                spacing="3",
                                width="100%",
                            ),
                        ),
                        _progress_panel(),
                        width="100%",
                        spacing="4",
                    ),
                ),
            ),
        ),
    )
