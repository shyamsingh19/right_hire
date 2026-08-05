"""App-wide theme: dark-mode-first Radix theme + custom glassmorphism CSS."""

from __future__ import annotations

import reflex as rx

GOOGLE_FONT_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
STYLESHEETS = [GOOGLE_FONT_URL, "/styles.css"]


def get_theme() -> rx.Component:
    return rx.theme(
        appearance="dark",
        has_background=True,
        accent_color="violet",
        gray_color="slate",
        panel_background="translucent",
        radius="large",
        scaling="100%",
    )
