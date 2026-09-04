"""App-wide theme: light-by-default Radix theme + token CSS (see assets/styles.css)."""

from __future__ import annotations

import reflex as rx

GOOGLE_FONT_URL = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
STYLESHEETS = [GOOGLE_FONT_URL, "/styles.css"]


def get_theme() -> rx.Component:
    return rx.theme(
        appearance="light",
        has_background=False,
        accent_color="violet",
        gray_color="sand",
        panel_background="solid",
        radius="large",
        scaling="100%",
    )
