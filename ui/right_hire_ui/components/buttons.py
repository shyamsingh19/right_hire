"""Button tiers — one primary (filled) per screen, everything else steps down.

Maps the design tiers onto Radix variant/color_scheme pairs so pages never pick
those two props by hand.
"""

from __future__ import annotations

import reflex as rx

TIERS = {
    "primary": {"variant": "solid", "color_scheme": "violet"},
    "secondary": {"variant": "outline", "color_scheme": "violet"},
    "tertiary": {"variant": "ghost", "color_scheme": "violet"},
    "danger": {"variant": "ghost", "color_scheme": "red"},
    "ghost": {"variant": "ghost", "color_scheme": "gray"},
}


def button(*children, tier: str = "primary", **props) -> rx.Component:
    return rx.button(*children, **TIERS[tier], **props)
