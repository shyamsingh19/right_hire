from __future__ import annotations

from typing import Any

import reflex as rx

from right_hire_ui.components.badges import (
    confidence_badge,
    signal_chip,
    status_badge,
    verdict_pill,
)
from right_hire_ui.components.buttons import button
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.job_picker import job_picker
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.results_state import ResultsState

RESUME_UPLOAD_ID = "candidate_resume_upload"


# ── Candidate queue (tabbed triage view) ─────────────────────────────────────


def _queue_tab_button(label: str, count: rx.Var, value: str) -> rx.Component:
    """Counts are always rendered, zero included — a tab with no number reads as
    "not loaded" rather than "none in this bucket"."""
    is_active = ResultsState.queue_tab == value
    return rx.button(
        rx.text(label + " (" + count.to(str) + ")", size="2", weight="medium"),
        on_click=ResultsState.set_queue_tab(value),
        variant="ghost",
        color_scheme=rx.cond(is_active, "violet", "gray"),
        size="2",
        border_radius="0",
        padding="0.4em 0.7em",
        border_bottom="2px solid",
        border_color=rx.cond(is_active, rx.color("violet", 9), "transparent"),
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
    return rx.badge(skill, variant="outline", color_scheme="red", size="1")


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
    candidate_id = row["candidate_id"].to(str)
    is_selected = ResultsState.selected_ids.contains(candidate_id)
    return rx.vstack(
        rx.hstack(
            # Hidden until the card is hovered or focused (see .rh-select in
            # styles.css); forced visible whenever anything is selected, so an active
            # selection is never invisible. Driven by a class, not an inline opacity —
            # an inline style would beat the :hover rule.
            rx.box(
                rx.checkbox(
                    checked=is_selected,
                    on_change=ResultsState.toggle_selected(candidate_id),
                    size="1",
                    aria_label="Select " + row["name"].to(str),
                ),
                class_name=rx.cond(
                    ResultsState.selected_count > 0, "rh-select rh-select-shown", "rh-select"
                ),
                display="flex",
                align_items="center",
            ),
            rx.text(row["name"].to(str), weight="bold", size="3"),
            rx.spacer(),
            rx.cond(
                is_error,
                # A failed fetch/parse is a processing state, not a verdict — never
                # let it read as a judgement on the candidate.
                rx.badge(
                    rx.spinner(size="1"),
                    "Processing…",
                    color_scheme="blue",
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
            color=rx.color("gray", 11),
        ),
        rx.cond(
            missing_skills.length() > 0,
            rx.hstack(
                rx.text("Missing:", size="1", color=rx.color("gray", 11)),
                rx.foreach(missing_skills, _missing_skill_tag),
                wrap="wrap",
                gap="1",
                align="center",
            ),
        ),
        rx.divider(),
        _row_actions(row),
        class_name="rh-row",
        spacing="2",
        align="start",
        width="100%",
        padding="1em 1.25em",
        border_width="1px",
        border_style="solid",
        border_color=border_color,
        border_radius="var(--radius-3)",
        background="var(--rh-card)",
    )


def _candidate_queue() -> rx.Component:
    rows = ResultsState.queue_rows
    return rx.vstack(
        rx.hstack(
            rx.tooltip(
                rx.checkbox(
                    checked=ResultsState.all_visible_selected,
                    on_change=ResultsState.toggle_select_all,
                    size="1",
                    aria_label="Select all candidates in this filter",
                ),
                content="Select all in this filter",
            ),
            _queue_tabs(),
            rx.spacer(),
            button(
                rx.icon("sliders-horizontal", size=14),
                "Calibrate thresholds",
                tier="secondary",
                on_click=ResultsState.toggle_calibrate,
                size="2",
            ),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="3",
            border_bottom=f"1px solid {rx.color('gray', 5)}",
            padding_bottom="0.25em",
        ),
        rx.cond(ResultsState.show_calibrate, _score_distribution_card()),
        rx.cond(
            (ResultsState.fit_count == 0) & (ResultsState.total_count > 0),
            rx.callout(
                "No candidates meet the Fit threshold ("
                + ResultsState.draft_fit_threshold.to_string()
                + "). Review the Maybe bucket, or calibrate the thresholds.",
                icon="info",
                color_scheme="blue",
                size="1",
            ),
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
        spacing="4",
        width="100%",
    )


# ── Reasoning card sub-components ────────────────────────────────────────────


def _breakdown_row(row: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(row["signal"].to(str), font_weight="500"),
        rx.table.cell(row["raw"].to(str), text_align="center"),
        rx.table.cell(row["weight"].to(str), text_align="center", color=rx.color("gray", 11)),
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


def _histogram_bar(bar: dict) -> rx.Component:
    tone = bar["tone"].to(str)
    color = rx.match(
        tone,
        ("fit", "var(--rh-fit)"),
        ("maybe", "var(--rh-maybe)"),
        ("reject", "var(--rh-reject)"),
        "var(--rh-processing)",
    )
    return rx.vstack(
        rx.box(
            height=bar["height_pct"].to(str) + "%",
            min_height="2px",
            width="100%",
            background=color,
            border_radius="2px 2px 0 0",
        ),
        rx.text(bar["count"].to(str), size="1", color=rx.color("gray", 11)),
        rx.text(bar["bucket"].to(str), size="1", color=rx.color("gray", 11)),
        height="140px",
        justify="end",
        align="center",
        spacing="1",
        width="100%",
    )


def _threshold_marker(fraction: rx.Var, color: str, label: str) -> rx.Component:
    """Dashed line over the chart at a threshold, so a bucket the cutoff runs
    through is readable rather than implied by its bar color."""
    return rx.box(
        rx.text(
            label,
            size="1",
            color=color,
            position="absolute",
            top="-1.15em",
            left="0.25em",
            white_space="nowrap",
        ),
        position="absolute",
        left=(fraction * 100).to_string() + "%",
        top="0",
        bottom="0",
        border_left="1px dashed " + color,
        pointer_events="none",
    )


def _score_distribution_card() -> rx.Component:
    stats = ResultsState.batch_stats
    histogram = ResultsState.histogram
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
                        color=rx.color("gray", 11),
                    ),
                    width="100%",
                    align="center",
                ),
                rx.box(
                    rx.hstack(
                        rx.foreach(ResultsState.histogram_bars, _histogram_bar),
                        spacing="2",
                        align="end",
                        width="100%",
                    ),
                    _threshold_marker(
                        ResultsState.draft_maybe_threshold, "var(--rh-maybe-text)", "Maybe"
                    ),
                    _threshold_marker(
                        ResultsState.draft_fit_threshold, "var(--rh-fit-text)", "Fit"
                    ),
                    position="relative",
                    width="100%",
                    padding_top="1.25em",
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
                            aria_label="Fit threshold",
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
                            aria_label="Maybe threshold",
                        ),
                        width="100%",
                        spacing="1",
                    ),
                    columns="2",
                    width="100%",
                    spacing="4",
                ),
                button(
                    rx.icon("check", size=14),
                    "Apply thresholds",
                    tier="secondary",
                    on_click=ResultsState.recalibrate_thresholds,
                    loading=ResultsState.is_recalibrating,
                    size="2",
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


def _delete_candidate_dialog() -> rx.Component:
    """One dialog for the whole queue, opened by a card's ⋯ menu (a dialog nested in
    an open Radix menu unmounts with the menu). Deleting removes the candidate and
    their evaluation for good — confirm first."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Delete this candidate?"),
            rx.alert_dialog.description(
                ResultsState.pending_delete_candidate_name
                + " and their evaluation will be permanently removed. This can't be undone.",
            ),
            rx.flex(
                button(
                    "Cancel",
                    tier="ghost",
                    on_click=ResultsState.cancel_delete_candidate,
                    auto_focus=True,
                ),
                rx.button(
                    "Delete",
                    color_scheme="red",
                    on_click=ResultsState.delete_candidate(
                        ResultsState.pending_delete_candidate_id
                    ),
                    loading=ResultsState.deleting_candidate_id != "",
                ),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
        open=ResultsState.pending_delete_candidate_id != "",
        on_open_change=lambda _open: ResultsState.cancel_delete_candidate(),
    )


def _row_actions(row: dict) -> rx.Component:
    is_error = row["is_error"].to(bool)
    candidate_id = row["candidate_id"].to(str)
    return rx.hstack(
        button(
            rx.icon("scan-search", size=12),
            "Inspect",
            tier="tertiary",
            size="1",
            on_click=ResultsState.open_inspector(candidate_id),
        ),
        rx.cond(
            is_error,
            button(
                rx.icon("refresh-cw", size=12),
                "Retry",
                tier="ghost",
                size="1",
                on_click=ResultsState.retry_candidate(candidate_id),
                loading=ResultsState.retrying_candidate_id == candidate_id,
            ),
        ),
        rx.spacer(),
        rx.menu.root(
            rx.menu.trigger(
                rx.icon_button(
                    rx.icon("ellipsis", size=14),
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                    aria_label="More actions for " + row["name"].to(str),
                ),
            ),
            rx.menu.content(
                rx.menu.item(
                    rx.icon("file-up", size=12),
                    "Attach resume file…",
                    on_click=ResultsState.set_resume_target_id(candidate_id),
                ),
                rx.menu.separator(),
                rx.menu.item(
                    rx.icon("trash-2", size=12),
                    "Delete candidate",
                    color="var(--rh-reject-text)",
                    on_click=ResultsState.ask_delete_candidate(candidate_id),
                ),
            ),
        ),
        width="100%",
        spacing="2",
        align="center",
    )


def _attach_resume_block() -> rx.Component:
    """For candidates whose sheet had no resume_url, or whose link couldn't be fetched —
    attach the file directly instead. Costs 1 credit, same as a sheet row.

    Collapsed by default; a card's ⋯ → "Attach resume file…" opens it with that
    candidate already selected."""
    form = rx.vstack(
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
        button(
            "Attach & re-queue",
            tier="secondary",
            on_click=ResultsState.attach_resume(rx.upload_files(upload_id=RESUME_UPLOAD_ID)),
            loading=ResultsState.is_attaching,
            size="2",
            width="fit-content",
        ),
        spacing="2",
        width="100%",
        padding="1em",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="var(--radius-3)",
    )
    return rx.vstack(
        button(
            rx.icon("file-up", size=14),
            "Attach a resume file",
            tier="tertiary",
            on_click=ResultsState.toggle_attach,
            size="2",
            width="fit-content",
        ),
        rx.cond(ResultsState.show_attach, form),
        spacing="2",
        width="100%",
    )


# ── Page ──────────────────────────────────────────────────────────────────────


def _failure_reason_row(item: dict) -> rx.Component:
    return rx.hstack(
        rx.icon("triangle-alert", size=12, color=rx.color("blue", 10)),
        rx.text(item["label"].to(str), size="1", color=rx.color("gray", 11)),
        rx.text("×" + item["count"].to(str), size="1", color=rx.color("gray", 11)),
        spacing="2",
        align="center",
    )


def _processing_banner() -> rx.Component:
    """One banner for everything that isn't a verdict: candidates still queued, and
    candidates whose processing failed and can be re-queued. Keeps processing state
    out of the per-candidate score badges, where it read as a candidate judgement.

    Cancel only affects 'pending' candidates — ones a worker already picked up are
    mid-flight and can't be interrupted.
    """
    needs = ResultsState.needs_attention_count
    return rx.cond(
        ResultsState.has_loaded & (ResultsState.has_active | (needs > 0)),
        rx.hstack(
            rx.cond(
                ResultsState.has_active,
                rx.spinner(size="2"),
                rx.icon("refresh-cw", size=18, color=rx.color("blue", 10)),
            ),
            rx.vstack(
                rx.cond(
                    needs > 0,
                    rx.text(
                        needs.to(str)
                        + rx.cond(needs == 1, " candidate needs ", " candidates need ")
                        + "reprocessing",
                        size="2",
                        weight="medium",
                    ),
                    rx.text("Processing in progress", size="2", weight="medium"),
                ),
                rx.hstack(
                    rx.cond(
                        ResultsState.pending_count > 0,
                        rx.badge(
                            ResultsState.pending_count.to(str) + " pending",
                            color_scheme="gray",
                            variant="soft",
                            size="1",
                        ),
                    ),
                    rx.cond(
                        ResultsState.processing_count > 0,
                        rx.badge(
                            ResultsState.processing_count.to(str) + " processing",
                            color_scheme="blue",
                            variant="soft",
                            size="1",
                        ),
                    ),
                    rx.foreach(ResultsState.failure_reason_counts, _failure_reason_row),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.cond(
                needs > 0,
                button(
                    rx.icon("refresh-cw", size=14),
                    "Retry all",
                    tier="secondary",
                    on_click=ResultsState.retry_all_failed,
                    loading=ResultsState.is_retrying_all,
                    size="2",
                ),
            ),
            rx.cond(
                ResultsState.pending_count > 0,
                button(
                    "Cancel pending",
                    tier="danger",
                    on_click=ResultsState.cancel_pending,
                    loading=ResultsState.is_cancelling,
                    size="2",
                ),
            ),
            padding="0.9em 1.25em",
            border=f"1px solid {rx.color('blue', 6)}",
            border_radius="var(--radius-3)",
            background=rx.color("blue", 2),
            width="100%",
            align="center",
            spacing="3",
        ),
    )


def _summary_pill(label: str, count: rx.Var, color: str, tab: str = "") -> rx.Component:
    """Compact rollup that doubles as a filter shortcut — the old five-number stats
    block sat above the queue and pushed the actual work off-screen.

    Rendered as a real button when it filters, so it gets keyboard focus and a focus
    ring for free instead of being a div with an onclick.
    """
    if not tab:
        return rx.badge(
            count.to(str) + " " + label,
            variant="soft",
            color_scheme=color,
            size="2",
            radius="full",
        )
    is_active = ResultsState.queue_tab == tab
    return rx.button(
        count.to(str) + " " + label,
        on_click=ResultsState.toggle_queue_tab(tab),
        variant=rx.cond(is_active, "solid", "soft"),
        color_scheme=color,
        size="2",
        radius="full",
        cursor="pointer",
        aria_pressed=is_active.to_string(),
        aria_label=rx.cond(is_active, "Clear the " + label + " filter", "Filter to " + label),
    )


def _summary_pills() -> rx.Component:
    in_flight = (
        ResultsState.pending_count
        + ResultsState.processing_count
        + ResultsState.needs_attention_count
    )
    return rx.hstack(
        _summary_pill("Fit", ResultsState.fit_count, "green", "Fit"),
        _summary_pill("Maybe", ResultsState.maybe_count, "amber", "Maybe"),
        _summary_pill("Reject", ResultsState.reject_count, "red", "Reject"),
        rx.cond(in_flight > 0, _summary_pill("Processing", in_flight, "blue")),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _bulk_action_bar() -> rx.Component:
    """Pinned to the viewport rather than inserted above the queue: an inline bar
    would shove every card down the moment a checkbox is ticked."""
    n = ResultsState.selected_count
    return rx.cond(
        n > 0,
        rx.box(
            rx.hstack(
                rx.text(n.to(str) + " selected", size="2", weight="medium"),
                rx.spacer(),
                button(
                    rx.icon("download", size=14),
                    "Export selected",
                    tier="secondary",
                    on_click=ResultsState.export_selected,
                    size="2",
                ),
                button(
                    rx.icon("refresh-cw", size=14),
                    "Retry selected",
                    tier="ghost",
                    on_click=ResultsState.retry_selected,
                    loading=ResultsState.is_retrying_all,
                    disabled=ResultsState.selected_error_count == 0,
                    size="2",
                ),
                button(
                    rx.icon("trash-2", size=14),
                    "Delete selected",
                    tier="danger",
                    on_click=ResultsState.ask_job_action("selected"),
                    size="2",
                ),
                button(
                    "Clear selection",
                    tier="tertiary",
                    on_click=ResultsState.clear_selection,
                    size="2",
                ),
                spacing="3",
                align="center",
                width="100%",
                max_width="960px",
                margin="0 auto",
            ),
            position="fixed",
            bottom="0",
            left="0",
            right="0",
            padding="0.9em 2em",
            background="var(--rh-card)",
            border_top=f"1px solid {rx.color('gray', 6)}",
            box_shadow="0 -2px 12px rgba(0,0,0,0.08)",
            z_index="20",
            role="region",
            aria_label="Bulk actions for selected candidates",
        ),
    )


def _job_action_dialog() -> rx.Component:
    """Shared confirm for both destructive job actions, opened from the ⋯ menu.
    Deleting all candidates keeps the JD/weights/thresholds so a fresh batch can be
    uploaded; deleting the job takes everything."""
    is_job = ResultsState.confirm_job_action == "job"
    is_selected = ResultsState.confirm_job_action == "selected"
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(
                rx.cond(
                    is_selected,
                    "Delete " + ResultsState.selected_count.to(str) + " selected candidates?",
                    rx.cond(is_job, "Delete this job?", "Delete all candidates for this job?"),
                )
            ),
            rx.alert_dialog.description(
                rx.cond(
                    is_selected,
                    "The selected candidates and their evaluation results will be "
                    "permanently deleted. This cannot be undone.",
                    rx.cond(
                        is_job,
                        "All candidates and evaluation results for this job will be "
                        "permanently deleted. This cannot be undone.",
                        "All candidates and their evaluation results will be permanently "
                        "deleted. The job itself (description, weights, thresholds) is kept, "
                        "so you can upload a fresh batch afterward. This cannot be undone.",
                    ),
                ),
            ),
            rx.flex(
                button(
                    "Cancel",
                    tier="ghost",
                    on_click=ResultsState.cancel_job_action,
                    # Claims focus for the dialog: it is opened from a ⋯ menu, and the
                    # menu's own focus-restore fires after the dialog mounts.
                    auto_focus=True,
                ),
                rx.button(
                    rx.cond(
                        is_selected,
                        "Delete selected",
                        rx.cond(is_job, "Delete job", "Delete all candidates"),
                    ),
                    color_scheme="red",
                    on_click=ResultsState.run_job_action,
                    loading=ResultsState.is_deleting_job | ResultsState.is_deleting_all,
                ),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
        open=ResultsState.confirm_job_action != "",
        on_open_change=lambda _open: ResultsState.cancel_job_action(),
    )


def _top_bar() -> rx.Component:
    return rx.hstack(
        rx.box(
            job_picker(
                ResultsState.job_options,
                ResultsState.selected_job_id,
                ResultsState.set_selected_job_id,
            ),
            flex="1",
            min_width="200px",
        ),
        rx.cond(ResultsState.has_loaded, _summary_pills()),
        rx.spacer(),
        button(
            rx.icon("download", size=14),
            "Export shortlist",
            on_click=ResultsState.export_shortlist,
            disabled=ResultsState.selected_job_id == "",
            size="2",
        ),
        rx.tooltip(
            rx.icon_button(
                rx.icon("refresh-cw", size=14),
                variant="outline",
                color_scheme="violet",
                size="2",
                on_click=ResultsState.load_results,
                loading=ResultsState.is_loading,
                disabled=ResultsState.selected_job_id == "",
                aria_label="Reload results",
            ),
            content="Reload results",
        ),
        rx.menu.root(
            rx.menu.trigger(
                rx.icon_button(
                    rx.icon("ellipsis", size=16),
                    variant="ghost",
                    color_scheme="gray",
                    size="2",
                    aria_label="Job actions",
                ),
            ),
            rx.menu.content(
                rx.menu.item(
                    rx.icon("download", size=12),
                    "Export all (CSV)",
                    on_click=ResultsState.export_csv,
                ),
                rx.menu.separator(),
                rx.menu.item(
                    rx.icon("trash", size=12),
                    "Delete all candidates",
                    color="var(--rh-reject-text)",
                    on_click=ResultsState.ask_job_action("candidates"),
                ),
                rx.menu.item(
                    rx.icon("trash-2", size=12),
                    "Delete job",
                    color="var(--rh-reject-text)",
                    on_click=ResultsState.ask_job_action("job"),
                ),
            ),
        ),
        width="100%",
        align="center",
        spacing="3",
        wrap="wrap",
    )


def results_page() -> rx.Component:
    """Work queue first, analytics second: the top bar answers "how does this batch
    look", the queue answers "who do I interview", and the histogram/sliders stay
    behind "Calibrate thresholds"."""
    return page_shell(
        section_card(
            "Evaluation Results",
            rx.cond(
                ResultsState.is_loading_jobs,
                rx.center(rx.spinner(size="3"), padding="2em"),
                rx.cond(
                    ResultsState.jobs.length() == 0,
                    empty_state(
                        "No jobs yet",
                        "Create a job with screening criteria to start evaluating candidates.",
                        icon="file-plus",
                        cta_label="Create a Job →",
                        cta_href="/",
                    ),
                    rx.vstack(
                        _top_bar(),
                        _processing_banner(),
                        rx.cond(
                            ResultsState.load_error != "",
                            rx.callout(
                                ResultsState.load_error, icon="triangle-alert", color_scheme="red"
                            ),
                        ),
                        rx.cond(
                            ResultsState.selected_job_id == "",
                            empty_state(
                                "Select a job",
                                "Pick a job above to see its candidate queue.",
                                icon="list-checks",
                            ),
                            rx.cond(
                                ResultsState.is_loading & ~ResultsState.has_loaded,
                                rx.center(rx.spinner(size="3"), padding="2em"),
                                rx.cond(
                                    ResultsState.total_count == 0,
                                    empty_state(
                                        "No candidates uploaded",
                                        "Upload a spreadsheet of candidates to evaluate them "
                                        "against this job's criteria.",
                                        icon="upload",
                                        cta_label="Upload Candidates →",
                                        cta_href="/upload?job=" + ResultsState.selected_job_id,
                                    ),
                                    rx.fragment(
                                        _candidate_queue(),
                                        rx.divider(margin_y="1em"),
                                        _attach_resume_block(),
                                    ),
                                ),
                            ),
                        ),
                        width="100%",
                        spacing="4",
                    ),
                ),
            ),
        ),
        _bulk_action_bar(),
        overlays=[
            _candidate_inspector_modal(),
            _delete_candidate_dialog(),
            _job_action_dialog(),
        ],
        overlay_open=ResultsState.any_dialog_open,
    )
