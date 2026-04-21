"""
Central UI theme for Legends Overlay.

This file contains ONLY design tokens:
- colors
- base backgrounds
- semantic colors

NO Qt stylesheet strings here.
"""


# ============================================================
# CORE COLORS
# ============================================================

GOLD = "#d4c5a1"

TEXT = "#ddd"
TEXT_DIM = "#909090"
TEXT_SUB = "#8f8f8f"


# ============================================================
# BACKGROUNDS
# ============================================================

BG_MAIN = "rgb(28, 28, 28)"
BG_DARK = "rgb(20, 20, 20)"
BG_CARD = "rgba(50, 50, 50, 0.6)"


# ============================================================
# SEMANTIC COLORS
# ============================================================

COLOR_SUCCESS = "#33CC66"
COLOR_WARNING = "#FFD966"
COLOR_INFO = "#66CCFF"
COLOR_ACCENT = "#FFA500"
COLOR_DISABLED = "#8c8c8c"


# ============================================================
# STATUS COLORS
# ============================================================

STATUS_COLORS = {
    "default": GOLD,
    "waiting": COLOR_INFO,
    "registration": COLOR_ACCENT,
    "active": COLOR_SUCCESS,
    "upcoming_soon": COLOR_WARNING,
    "unique_cd": COLOR_INFO,
    "unique_spawn": COLOR_WARNING,
    "unknown": COLOR_DISABLED,
}