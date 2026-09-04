"""Persistent sidebar nav + page shell.

The sidebar footer is deliberately thin: identity, credit balance, a Settings
link. Credit top-ups, request history and key rotation live on /settings.
"""

from __future__ import annotations

import reflex as rx

from right_hire_ui.components.buttons import button
from right_hire_ui.states.app_state import AppState

NAV_ITEMS = [
    ("/", "Create Job", "file-plus"),
    ("/upload", "Upload Candidates", "upload"),
    ("/results", "Results", "list-checks"),
]


def _nav_link(route: str, label: str, icon: str) -> rx.Component:
    is_active = rx.State.router.page.path == route
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=16),
            rx.text(label, size="3"),
            spacing="2",
            align="center",
        ),
        href=route,
        class_name="nav-link",
        padding="0.6em 0.9em",
        border_radius="var(--radius-3)",
        width="100%",
        color=rx.cond(is_active, rx.color("violet", 11), rx.color("gray", 11)),
        background=rx.cond(is_active, rx.color("violet", 3), "transparent"),
        border_left_color=rx.cond(is_active, rx.color("violet", 9), "transparent"),
        weight=rx.cond(is_active, "medium", "regular"),
        underline="none",
        _hover={"background": rx.color("violet", 2)},
    )


def _credit_pill() -> rx.Component:
    """1 credit = 1 candidate evaluated. Red at zero, since uploads then fail."""
    out_of_credits = (AppState.credits == "0") | (AppState.credits == "")
    return rx.cond(
        AppState.is_loading_account,
        rx.spinner(size="1"),
        rx.badge(
            rx.icon("zap", size=11),
            AppState.credits,
            variant="soft",
            color_scheme=rx.cond(out_of_credits, "red", "violet"),
            size="1",
            radius="full",
            aria_label="Credits remaining: " + AppState.credits,
        ),
    )


def _account_widget() -> rx.Component:
    """Every API call needs an X-API-Key — this is the only place a user gets or pastes one."""
    signed_in = rx.vstack(
        rx.hstack(
            rx.avatar(
                fallback=AppState.user_initials,
                size="1",
                radius="full",
                color_scheme="violet",
                variant="solid",
            ),
            rx.text(
                rx.cond(AppState.user_email != "", AppState.user_email, "Connected"),
                size="1",
                color=rx.color("gray", 11),
                no_of_lines=1,
            ),
            rx.spacer(),
            _credit_pill(),
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.cond(
            (AppState.credits == "0") & ~AppState.is_loading_account,
            rx.text(
                "Out of credits — uploads will be rejected.",
                size="1",
                color=rx.color("red", 10),
                role="alert",
            ),
        ),
        rx.hstack(
            rx.link(
                rx.hstack(
                    rx.icon("settings", size=12),
                    rx.text("Settings", size="1"),
                    spacing="1",
                    align="center",
                ),
                href="/settings",
                color=rx.color("gray", 10),
                underline="none",
            ),
            rx.spacer(),
            rx.link("Log out", on_click=AppState.log_out, size="1", color=rx.color("gray", 10)),
            width="100%",
            align="center",
        ),
        spacing="2",
        width="100%",
    )
    signed_out = rx.vstack(
        rx.text("Get an API key to use Right Hire", size="1", color=rx.color("gray", 11)),
        rx.input(
            placeholder="you@company.com",
            value=AppState.signup_email,
            on_change=AppState.set_signup_email,
            size="1",
        ),
        button(
            "Sign up",
            on_click=AppState.signup,
            loading=AppState.is_authenticating,
            size="1",
            width="100%",
        ),
        rx.cond(
            AppState.auth_error != "",
            rx.text(AppState.auth_error, size="1", color=rx.color("red", 10)),
        ),
        rx.divider(),
        rx.text("...or paste an existing key", size="1", color=rx.color("gray", 10)),
        rx.input(
            placeholder="rh_...",
            value=AppState.key_input,
            on_change=AppState.set_key_input,
            size="1",
        ),
        button(
            "Use key", tier="secondary", on_click=AppState.use_existing_key, size="1", width="100%"
        ),
        spacing="2",
        width="100%",
    )
    return rx.box(
        rx.cond(AppState.is_authenticated, signed_in, signed_out),
        padding="0.75em",
        border_radius="var(--radius-3)",
        background="var(--rh-inset)",
        width="100%",
    )


def _sidebar() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon("target", size=22, color=rx.color("violet", 9)),
            rx.heading("Right Hire", size="5", weight="bold"),
            spacing="2",
            align="center",
            padding_bottom="1em",
        ),
        *[_nav_link(route, label, icon) for route, label, icon in NAV_ITEMS],
        rx.spacer(),
        _account_widget(),
        rx.color_mode.button(size="1"),
        class_name="rh-sidebar",
        spacing="2",
        width="240px",
        min_width="240px",
        height="100vh",
        padding="1.5em 1em",
        position="sticky",
        top="0",
        align_items="stretch",
    )


def page_shell(*children) -> rx.Component:
    return rx.hstack(
        _sidebar(),
        rx.box(
            rx.vstack(*children, spacing="5", width="100%", max_width="960px", margin="0 auto"),
            padding="2.5em 2em",
            width="100%",
        ),
        spacing="0",
        width="100%",
        align_items="flex-start",
    )
