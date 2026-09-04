"""Account settings — credit top-ups, request history and API-key rotation.

These used to live in the sidebar footer; they are rare, deliberate actions and
don't belong on every screen.
"""

from __future__ import annotations

import reflex as rx

from right_hire_ui.components.buttons import button
from right_hire_ui.components.cards import section_card
from right_hire_ui.components.empty_state import empty_state
from right_hire_ui.components.layout import page_shell
from right_hire_ui.states.app_state import AppState


def _credit_request_row(item: dict) -> rx.Component:
    status = item["status"].to(str)
    scheme = rx.match(status, ("granted", "green"), ("pending", "amber"), "gray")
    return rx.hstack(
        rx.text(item["created_at"].to(str), size="2", color=rx.color("gray", 11)),
        rx.spacer(),
        rx.badge(status, color_scheme=scheme, variant="soft", size="1"),
        width="100%",
        align="center",
        class_name="rh-row",
        padding="0.5em 0.75em",
        border_radius="var(--radius-2)",
    )


def _credits_section() -> rx.Component:
    """Top-ups are approved by a human out-of-band, so this only asks — it never
    charges (see app/api/billing.py)."""
    return rx.vstack(
        rx.hstack(
            rx.text("Credits", size="3", weight="medium"),
            rx.spacer(),
            rx.badge(AppState.credits, variant="soft", color_scheme="violet", size="2"),
            width="100%",
            align="center",
        ),
        rx.text(
            "1 credit evaluates 1 candidate. Top-ups are approved manually.",
            size="2",
            color=rx.color("gray", 11),
        ),
        rx.cond(
            AppState.has_pending_credit_request,
            rx.callout(
                "A credit request is pending operator approval.",
                icon="clock",
                color_scheme="amber",
                size="1",
            ),
        ),
        button(
            "Request more credits",
            on_click=AppState.request_credits,
            loading=AppState.is_requesting_credits,
            size="2",
            width="fit-content",
        ),
        rx.cond(
            AppState.credits_message != "",
            rx.text(AppState.credits_message, size="2", color=rx.color("gray", 11)),
        ),
        rx.cond(
            AppState.payment_link != "",
            rx.link(
                "Open payment page →",
                href=AppState.payment_link,
                is_external=True,
                size="2",
                color=rx.color("violet", 11),
            ),
        ),
        rx.cond(
            AppState.support_contact != "",
            rx.text(
                "Or reach out: " + AppState.support_contact,
                size="2",
                color=rx.color("gray", 11),
            ),
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def _history_section() -> rx.Component:
    return rx.vstack(
        rx.text("Request history", size="3", weight="medium"),
        rx.cond(
            AppState.credit_requests.length() > 0,
            rx.vstack(
                rx.foreach(AppState.credit_requests, _credit_request_row),
                spacing="1",
                width="100%",
            ),
            empty_state(heading="No credit requests yet", icon="history"),
        ),
        spacing="2",
        width="100%",
        align="start",
    )


def _api_key_section() -> rx.Component:
    return rx.vstack(
        rx.text("API key", size="3", weight="medium"),
        rx.text(
            "Rotating issues a new key and saves it in this browser. "
            "The current key stops working immediately.",
            size="2",
            color=rx.color("gray", 11),
        ),
        button(
            rx.icon("refresh-cw", size=14),
            "Rotate key",
            tier="secondary",
            on_click=AppState.rotate_key,
            loading=AppState.is_rotating_key,
            size="2",
            width="fit-content",
        ),
        spacing="3",
        width="100%",
        align="start",
    )


def settings_page() -> rx.Component:
    return page_shell(
        section_card(
            "Settings",
            rx.cond(
                AppState.is_authenticated,
                rx.vstack(
                    rx.hstack(
                        rx.avatar(
                            fallback=AppState.user_initials,
                            size="3",
                            radius="full",
                            color_scheme="violet",
                            variant="solid",
                        ),
                        rx.vstack(
                            rx.text(AppState.user_email, size="3", weight="medium"),
                            rx.text("Signed in", size="1", color=rx.color("gray", 11)),
                            spacing="0",
                            align="start",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    rx.divider(),
                    _credits_section(),
                    rx.divider(),
                    _history_section(),
                    rx.divider(),
                    _api_key_section(),
                    spacing="4",
                    width="100%",
                    align="start",
                ),
                empty_state(
                    heading="Sign in first",
                    body="Get an API key from the sidebar to manage your account.",
                    icon="key-round",
                ),
            ),
        ),
    )
