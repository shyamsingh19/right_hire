"""Persistent sidebar nav + header — replaces `st.sidebar.radio` page switching."""

from __future__ import annotations

import reflex as rx

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
        border_radius="var(--radius-4)",
        width="100%",
        color=rx.cond(is_active, rx.color("violet", 12), rx.color("gray", 11)),
        background=rx.cond(is_active, rx.color("violet", 4), "transparent"),
        weight=rx.cond(is_active, "bold", "regular"),
        underline="none",
        _hover={"background": rx.color("violet", 3)},
    )


def _credits_block() -> rx.Component:
    """1 credit = 1 candidate evaluated. Top-ups are approved by a human out-of-band,
    so this only asks — it never charges (see app/api/billing.py)."""
    out_of_credits = AppState.credits <= 0
    return rx.vstack(
        rx.hstack(
            rx.icon("coins", size=14, color=rx.color("amber", 9)),
            rx.text("Credits", size="1", color=rx.color("gray", 11)),
            rx.spacer(),
            rx.badge(
                AppState.credits.to_string(),
                variant="soft",
                color_scheme=rx.cond(out_of_credits, "red", "grass"),
                size="1",
            ),
            align="center",
            width="100%",
        ),
        rx.cond(
            out_of_credits,
            rx.text(
                "Out of credits — uploads will be rejected.",
                size="1",
                color=rx.color("red", 9),
            ),
        ),
        rx.button(
            "Request more",
            on_click=AppState.request_credits,
            size="1",
            variant="soft",
            width="100%",
        ),
        rx.cond(
            AppState.credits_message != "",
            rx.text(AppState.credits_message, size="1", color=rx.color("gray", 11)),
        ),
        rx.cond(
            AppState.payment_link != "",
            rx.link(
                "Open payment page →",
                href=AppState.payment_link,
                is_external=True,
                size="1",
                color=rx.color("violet", 10),
            ),
        ),
        spacing="2",
        width="100%",
    )


def _account_widget() -> rx.Component:
    """Every API call needs an X-API-Key — this is the only place a user gets or pastes one."""
    signed_in = rx.vstack(
        rx.hstack(
            rx.icon("key-round", size=14, color=rx.color("grass", 9)),
            rx.text("Connected", size="1", color=rx.color("gray", 11)),
            rx.spacer(),
            rx.link("Log out", on_click=AppState.log_out, size="1", color=rx.color("gray", 9)),
            align="center",
            width="100%",
        ),
        _credits_block(),
        rx.divider(),
        rx.tooltip(
            rx.button(
                rx.icon("refresh-cw", size=12),
                "Rotate key",
                on_click=AppState.rotate_key,
                size="1",
                variant="ghost",
                width="100%",
            ),
            content="Issues a new key and saves it here. The current key stops working immediately.",
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
        rx.button(
            "Sign up",
            on_click=AppState.signup,
            loading=AppState.is_authenticating,
            size="1",
            width="100%",
        ),
        rx.cond(
            AppState.auth_error != "",
            rx.text(AppState.auth_error, size="1", color=rx.color("red", 9)),
        ),
        rx.divider(),
        rx.text("...or paste an existing key", size="1", color=rx.color("gray", 9)),
        rx.input(
            placeholder="rh_...",
            value=AppState.key_input,
            on_change=AppState.set_key_input,
            size="1",
        ),
        rx.button(
            "Use key", on_click=AppState.use_existing_key, size="1", width="100%", variant="soft"
        ),
        spacing="2",
        width="100%",
    )
    return rx.box(
        rx.cond(AppState.is_authenticated, signed_in, signed_out),
        padding="0.75em",
        border_radius="var(--radius-4)",
        background=rx.color("gray", 2),
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
        rx.color_mode.button(),
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
