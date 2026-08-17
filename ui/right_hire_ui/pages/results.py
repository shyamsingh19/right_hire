from __future__ import annotations

from typing import Any

import reflex as rx

from right_hire_ui.components.badges import (
    confidence_badge,
    signal_chip,
    status_badge,
    verdict_pill,
)
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.job_picker import job_picker
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.results_state import ResultsState

RESUME_UPLOAD_ID = "candidate_resume_upload"


# ── Candidate queue (tabbed triage view) ─────────────────────────────────────


def _queue_tab_button(label: str, count: rx.Var, value: str) -> rx.Component:
    is_active = ResultsState.queue_tab == value
    return rx.button(
        rx.text(label, size="2", weight="medium"),
        rx.cond(
            count > 0,
            rx.badge(
                count.to(str),
                size="1",
                variant="soft",
                color_scheme=rx.cond(is_active, "gray", "violet"),
                radius="full",
            ),
        ),
        on_click=ResultsState.set_queue_tab(value),
        variant=rx.cond(is_active, "solid", "soft"),
        color_scheme=rx.cond(is_active, "violet", "gray"),
        size="2",
    )


def _queue_tabs() -> rx.Component:
    return rx.hstack(
        _queue_tab_button("All", ResultsState.total_count, "All"),
        _queue_tab_button("Fit", ResultsState.fit_count, "Fit"),
        _queue_tab_button("Maybe", ResultsState.maybe_count, "Maybe"),
        _queue_tab_button("Reject", ResultsState.reject_count, "Reject"),
        spacing="2",
        wrap="wrap",
    )


def _missing_skill_tag(skill: str) -> rx.Component:
    return rx.badge(skill, variant="soft", color_scheme="red", size="1")


def _queue_card(row: dict) -> rx.Component:
    has_eval = row["has_eval"].to(bool)
    is_error = row["is_error"].to(bool)
    verdict = row["verdict"].to(str)
    missing_skills = row["missing_skills"].to(list[str])
    verdict_color = rx.match(
        verdict,
        ("Fit", "green"),
        ("Maybe", "amber"),
        ("Reject", "red"),
        "gray",
    )
    border_color = rx.match(
        verdict,
        ("Fit", rx.color("green", 7)),
        ("Maybe", rx.color("amber", 7)),
        ("Reject", rx.color("red", 7)),
        rx.color("gray", 5),
    )
    return rx.vstack(
        rx.hstack(
            rx.text(row["name"].to(str), weight="bold", size="3"),
            rx.spacer(),
            rx.cond(
                is_error,
                rx.badge(
                    rx.icon("triangle-alert", size=12),
                    "Needs attention",
                    color_scheme="orange",
                    variant="soft",
                    size="2",
                    radius="full",
                ),
                rx.cond(
                    has_eval,
                    rx.badge(
                        verdict + " (" + row["score_pct_display"].to(str) + ")",
                        color_scheme=verdict_color,
                        variant="soft",
                        size="2",
                        radius="full",
                    ),
                    status_badge(row["status"].to(str)),
                ),
            ),
            width="100%",
            align="center",
        ),
        rx.text(
            row["email"].to(str) + " • " + row["yoe"].to(str) + " yrs • " + row["location"].to(str),
            size="2",
            color=rx.color("gray", 10),
        ),
        rx.cond(
            missing_skills.length() > 0,
            rx.hstack(
                rx.text("Missing:", size="1", color=rx.color("gray", 10)),
                rx.foreach(missing_skills, _missing_skill_tag),
                wrap="wrap",
                gap="1",
                align="center",
            ),
        ),
        rx.divider(),
        _row_actions(row),
        spacing="2",
        align="start",
        width="100%",
        padding="1em 1.25em",
        border_width="1.5px",
        border_style="solid",
        border_color=border_color,
        border_radius="var(--radius-3)",
        background=rx.color("gray", 2),
    )


def _candidate_queue() -> rx.Component:
    rows = ResultsState.queue_rows
    return rx.vstack(
        rx.hstack(
            rx.heading(
                "Candidate queue (" + ResultsState.total_count.to(str) + ")",
                size="4",
                weight="bold",
            ),
            rx.spacer(),
            _queue_tabs(),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="3",
        ),
        rx.cond(
            rows.length() == 0,
            empty_state("No candidates in this bucket.", icon="search-x"),
            rx.vstack(
                rx.foreach(rows, _queue_card),
                spacing="3",
                width="100%",
            ),
        ),
        rx.cond(
            ResultsState.has_more,
            rx.button(
                "Load more",
                on_click=ResultsState.load_more,
                loading=ResultsState.is_loading,
                variant="soft",
                size="2",
                margin_top="0.25em",
            ),
        ),
        rx.divider(),
        rx.hstack(
            rx.text("Bulk triage:", size="2", weight="medium", color=rx.color("gray", 10)),
            rx.spacer(),
            rx.button(
                rx.icon("download", size=14),
                "Export CSV",
                on_click=ResultsState.export_csv,
                loading=ResultsState.is_exporting,
                variant="soft",
                size="2",
            ),
            rx.button(
                rx.icon("list-checks", size=14),
                "Batch Shortlist",
                on_click=ResultsState.export_shortlist,
                loading=ResultsState.is_exporting,
                size="2",
            ),
            width="100%",
            align="center",
        ),
        spacing="4",
        width="100%",
    )


# ── Reasoning card sub-components ────────────────────────────────────────────


def _breakdown_row(row: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row["signal"].to(str), font_weight="500"),
        rx.table.cell(row["raw"].to(str), text_align="center"),
        rx.table.cell(row["weight"].to(str), text_align="center", color=rx.color("gray", 10)),
        rx.table.cell(
            rx.badge(row["contribution"].to(str), variant="soft", color_scheme="violet", size="1"),
            text_align="center",
        ),
    )


def _score_breakdown_table(breakdown_rows) -> rx.Component:
    return rx.vstack(
        rx.text("Score breakdown", weight="medium", size="2"),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Signal"),
                    rx.table.column_header_cell("Raw score", text_align="center"),
                    rx.table.column_header_cell("Weight", text_align="center"),
                    rx.table.column_header_cell("Contribution", text_align="center"),
                ),
            ),
            rx.table.body(
                rx.foreach(breakdown_rows, _breakdown_row),
            ),
            variant="surface",
            size="1",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def _rubric_row(row: dict) -> rx.Component:
    return rx.hstack(
        rx.text(row["criterion"].to(str), weight="medium", size="2"),
        rx.badge(row["score"].to(str), variant="soft", color_scheme="violet", size="1"),
        rx.text(row["reason"].to(str), size="2", color=rx.color("gray", 11)),
        spacing="2",
        align="start",
    )


def _skill_tag(skill: str) -> rx.Component:
    return rx.badge(skill, variant="outline", color_scheme="blue", size="1")


# ── Score distribution card ──────────────────────────────────────────────────


def _histogram_bar(bucket: dict, max_count: rx.Var) -> rx.Component:
    height_pct = rx.cond(max_count > 0, (bucket["count"].to(int) / max_count) * 100, 0)
    return rx.vstack(
        rx.box(
            height=f"{height_pct}%",
            min_height="2px",
            width="100%",
            background=rx.color("violet", 8),
            border_radius="2px 2px 0 0",
        ),
        rx.text(bucket["count"].to(str), size="1", color=rx.color("gray", 10)),
        rx.text(bucket["bucket"].to(str), size="1", color=rx.color("gray", 9)),
        height="140px",
        justify="end",
        align="center",
        spacing="1",
        width="100%",
    )


def _score_distribution_card() -> rx.Component:
    stats = ResultsState.batch_stats
    histogram = ResultsState.histogram
    max_count = ResultsState.max_histogram_count
    return rx.cond(
        ResultsState.is_loading_stats,
        rx.center(rx.spinner(), padding="2em"),
        rx.cond(
            histogram.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.text("Score distribution", weight="bold", size="3"),
                    rx.spacer(),
                    rx.text(
                        stats["evaluated"].to(str)
                        + " evaluated of "
                        + stats["total_candidates"].to(str)
                        + " candidates",
                        size="1",
                        color=rx.color("gray", 10),
                    ),
                    width="100%",
                    align="center",
                ),
                rx.hstack(
                    rx.foreach(histogram, lambda b: _histogram_bar(b, max_count)),
                    spacing="2",
                    align="end",
                    width="100%",
                ),
                rx.divider(),
                rx.text(
                    "Recalibrate Fit / Maybe thresholds",
                    weight="medium",
                    size="2",
                ),
                rx.grid(
                    rx.vstack(
                        rx.hstack(
                            rx.text("Fit threshold", size="2"),
                            rx.spacer(),
                            rx.badge(
                                ResultsState.draft_fit_threshold.to_string(),
                                color_scheme="green",
                                variant="soft",
                            ),
                            width="100%",
                        ),
                        rx.slider(
                            value=[ResultsState.draft_fit_threshold],
                            on_change=ResultsState.set_draft_fit_threshold,
                            min=0,
                            max=1,
                            step=0.05,
                            width="100%",
                        ),
                        width="100%",
                        spacing="1",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("Maybe threshold", size="2"),
                            rx.spacer(),
                            rx.badge(
                                ResultsState.draft_maybe_threshold.to_string(),
                                color_scheme="amber",
                                variant="soft",
                            ),
                            width="100%",
                        ),
                        rx.slider(
                            value=[ResultsState.draft_maybe_threshold],
                            on_change=ResultsState.set_draft_maybe_threshold,
                            min=0,
                            max=1,
                            step=0.05,
                            width="100%",
                        ),
                        width="100%",
                        spacing="1",
                    ),
                    columns="2",
                    width="100%",
                    spacing="4",
                ),
                rx.button(
                    rx.icon("sliders-horizontal", size=14),
                    "Apply thresholds",
                    on_click=ResultsState.recalibrate_thresholds,
                    loading=ResultsState.is_recalibrating,
                    size="2",
                    variant="soft",
                    width="fit-content",
                ),
                spacing="3",
                width="100%",
                padding="1em",
                border=f"1px solid {rx.color('gray', 5)}",
                border_radius="var(--radius-3)",
            ),
            rx.fragment(),
        ),
    )


# ── Candidate inspector (split-screen audit view) ────────────────────────────


def _inspector_left(row: dict) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            verdict_pill(row["verdict"].to(str)),
            rx.text(row["score_display"].to(str), size="3", weight="medium"),
            rx.cond(
                row["confidence"].to(str) != "",
                confidence_badge(row["confidence"].to(str)),
            ),
            spacing="2",
            align="center",
        ),
        rx.cond(
            row["summary"].to(str) != "",
            rx.callout(row["summary"].to(str), icon="info", color_scheme="blue", size="1"),
        ),
        rx.hstack(
            rx.foreach(
                row["matched_skills"].to(list[str]),
                lambda s: signal_chip(s, "match"),
            ),
            wrap="wrap",
            gap="1",
        ),
        rx.cond(
            row["breakdown_rows"].to(list[dict[str, Any]]).length() > 0,
            _score_breakdown_table(row["breakdown_rows"].to(list[dict[str, Any]])),
        ),
        rx.cond(
            row["rubric_rows"].to(list[dict[str, Any]]).length() > 0,
            rx.vstack(
                rx.text("Rubric scores", weight="medium", size="2"),
                rx.foreach(row["rubric_rows"].to(list[dict[str, Any]]), _rubric_row),
                align="start",
                spacing="2",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        align="start",
        overflow_y="auto",
        height="100%",
    )


def _inspector_right() -> rx.Component:
    return rx.vstack(
        rx.text("Original resume", weight="medium", size="2"),
        rx.box(
            rx.text(
                ResultsState.inspect_resume_text,
                size="2",
                white_space="pre-wrap",
                font_family="var(--code-font-family)",
            ),
            padding="1em",
            border=f"1px solid {rx.color('gray', 5)}",
            border_radius="var(--radius-3)",
            background=rx.color("gray", 2),
            width="100%",
            height="100%",
            overflow_y="auto",
        ),
        spacing="2",
        width="100%",
        height="100%",
    )


def _candidate_inspector_modal() -> rx.Component:
    row = ResultsState.inspect_row
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(row["name"].to(str)),
            rx.grid(
                _inspector_left(row),
                _inspector_right(),
                columns="2",
                spacing="4",
                width="100%",
                height="60vh",
            ),
            rx.flex(
                rx.dialog.close(rx.button("Close", variant="soft", color_scheme="gray")),
                justify="end",
                margin_top="1em",
            ),
            max_width="90vw",
            width="1100px",
        ),
        open=ResultsState.inspect_candidate_id != "",
        on_open_change=lambda _open: ResultsState.close_inspector(),
    )


# ── Result item ───────────────────────────────────────────────────────────────


def _delete_candidate_dialog(row: dict) -> rx.Component:
    """Deleting removes the candidate and their evaluation for good — confirm first."""
    candidate_id = row["candidate_id"].to(str)
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash-2", size=12),
                "Delete",
                size="1",
                variant="ghost",
                color_scheme="red",
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete this candidate?"),
            rx.alert_dialog.description(
                f"{row['name'].to(str)} and their evaluation will be permanently removed. "
                "This can't be undone.",
            ),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(
                    rx.button(
                        "Delete",
                        color_scheme="red",
                        on_click=ResultsState.delete_candidate(candidate_id),
                        loading=ResultsState.deleting_candidate_id == candidate_id,
                    ),
                ),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
    )


def _row_actions(row: dict) -> rx.Component:
    is_error = row["is_error"].to(bool)
    candidate_id = row["candidate_id"].to(str)
    return rx.hstack(
        rx.cond(
            is_error,
            rx.button(
                rx.icon("refresh-cw", size=12),
                "Retry",
                size="1",
                variant="soft",
                color_scheme="orange",
                on_click=ResultsState.retry_candidate(candidate_id),
                loading=ResultsState.retrying_candidate_id == candidate_id,
            ),
        ),
        rx.cond(
            is_error,
            rx.button(
                rx.icon("file-up", size=12),
                "Attach Resume PDF",
                size="1",
                variant="soft",
                color_scheme="orange",
                on_click=ResultsState.set_resume_target_id(candidate_id),
            ),
        ),
        rx.button(
            rx.icon("scan-search", size=12),
            "Inspect",
            size="1",
            variant="soft",
            on_click=ResultsState.open_inspector(candidate_id),
        ),
        rx.spacer(),
        _delete_candidate_dialog(row),
        width="100%",
        spacing="2",
    )


def _attach_resume_block() -> rx.Component:
    """For candidates whose sheet had no resume_url, or whose link couldn't be fetched —
    attach the file directly instead. Costs 1 credit, same as a sheet row."""
    return rx.vstack(
        rx.text("Attach a resume file", weight="medium", size="2"),
        rx.text(
            "Uploads the file for one candidate and re-queues them. Accepts .pdf, .txt, .md.",
            size="1",
            color=rx.color("gray", 11),
        ),
        rx.hstack(
            job_picker(
                ResultsState.candidate_options,
                ResultsState.resume_target_id,
                ResultsState.set_resume_target_id,
                placeholder="Select a candidate...",
            ),
            width="100%",
        ),
        rx.upload(
            rx.hstack(
                rx.icon("file-up", size=18, color=rx.color("gray", 9)),
                rx.text("Drag & drop, or click to select", size="2"),
                spacing="2",
                align="center",
            ),
            rx.foreach(
                rx.selected_files(RESUME_UPLOAD_ID),
                lambda f: rx.badge(f, variant="soft", color_scheme="violet"),
            ),
            id=RESUME_UPLOAD_ID,
            multiple=False,
            max_files=1,
            accept={"application/pdf": [".pdf"], "text/plain": [".txt", ".md"]},
            border=f"1.5px dashed {rx.color('gray', 7)}",
            border_radius="var(--radius-4)",
            padding="1.25em",
            width="100%",
        ),
        rx.button(
            "Attach & re-queue",
            on_click=ResultsState.attach_resume(rx.upload_files(upload_id=RESUME_UPLOAD_ID)),
            loading=ResultsState.is_attaching,
            size="2",
            variant="soft",
            width="fit-content",
        ),
        spacing="2",
        width="100%",
    )


# ── Page ──────────────────────────────────────────────────────────────────────


def _processing_status_banner() -> rx.Component:
    """Live status bar shown while any candidates are pending or processing.

    Displays per-status counts, a spinner, and a Cancel button that marks all
    pending candidates as cancelled (processing ones are mid-flight and unaffected).
    """
    return rx.cond(
        ResultsState.has_loaded & ResultsState.has_active,
        rx.hstack(
            rx.spinner(size="2", color=rx.color("violet", 9)),
            rx.vstack(
                rx.text(
                    "Processing in progress",
                    size="2",
                    weight="medium",
                ),
                rx.hstack(
                    rx.cond(
                        ResultsState.pending_count > 0,
                        rx.badge(
                            rx.icon("clock", size=10),
                            ResultsState.pending_count.to(str) + " pending",
                            color_scheme="gray",
                            variant="soft",
                            size="1",
                        ),
                    ),
                    rx.cond(
                        ResultsState.processing_count > 0,
                        rx.badge(
                            rx.icon("loader", size=10),
                            ResultsState.processing_count.to(str) + " processing",
                            color_scheme="blue",
                            variant="soft",
                            size="1",
                        ),
                    ),
                    rx.badge(
                        rx.icon("check", size=10),
                        ResultsState.done_count.to(str) + " done",
                        color_scheme="green",
                        variant="soft",
                        size="1",
                    ),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                spacing="1",
            ),
            rx.spacer(),
            rx.cond(
                ResultsState.needs_attention_count > 0,
                rx.button(
                    rx.icon("refresh-cw", size=14),
                    "Retry all failed",
                    on_click=ResultsState.retry_all_failed,
                    loading=ResultsState.is_retrying_all,
                    size="2",
                    variant="soft",
                    color_scheme="orange",
                ),
            ),
            rx.cond(
                ResultsState.pending_count > 0,
                rx.button(
                    rx.icon("circle-x", size=14),
                    "Cancel pending",
                    on_click=ResultsState.cancel_pending,
                    loading=ResultsState.is_cancelling,
                    size="2",
                    variant="soft",
                    color_scheme="red",
                ),
            ),
            padding="1.25em 1.75em",
            border=f"1px solid {rx.color('violet', 5)}",
            border_radius="var(--radius-3)",
            background=rx.color("violet", 2),
            width="100%",
            align="center",
            spacing="3",
        ),
    )


def _summary_stat(label: str, value: rx.Var, color_scheme: str) -> rx.Component:
    return rx.vstack(
        rx.text(value.to(str), size="6", weight="bold", color=rx.color(color_scheme, 9)),
        rx.text(label, size="1", color=rx.color("gray", 10)),
        spacing="0",
        align="center",
    )


def _failure_reason_row(item: dict) -> rx.Component:
    return rx.hstack(
        rx.icon("triangle-alert", size=12, color=rx.color("orange", 9)),
        rx.text(item["label"].to(str), size="2"),
        rx.spacer(),
        rx.badge(item["count"].to(str), variant="soft", color_scheme="orange", size="1"),
        width="100%",
        align="center",
    )


def _results_summary_panel() -> rx.Component:
    """Batch-level rollup shown once results are loaded: verdict counts plus a
    breakdown of *why* any candidates need attention, so the cause of a failed
    batch (private Drive links, LLM outage, etc.) is visible at a glance."""
    return rx.cond(
        ResultsState.has_loaded & (ResultsState.total_count > 0),
        rx.vstack(
            rx.hstack(
                _summary_stat("Total", ResultsState.total_count, "gray"),
                _summary_stat("Fit", ResultsState.fit_count, "green"),
                _summary_stat("Maybe", ResultsState.maybe_count, "amber"),
                _summary_stat("Reject", ResultsState.reject_count, "red"),
                _summary_stat("Needs attention", ResultsState.needs_attention_count, "orange"),
                spacing="6",
                width="100%",
                justify="center",
            ),
            rx.cond(
                ResultsState.failure_reason_counts.length() > 0,
                rx.vstack(
                    rx.divider(),
                    rx.text("Why candidates need attention", weight="medium", size="2"),
                    rx.foreach(ResultsState.failure_reason_counts, _failure_reason_row),
                    spacing="2",
                    width="100%",
                    align="start",
                ),
            ),
            padding="1em",
            border=f"1px solid {rx.color('gray', 5)}",
            border_radius="var(--radius-3)",
            width="100%",
            spacing="3",
        ),
    )


def _delete_job_dialog() -> rx.Component:
    """Confirm before deleting a job and all its data — this is irreversible."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash-2", size=14),
                "Delete job",
                disabled=ResultsState.selected_job_id == "",
                size="3",
                variant="soft",
                color_scheme="red",
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete this job?"),
            rx.alert_dialog.description(
                "All candidates and evaluation results for this job will be permanently deleted. "
                "This cannot be undone.",
            ),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(
                    rx.button(
                        "Delete job",
                        color_scheme="red",
                        on_click=ResultsState.delete_job(ResultsState.selected_job_id),
                        loading=ResultsState.is_deleting_job,
                    ),
                ),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
    )


def _delete_all_candidates_dialog() -> rx.Component:
    """Confirm before wiping every candidate for the current job. Unlike deleting the
    job itself, this keeps the JD/weights/thresholds so a fresh batch can be uploaded."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash", size=14),
                "Delete all candidates",
                disabled=ResultsState.selected_job_id == "",
                size="3",
                variant="soft",
                color_scheme="red",
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete all candidates for this job?"),
            rx.alert_dialog.description(
                "All candidates and their evaluation results for this job will be permanently "
                "deleted. The job itself (description, weights, thresholds) is kept, so you can "
                "upload a fresh batch afterward. This cannot be undone.",
            ),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("Cancel", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(
                    rx.button(
                        "Delete all candidates",
                        color_scheme="red",
                        on_click=ResultsState.delete_all_candidates,
                        loading=ResultsState.is_deleting_all,
                    ),
                ),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
    )


def results_page() -> rx.Component:
    return page_shell(
        section_card(
            "Evaluation Results",
            rx.cond(
                ResultsState.is_loading_jobs,
                rx.center(rx.spinner(size="3"), padding="2em"),
                rx.cond(
                    ResultsState.jobs.length() == 0,
                    empty_state("No jobs found. Create one on the 'Create Job' page first."),
                    rx.vstack(
                        rx.hstack(
                            rx.box(
                                job_picker(
                                    ResultsState.job_options,
                                    ResultsState.selected_job_id,
                                    ResultsState.set_selected_job_id,
                                ),
                                flex="1",
                                min_width="0",
                            ),
                            width="100%",
                            spacing="3",
                        ),
                        rx.hstack(
                            rx.button(
                                "Load Results",
                                on_click=ResultsState.load_results,
                                loading=ResultsState.is_loading,
                                size="3",
                            ),
                            _delete_all_candidates_dialog(),
                            _delete_job_dialog(),
                            spacing="3",
                            width="fit-content",
                        ),
                        _processing_status_banner(),
                        _results_summary_panel(),
                        rx.cond(ResultsState.has_loaded, _score_distribution_card()),
                        rx.cond(
                            ResultsState.load_error != "",
                            rx.callout(
                                ResultsState.load_error, icon="triangle-alert", color_scheme="red"
                            ),
                        ),
                        rx.cond(
                            ResultsState.has_loaded & (ResultsState.display_rows.length() == 0),
                            empty_state("No results found.", icon="search-x"),
                            rx.fragment(
                                _candidate_queue(),
                                rx.divider(margin_y="1em"),
                                _attach_resume_block(),
                            ),
                        ),
                        width="100%",
                        spacing="4",
                    ),
                ),
            ),
        ),
        _candidate_inspector_modal(),
    )
