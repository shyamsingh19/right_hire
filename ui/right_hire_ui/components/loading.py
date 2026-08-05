from __future__ import annotations

import reflex as rx


def loading_spinner(is_loading: rx.Var[bool], *children) -> rx.Component:
    return rx.cond(
        is_loading,
        rx.center(rx.spinner(size="3"), padding="2em"),
        rx.fragment(*children),
    )
