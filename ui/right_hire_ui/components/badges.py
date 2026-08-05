"""Colored pill badges — replaces the old Streamlit emoji dict (_BADGE)."""

from __future__ import annotations

import reflex as rx


def verdict_pill(verdict: rx.Var[str] | str) -> rx.Component:
    color = rx.match(
        verdict,
        ("Fit", "green"),
        ("Maybe", "amber"),
        ("Reject", "red"),
        "gray",
    )
    return rx.badge(verdict, color_scheme=color, variant="soft", size="2", radius="full")


def status_badge(status: rx.Var[str] | str) -> rx.Component:
    color = rx.match(
        status,
        ("pending", "gray"),
        ("processing", "blue"),
        ("done", "green"),
        ("failed", "red"),
        "gray",
    )
    return rx.badge(status, color_scheme=color, variant="soft", size="2", radius="full")
