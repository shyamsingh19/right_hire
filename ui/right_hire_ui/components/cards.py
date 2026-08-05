from __future__ import annotations

import reflex as rx


def glass_panel(*children, **props) -> rx.Component:
    class_name = "glass-panel " + props.pop("class_name", "")
    return rx.box(*children, class_name=class_name.strip(), padding="1.75em", **props)


def section_card(title: str, *children, **props) -> rx.Component:
    return glass_panel(
        rx.vstack(
            rx.heading(title, size="5", weight="bold"),
            *children,
            spacing="4",
            width="100%",
        ),
        width="100%",
        **props,
    )
