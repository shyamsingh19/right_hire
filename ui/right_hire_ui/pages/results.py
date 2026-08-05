from __future__ import annotations

from typing import Any

import reflex as rx

from right_hire_ui.components.badges import status_badge, verdict_pill
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.job_picker import job_picker
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.results_state import VERDICT_FILTERS, ResultsState


def _verdict_filter_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Filter by verdict"),
        rx.select.content(
            rx.foreach(VERDICT_FILTERS, lambda v: rx.select.item(v, value=v)),
        ),
        value=ResultsState.verdict_filter,
        on_change=ResultsState.set_verdict_filter,
    )


def _rubric_row(row: dict) -> rx.Component:
    return rx.hstack(
        rx.text(row["criterion"].to(str), weight="medium", size="2"),
        rx.badge(row["score"].to(str), variant="soft", color_scheme="violet", size="1"),
        rx.text(row["reason"].to(str), size="2", color=rx.color("gray", 11)),
        spacing="2",
        align="start",
    )


def _result_header(row: dict) -> rx.Component:
    has_eval = row["has_eval"].to(bool)
    return rx.hstack(
        rx.cond(
            has_eval, verdict_pill(row["verdict"].to(str)), status_badge(row["status"].to(str))
        ),
        rx.text(row["name"].to(str), weight="medium"),
        rx.text(f"score: {row['score_display'].to(str)}", size="2", color=rx.color("gray", 10)),
        spacing="3",
        align="center",
    )


def _result_content(row: dict) -> rx.Component:
    has_eval = row["has_eval"].to(bool)
    rubric_rows = row["rubric_rows"].to(list[dict[str, Any]])
    return rx.vstack(
        rx.grid(
            rx.vstack(
                rx.text(f"Email: {row['email'].to(str)}", size="2"),
                rx.text(f"YOE: {row['yoe'].to(str)}", size="2"),
                rx.text(f"Location: {row['location'].to(str)}", size="2"),
                align="start",
                spacing="1",
            ),
            rx.cond(
                has_eval,
                rx.vstack(
                    rx.text(f"Score: {row['score_display'].to(str)}", size="2"),
                    rx.text(f"Model: {row['model_used'].to(str)}", size="2"),
                    align="start",
                    spacing="1",
                ),
            ),
            columns="2",
            width="100%",
            spacing="4",
        ),
        rx.cond(
            rubric_rows.length() > 0,
            rx.vstack(
                rx.text("Rubric scores:", weight="medium", size="2"),
                rx.foreach(rubric_rows, _rubric_row),
                align="start",
                spacing="2",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        padding_top="0.75em",
    )


def _result_item(row: dict) -> rx.Component:
    return rx.accordion.item(
        header=_result_header(row),
        content=_result_content(row),
        value=row["candidate_id"].to(str),
    )


def results_page() -> rx.Component:
    return page_shell(
        section_card(
            "Evaluation Results",
            rx.cond(
                ResultsState.jobs.length() == 0,
                empty_state("No jobs found. Create one on the 'Create Job' page first."),
                rx.vstack(
                    rx.hstack(
                        job_picker(
                            ResultsState.job_options,
                            ResultsState.selected_job_id,
                            ResultsState.set_selected_job_id,
                        ),
                        _verdict_filter_select(),
                        width="100%",
                        spacing="3",
                    ),
                    rx.button(
                        "Load Results",
                        on_click=ResultsState.load_results,
                        loading=ResultsState.is_loading,
                        size="3",
                        width="fit-content",
                    ),
                    rx.cond(
                        ResultsState.load_error != "",
                        rx.callout(
                            ResultsState.load_error, icon="triangle-alert", color_scheme="red"
                        ),
                    ),
                    rx.cond(
                        ResultsState.has_loaded & (ResultsState.display_rows.length() == 0),
                        empty_state("No results found.", icon="search-x"),
                        rx.accordion.root(
                            rx.foreach(ResultsState.display_rows, _result_item),
                            type="multiple",
                            collapsible=True,
                            variant="surface",
                            width="100%",
                        ),
                    ),
                    width="100%",
                    spacing="4",
                ),
            ),
        ),
    )
