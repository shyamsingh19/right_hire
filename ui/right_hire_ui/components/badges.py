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
    return rx.badge(
        verdict,
        color_scheme=color,
        variant="soft",
        size="2",
        radius="full",
        aria_label="Verdict: " + verdict,
    )


def status_badge(status: rx.Var[str] | str) -> rx.Component:
    """Processing state for a candidate with no evaluation yet. Labels are written
    out rather than echoing the raw DB status, so the queue reads consistently
    alongside the verdict pills."""
    color = rx.match(
        status,
        ("pending", "gray"),
        ("processing", "blue"),
        ("done", "green"),
        ("failed", "red"),
        "gray",
    )
    label = rx.match(
        status,
        ("pending", "Queued"),
        ("processing", "Processing…"),
        ("done", "Done"),
        ("failed", "Failed"),
        status,
    )
    return rx.badge(
        label,
        color_scheme=color,
        variant="soft",
        size="2",
        radius="full",
        aria_label="Status: " + status,
    )


def confidence_badge(confidence: rx.Var[str] | str) -> rx.Component:
    """How close a verdict is to the nearest Fit/Maybe cutoff — "Low" flags a score a
    recruiter should sanity-check manually rather than act on directly."""
    color = rx.match(
        confidence,
        ("High", "green"),
        ("Medium", "amber"),
        ("Low", "red"),
        "gray",
    )
    return rx.badge(
        confidence + " confidence",
        color_scheme=color,
        variant="outline",
        size="1",
        aria_label=confidence + " confidence verdict",
    )


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
