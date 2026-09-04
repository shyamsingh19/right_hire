from __future__ import annotations

import reflex as rx

from right_hire_ui.components.buttons import button
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.create_job_state import CRITERION_LEVELS, CreateJobState


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


def _step_dot(number: int, label: str) -> rx.Component:
    """Filled = current, filled-with-check = done, outlined = still ahead."""
    is_current = CreateJobState.step == number
    is_done = CreateJobState.step > number
    return rx.vstack(
        rx.center(
            rx.cond(
                is_done,
                rx.icon("check", size=14, color=rx.color("violet", 1)),
                rx.text(
                    str(number),
                    size="2",
                    weight="bold",
                    color=rx.cond(is_current, rx.color("violet", 1), rx.color("gray", 10)),
                ),
            ),
            width="28px",
            height="28px",
            border_radius="50%",
            border="1px solid",
            border_color=rx.cond(is_current | is_done, rx.color("violet", 9), rx.color("gray", 7)),
            background=rx.cond(is_current | is_done, rx.color("violet", 9), "transparent"),
            flex_shrink="0",
        ),
        rx.text(
            label,
            size="2",
            weight=rx.cond(is_current, "bold", "regular"),
            color=rx.cond(is_current, rx.color("violet", 11), rx.color("gray", 10)),
            white_space="nowrap",
        ),
        spacing="2",
        align="center",
    )


def _step_connector() -> rx.Component:
    """Accent once step 1 is behind us, border-colored while it's still ahead."""
    return rx.box(
        height="1px",
        flex="1",
        min_width="2em",
        margin_top="14px",
        background=rx.cond(CreateJobState.step > 1, rx.color("violet", 9), rx.color("gray", 7)),
    )


def _step_indicator() -> rx.Component:
    return rx.hstack(
        rx.spacer(),
        _step_dot(1, "Job Description"),
        _step_connector(),
        _step_dot(2, "Review & Calibrate"),
        rx.spacer(),
        width="100%",
        align="start",
        spacing="3",
    )


# ── Step 1 ────────────────────────────────────────────────────────────────────


def _manual_entry_link(label: str = "Or enter criteria manually →") -> rx.Component:
    """Escape hatch for a role with no JD to paste — goes straight to step 2 with one
    blank criterion row."""
    return button(
        label,
        tier="tertiary",
        on_click=CreateJobState.start_manual,
        size="2",
        padding_x="0",
    )


def _step_1() -> rx.Component:
    parsing = CreateJobState.is_parsing
    return rx.vstack(
        rx.text(
            "Paste a job description — the AI extracts structured screening criteria "
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
                # read_only, not disabled: a disabled input greys the text out, and the
                # user should still be able to read what they typed while it parses.
                read_only=parsing,
                width="100%",
                size="3",
            ),
            width="100%",
            spacing="1",
        ),
        rx.vstack(
            rx.text("Job Description", size="2", weight="medium"),
            rx.box(
                rx.text_area(
                    placeholder="Paste the full job description here…",
                    value=CreateJobState.jd_raw,
                    on_change=CreateJobState.set_jd_raw,
                    read_only=parsing,
                    min_height="300px",
                    width="100%",
                ),
                rx.cond(
                    CreateJobState.jd_char_count != "",
                    rx.text(
                        CreateJobState.jd_char_count,
                        size="1",
                        color=rx.color("gray", 10),
                        position="absolute",
                        bottom="0.6em",
                        right="0.9em",
                        background="var(--rh-card)",
                        padding_x="0.35em",
                        pointer_events="none",
                    ),
                ),
                # .rh-parsing pulses the border while the LLM call is in flight and
                # falls back to a static accent border under prefers-reduced-motion.
                class_name=rx.cond(parsing, "rh-parsing", ""),
                position="relative",
                width="100%",
                border_radius="var(--radius-3)",
            ),
            width="100%",
            spacing="1",
        ),
        rx.cond(
            CreateJobState.error_message != "",
            rx.vstack(
                rx.hstack(
                    rx.icon("triangle-alert", size=14, color=rx.color("red", 10)),
                    rx.text(
                        CreateJobState.error_message,
                        size="2",
                        color=rx.color("red", 11),
                        role="alert",
                    ),
                    spacing="2",
                    align="center",
                ),
                _manual_entry_link("Enter criteria manually →"),
                spacing="1",
                align="start",
                width="100%",
            ),
        ),
        rx.vstack(
            button(
                rx.cond(parsing, rx.spinner(size="2"), rx.icon("sparkles", size=14)),
                rx.cond(parsing, "Parsing…", "Parse JD Criteria"),
                on_click=CreateJobState.parse_criteria,
                disabled=parsing,
                size="3",
                width="fit-content",
            ),
            _manual_entry_link(),
            spacing="1",
            align="start",
        ),
        width="100%",
        spacing="4",
    )


# ── Step 2 ────────────────────────────────────────────────────────────────────


def _skill_tag(skill: str, removable: bool = True) -> rx.Component:
    """Read-only chip for the post-create summary panel."""
    return rx.badge(skill, variant="outline", color_scheme="gray", size="2")


def _level_control(index: rx.Var, level: rx.Var) -> rx.Component:
    """Three-position importance picker. Segmented rather than a numeric slider —
    the pipeline only distinguishes three cases, so a 0-1 weight would invent
    precision it can't act on."""
    return rx.segmented_control.root(
        *[rx.segmented_control.item(label, value=value) for value, label in CRITERION_LEVELS],
        value=level,
        on_change=lambda v: CreateJobState.set_criterion_level(index, v),
        size="1",
    )


def _criterion_row(criterion: dict, index: rx.Var) -> rx.Component:
    return rx.hstack(
        rx.input(
            value=criterion["text"].to(str),
            on_change=lambda v: CreateJobState.set_criterion_text(index, v),
            placeholder="e.g. Python",
            size="2",
            flex="1",
            min_width="0",
        ),
        _level_control(index, criterion["level"].to(str)),
        rx.icon_button(
            rx.icon("x", size=14),
            on_click=CreateJobState.remove_criterion(index),
            variant="ghost",
            color_scheme="red",
            size="1",
            aria_label="Remove this criterion",
        ),
        width="100%",
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _criteria_editor() -> rx.Component:
    return rx.vstack(
        rx.text("Screening criteria", weight="medium", size="3"),
        rx.text(
            "Nice to have counts toward the skill-overlap score. Important is also shown "
            "to the LLM judge. Required additionally eliminates candidates who lack it.",
            size="1",
            color=rx.color("gray", 11),
        ),
        rx.cond(
            CreateJobState.criteria.length() > 0,
            rx.vstack(
                rx.foreach(CreateJobState.criteria, _criterion_row),
                spacing="2",
                width="100%",
            ),
            rx.text("No criteria yet — add one below.", size="2", color=rx.color("gray", 10)),
        ),
        button(
            rx.icon("plus", size=14),
            "Add criterion",
            tier="tertiary",
            on_click=CreateJobState.add_criterion,
            size="2",
            padding_x="0",
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
        _criteria_editor(),
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
            rx.tooltip(
                button(
                    "Confirm & Activate Job",
                    on_click=CreateJobState.submit,
                    loading=CreateJobState.is_submitting,
                    disabled=~CreateJobState.has_criteria,
                    size="3",
                ),
                content=rx.cond(
                    CreateJobState.has_criteria,
                    "Create the job and start screening",
                    "Add at least one criterion first",
                ),
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
                                lambda m: _skill_tag(m, removable=False),
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
