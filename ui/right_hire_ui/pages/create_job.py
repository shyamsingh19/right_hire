from __future__ import annotations

import reflex as rx

from right_hire_ui.components.cards import section_card
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.create_job_state import CreateJobState


def _threshold_slider(label: str, value, on_change) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="3", weight="medium"),
            rx.spacer(),
            rx.badge(value.to_string(), variant="soft", color_scheme="violet"),
            width="100%",
        ),
        rx.slider(
            value=[value],
            on_change=on_change,
            min=0,
            max=1,
            step=0.05,
            width="100%",
        ),
        width="100%",
        spacing="1",
    )


def _created_job_panel() -> rx.Component:
    return rx.cond(
        CreateJobState.created_job_id != "",
        rx.vstack(
            rx.callout(
                f"Job created! ID: {CreateJobState.created_job_id}",
                icon="check",
                color_scheme="green",
            ),
            rx.text("Parsed job description", weight="medium", size="2"),
            rx.code_block(
                CreateJobState.created_job_jd_parsed.to_string(),
                language="json",
            ),
            width="100%",
            spacing="3",
        ),
    )


def create_job_page() -> rx.Component:
    return page_shell(
        section_card(
            "Create a New Job",
            rx.text(
                "Paste a job description — it's parsed by the LLM into structured "
                "requirements, then used to evaluate every candidate you upload.",
                color=rx.color("gray", 11),
                size="2",
            ),
            rx.vstack(
                rx.text("Job Title", size="2", weight="medium"),
                rx.input(
                    placeholder="Senior Python Engineer",
                    value=CreateJobState.title,
                    on_change=CreateJobState.set_title,
                    width="100%",
                    size="3",
                ),
                width="100%",
                spacing="1",
            ),
            rx.vstack(
                rx.text("Job Description", size="2", weight="medium"),
                rx.text_area(
                    placeholder="Paste the full JD here...",
                    value=CreateJobState.jd_raw,
                    on_change=CreateJobState.set_jd_raw,
                    height="300px",
                    width="100%",
                ),
                width="100%",
                spacing="1",
            ),
            _threshold_slider(
                "Fit threshold", CreateJobState.fit_threshold, CreateJobState.set_fit_threshold
            ),
            _threshold_slider(
                "Maybe threshold",
                CreateJobState.maybe_threshold,
                CreateJobState.set_maybe_threshold,
            ),
            rx.cond(
                CreateJobState.error_message != "",
                rx.callout(CreateJobState.error_message, icon="triangle-alert", color_scheme="red"),
            ),
            rx.button(
                "Create Job",
                on_click=CreateJobState.submit,
                loading=CreateJobState.is_submitting,
                size="3",
                width="fit-content",
            ),
            _created_job_panel(),
        ),
    )
