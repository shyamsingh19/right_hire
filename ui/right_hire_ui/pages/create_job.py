from __future__ import annotations

import reflex as rx

from right_hire_ui.components.buttons import button
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.create_job_state import CreateJobState


def _threshold_slider(label: str, value, on_change) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="3", weight="medium"),
            rx.spacer(),
            rx.badge(f"{value:.2f}", variant="soft", color_scheme="violet"),
            width="100%",
        ),
        rx.slider(
            value=[value],
            on_change=on_change,
            min=0,
            max=1,
            step=0.05,
            width="100%",
            aria_label=label,
        ),
        width="100%",
        spacing="1",
    )


def _weight_slider(label: str, value, on_change) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="2", weight="medium"),
            rx.spacer(),
            rx.badge(f"{value * 100:.2f}%", variant="soft", color_scheme="blue"),
            width="100%",
        ),
        rx.slider(
            value=[value],
            on_change=on_change,
            min=0,
            max=1,
            step=0.05,
            width="100%",
            aria_label=label,
        ),
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
        button(
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


def _must_have_tag(must_have: str, removable: bool = True) -> rx.Component:
    if not removable:
        return rx.badge(must_have, variant="outline", color_scheme="gray", size="2")
    return rx.badge(
        rx.hstack(
            rx.text(must_have),
            rx.icon(
                "x",
                size=12,
                cursor="pointer",
                on_click=CreateJobState.remove_must_have(must_have),
            ),
            spacing="1",
            align="center",
        ),
        variant="outline",
        color_scheme="gray",
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
            button("Add", tier="secondary", on_click=CreateJobState.add_required_skill, size="2"),
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
            rx.hstack(
                rx.callout(
                    CreateJobState.weight_error,
                    icon="triangle-alert",
                    color_scheme="amber",
                    size="1",
                ),
                button(
                    "Auto-normalize",
                    tier="tertiary",
                    on_click=CreateJobState.normalize_weights,
                    size="1",
                ),
                align="center",
                spacing="2",
                width="100%",
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
        rx.vstack(
            rx.text("Must-haves", weight="medium", size="2"),
            rx.flex(
                rx.foreach(CreateJobState.must_haves, lambda m: _must_have_tag(m)),
                wrap="wrap",
                gap="2",
            ),
            rx.hstack(
                rx.input(
                    placeholder="Add a must-have...",
                    value=CreateJobState.new_must_have_input,
                    on_change=CreateJobState.set_new_must_have_input,
                    on_key_down=lambda k: rx.cond(
                        k == "Enter", CreateJobState.add_must_have(), rx.console_log("")
                    ),
                    size="2",
                    width="100%",
                ),
                button("Add", tier="secondary", on_click=CreateJobState.add_must_have, size="2"),
                width="100%",
                spacing="2",
            ),
            spacing="2",
            width="100%",
            align="start",
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
            button(
                rx.icon("arrow-left", size=14),
                "Back",
                tier="ghost",
                on_click=CreateJobState.back_to_step_1,
                size="3",
            ),
            button(
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


def _summary_item(label: str, value) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="1", color=rx.color("gray", 10), weight="medium"),
        rx.text(value, size="3", weight="medium"),
        spacing="1",
        align="start",
    )


def _created_job_panel() -> rx.Component:
    """Shown instead of the form once a job is live — the next step is uploading
    candidates for it, so that CTA is the only primary button here."""
    return rx.cond(
        CreateJobState.created_job_id != "",
        rx.vstack(
            rx.callout(
                f"“{CreateJobState.created_job_title}” is live and ready for candidates.",
                icon="check",
                color_scheme="green",
            ),
            rx.box(
                rx.grid(
                    _summary_item("Minimum experience", f"{CreateJobState.min_yoe:.1f} yrs"),
                    _summary_item(
                        "Location",
                        rx.cond(CreateJobState.location != "", CreateJobState.location, "Any"),
                    ),
                    _summary_item("Fit threshold", f"{CreateJobState.fit_threshold:.2f}"),
                    _summary_item("Maybe threshold", f"{CreateJobState.maybe_threshold:.2f}"),
                    columns="2",
                    spacing="4",
                    width="100%",
                ),
                rx.cond(
                    CreateJobState.required_skills.length() > 0,
                    rx.vstack(
                        rx.text(
                            "Required skills",
                            size="1",
                            color=rx.color("gray", 10),
                            weight="medium",
                        ),
                        rx.flex(
                            rx.foreach(
                                CreateJobState.required_skills,
                                lambda s: _skill_tag(s, removable=False),
                            ),
                            wrap="wrap",
                            gap="2",
                        ),
                        spacing="2",
                        align="start",
                        width="100%",
                        margin_top="3",
                    ),
                ),
                rx.cond(
                    CreateJobState.must_haves.length() > 0,
                    rx.vstack(
                        rx.text(
                            "Must-haves",
                            size="1",
                            color=rx.color("gray", 10),
                            weight="medium",
                        ),
                        rx.flex(
                            rx.foreach(
                                CreateJobState.must_haves,
                                lambda m: _must_have_tag(m, removable=False),
                            ),
                            wrap="wrap",
                            gap="2",
                        ),
                        spacing="2",
                        align="start",
                        width="100%",
                        margin_top="3",
                    ),
                ),
                padding="4",
                border=f"1px solid {rx.color('gray', 5)}",
                border_radius="var(--radius-3)",
                width="100%",
            ),
            rx.hstack(
                rx.link(
                    button(
                        "Upload candidates for " + CreateJobState.created_job_title + " →",
                        size="3",
                    ),
                    href="/upload?job=" + CreateJobState.created_job_id,
                ),
                button(
                    "Create another job",
                    tier="tertiary",
                    on_click=CreateJobState.create_another,
                    size="3",
                ),
                spacing="3",
                align="center",
                wrap="wrap",
            ),
            width="100%",
            spacing="3",
        ),
    )


def create_job_page() -> rx.Component:
    return page_shell(
        section_card(
            "Create a New Job",
            rx.cond(
                CreateJobState.created_job_id != "",
                _created_job_panel(),
                rx.fragment(
                    _step_indicator(),
                    rx.cond(CreateJobState.step == 1, _step_1(), _step_2()),
                ),
            ),
        ),
    )
