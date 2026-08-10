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


def signal_chip(label: rx.Var[str] | str, kind: rx.Var[str] | str) -> rx.Component:
    """Small evidence tag for the candidate inspector — e.g. `signal_chip("Skills", "match")`
    renders a green "✓ Skills" pill. `kind` is one of "match" | "warning" | "fail"."""
    icon = rx.match(kind, ("match", "check"), ("warning", "triangle-alert"), ("fail", "x"), "info")
    color = rx.match(kind, ("match", "green"), ("warning", "amber"), ("fail", "red"), "gray")
    return rx.badge(
        rx.icon(icon, size=11),
        label,
        color_scheme=color,
        variant="soft",
        size="1",
        radius="full",
    )
