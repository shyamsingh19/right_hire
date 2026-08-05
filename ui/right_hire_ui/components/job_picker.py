"""Shared job selector — replaces the old Streamlit `_job_selectbox()` helper
that was copy-pasted across the Upload and Results pages."""

from __future__ import annotations

import reflex as rx


def job_picker(
    options: rx.Var[list[tuple[str, str]]],
    value: rx.Var[str],
    on_change,
    placeholder: str = "Select a job...",
) -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder=placeholder, width="100%"),
        rx.select.content(
            rx.foreach(
                options,
                lambda opt: rx.select.item(opt[1], value=opt[0]),
            )
        ),
        value=value,
        on_change=on_change,
        width="100%",
    )
