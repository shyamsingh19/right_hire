"""Persistent sidebar nav + header — replaces `st.sidebar.radio` page switching."""

from __future__ import annotations

import reflex as rx

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
