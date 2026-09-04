from __future__ import annotations

import reflex as rx


def empty_state(
    heading: str,
    body: str = "",
    icon: str = "inbox",
    cta_label: str = "",
    cta_href: str = "",
) -> rx.Component:
    """Centered dead-end filler. Give it a `cta_label`/`cta_href` whenever there is
    a next step the user can actually take — an empty screen with no way forward is
    where new users churn."""
    return rx.center(
        rx.vstack(
            rx.icon(icon, size=32, color=rx.color("gray", 9)),
            rx.heading(heading, size="4", weight="medium"),
            rx.cond(
                body != "",
                rx.text(
                    body,
                    color=rx.color("gray", 11),
                    size="2",
                    text_align="center",
                    max_width="26em",
                ),
            ),
            rx.cond(
                cta_label != "",
                rx.link(
                    rx.button(cta_label, variant="solid", color_scheme="violet", size="3"),
                    href=cta_href,
                ),
            ),
            spacing="3",
            align="center",
        ),
        padding="3em 1em",
        width="100%",
    )
