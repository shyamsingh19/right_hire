from __future__ import annotations

import reflex as rx


def empty_state(message: str, icon: str = "inbox") -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon(icon, size=32, color=rx.color("gray", 9)),
            rx.text(message, color=rx.color("gray", 11)),
            spacing="2",
            align="center",
        ),
        padding="2.5em",
        width="100%",
    )
