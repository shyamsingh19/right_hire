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


def _weight_slider(label: str, value, on_change) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="2", weight="medium"),
            rx.spacer(),
            rx.badge(f"{value * 100:.0f}%", variant="soft", color_scheme="blue"),
            width="100%",
        ),
        rx.slider(value=[value], on_change=on_change, min=0, max=1, step=0.05, width="100%"),
        width="100%",
        spacing="1",
    )


def _step_indicator() -> rx.Component:
    return rx.hstack(
        rx.badge(
            "1. Job Description",
            variant=rx.cond(CreateJobState.step == 1, "solid", "soft"),
            color_scheme="violet",
            size="2",
        ),
        rx.icon("chevron-right", size=14, color=rx.color("gray", 9)),
        rx.badge(
            "2. Review & Calibrate",
            variant=rx.cond(CreateJobState.step == 2, "solid", "soft"),
            color_scheme="violet",
            size="2",
        ),
        spacing="2",
        align="center",
    )


# ── Step 1 ────────────────────────────────────────────────────────────────────


def _step_1() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Paste a job description — it's parsed by the LLM into structured requirements "
            "you can review and edit before the job goes live.",
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
        rx.cond(
            CreateJobState.error_message != "",
            rx.callout(CreateJobState.error_message, icon="triangle-alert", color_scheme="red"),
        ),
        rx.button(
            rx.icon("sparkles", size=14),
            "Parse JD Criteria",
            on_click=CreateJobState.parse_criteria,
            loading=CreateJobState.is_parsing,
            size="3",
            width="fit-content",
        ),
        width="100%",
        spacing="4",
    )


# ── Step 2 ────────────────────────────────────────────────────────────────────


def _skill_tag(skill: str, removable: bool = True) -> rx.Component:
    if not removable:
        return rx.badge(skill, variant="outline", color_scheme="gray", size="2")
    return rx.badge(
        rx.hstack(
            rx.text(skill),
            rx.icon(
                "x",
                size=12,
                cursor="pointer",
                on_click=CreateJobState.remove_required_skill(skill),
            ),
            spacing="1",
            align="center",
        ),
        variant="soft",
        color_scheme="violet",
        size="2",
    )


def _preferred_skill_tag(skill: str) -> rx.Component:
    return rx.badge(
        rx.hstack(
            rx.text(skill),
            rx.icon(
                "x",
                size=12,
                cursor="pointer",
                on_click=CreateJobState.remove_preferred_skill(skill),
            ),
            spacing="1",
            align="center",
        ),
        variant="soft",
        color_scheme="blue",
        size="2",
    )


def _skills_editor() -> rx.Component:
    return rx.vstack(
        rx.text("Required skills", weight="medium", size="2"),
        rx.flex(
            rx.foreach(CreateJobState.required_skills, lambda s: _skill_tag(s)),
            wrap="wrap",
            gap="2",
        ),
        rx.hstack(
            rx.input(
                placeholder="Add a required skill...",
                value=CreateJobState.new_skill_input,
                on_change=CreateJobState.set_new_skill_input,
                on_key_down=lambda k: rx.cond(
                    k == "Enter", CreateJobState.add_required_skill(), rx.console_log("")
                ),
                size="2",
                width="100%",
            ),
            rx.button("Add", on_click=CreateJobState.add_required_skill, size="2", variant="soft"),
            width="100%",
            spacing="2",
        ),
        rx.cond(
            CreateJobState.preferred_skills.length() > 0,
            rx.vstack(
                rx.text("Preferred skills", weight="medium", size="2"),
                rx.flex(
                    rx.foreach(CreateJobState.preferred_skills, _preferred_skill_tag),
                    wrap="wrap",
                    gap="2",
                ),
                spacing="2",
                width="100%",
                align="start",
            ),
        ),
        width="100%",
        spacing="3",
        align="start",
    )


def _weights_editor() -> rx.Component:
    return rx.vstack(
        rx.text("Scoring weights", weight="medium", size="3"),
        rx.text(
            "How much each signal contributes to the final score. Must sum to 100%.",
            size="1",
            color=rx.color("gray", 11),
        ),
        _weight_slider(
            "Skill overlap", CreateJobState.skill_weight, CreateJobState.set_skill_weight
        ),
        _weight_slider(
            "Semantic similarity", CreateJobState.cosine_weight, CreateJobState.set_cosine_weight
        ),
        _weight_slider("LLM judge", CreateJobState.judge_weight, CreateJobState.set_judge_weight),
        rx.cond(
            CreateJobState.weight_error != "",
            rx.callout(
                CreateJobState.weight_error, icon="triangle-alert", color_scheme="amber", size="1"
            ),
        ),
        width="100%",
        spacing="2",
    )


def _step_2() -> rx.Component:
    return rx.vstack(
        rx.callout(
            "Review the AI-extracted criteria below, edit as needed, then confirm to "
            "activate this job.",
            icon="info",
            color_scheme="blue",
        ),
        rx.grid(
            rx.vstack(
                rx.text("Minimum years of experience", size="2", weight="medium"),
                rx.hstack(
                    rx.slider(
                        value=[CreateJobState.min_yoe],
                        on_change=CreateJobState.set_min_yoe,
                        min=0,
                        max=20,
                        step=0.5,
                        width="100%",
                    ),
                    rx.badge(CreateJobState.min_yoe.to_string(), variant="soft"),
                    width="100%",
                    align="center",
                    spacing="2",
                ),
                width="100%",
                spacing="1",
            ),
            rx.vstack(
                rx.text("Location", size="2", weight="medium"),
                rx.input(
                    value=CreateJobState.location,
                    on_change=CreateJobState.set_location,
                    placeholder="e.g. Remote, San Francisco",
                    size="2",
                    width="100%",
                ),
                width="100%",
                spacing="1",
            ),
            columns="2",
            width="100%",
            spacing="4",
        ),
        _skills_editor(),
        rx.cond(
            CreateJobState.must_haves.length() > 0,
            rx.vstack(
                rx.text("Must-haves", weight="medium", size="2"),
                rx.flex(
                    rx.foreach(CreateJobState.must_haves, lambda m: _skill_tag(m, removable=False)),
                    wrap="wrap",
                    gap="2",
                ),
                spacing="2",
                width="100%",
                align="start",
            ),
        ),
        rx.divider(),
        _weights_editor(),
        rx.divider(),
        _threshold_slider(
            "Fit threshold", CreateJobState.fit_threshold, CreateJobState.set_fit_threshold
        ),
        _threshold_slider(
            "Maybe threshold",
            CreateJobState.maybe_threshold,
            CreateJobState.set_maybe_threshold,
        ),
        rx.cond(
            CreateJobState.threshold_error != "",
            rx.callout(
                CreateJobState.threshold_error,
                icon="triangle-alert",
                color_scheme="amber",
                width="100%",
            ),
        ),
        rx.cond(
            CreateJobState.error_message != "",
            rx.callout(CreateJobState.error_message, icon="triangle-alert", color_scheme="red"),
        ),
        rx.hstack(
            rx.button(
                rx.icon("arrow-left", size=14),
                "Back",
                on_click=CreateJobState.back_to_step_1,
                variant="soft",
                color_scheme="gray",
                size="3",
            ),
            rx.button(
                "Confirm & Activate Job",
                on_click=CreateJobState.submit,
                loading=CreateJobState.is_submitting,
                size="3",
            ),
            spacing="3",
        ),
        width="100%",
        spacing="4",
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
            rx.text("Stored job criteria", weight="medium", size="2"),
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
            _step_indicator(),
            rx.cond(CreateJobState.step == 1, _step_1(), _step_2()),
            _created_job_panel(),
        ),
    )
