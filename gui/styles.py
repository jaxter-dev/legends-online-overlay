"""
Central Qt styles for Legends Overlay UI.

This file contains Qt stylesheet strings only.

Pravila:
- theme.py = samo tokens
- styles.py = vsi QSS / stylesheet stringi
- ohranjamo ista imena konstant, da ne razbijemo obstoječih importov
"""

from gui.theme import (
    BG_CARD,
    BG_DARK,
    BG_MAIN,
    COLOR_ACCENT,
    COLOR_DISABLED,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    GOLD,
    TEXT,
    TEXT_DIM,
    TEXT_SUB,
)


# ============================================================
# ROOT / BASE
# ============================================================

ROOT_STYLE = f"""
QWidget {{
    border: none;
}}

QLabel {{
    border: none;
    background: transparent;
    color: {TEXT};
}}

QPushButton {{
    border: none;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
"""


# ============================================================
# SHARED SECTIONS / CARDS
# ============================================================

SECTION_STYLE = f"""
QWidget#sectionCard {{
    background: {BG_CARD};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
}}
"""

CARD_STYLE = f"""
QFrame#itemCard {{
    background: {BG_CARD};
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
}}
"""


# ============================================================
# TEXT
# ============================================================

SECTION_TITLE_STYLE = f"""
color: {GOLD};
font-weight: bold;
font-size: 10px;
padding-bottom: 2px;
border: none;
background: transparent;
"""

TITLE_STYLE = f"""
color: {GOLD};
font-weight: bold;
font-size: 10px;
background: transparent;
border: none;
padding: 0;
"""

SUBTITLE_STYLE = f"""
color: {TEXT_SUB};
font-size: 9px;
background: transparent;
border: none;
padding: 0;
"""

INFO_STYLE = f"""
color: {TEXT_DIM};
font-size: 9px;
background: transparent;
border: none;
"""

ROW_LABEL_STYLE = """
color: #c8c8c8;
font-size: 9px;
background: transparent;
border: none;
padding: 0;
"""

VERSION_LABEL_STYLE = """
color: #8c8c8c;
font-size: 9px;
border: none;
"""

WINDOW_TITLE_TEXT_STYLE = f"""
color: {GOLD};
background: transparent;
border: none;
"""


# ============================================================
# OVERLAY-SPECIFIC STYLES
# ============================================================

PANEL_STYLE = f"""
QFrame#overlayPanel {{
    background-color: rgba(40, 40, 40, 180);
    border: 1px solid rgba(212, 197, 161, 120);
    border-radius: 8px;
}}
"""

ROW_BASE_STYLE = """
background: transparent;
"""

ROW_TEXT_STYLE = """
color: {color};
background: transparent;
"""

HEADER_BUTTON_STYLE = """
QPushButton {
    background: transparent;
    border: none;
}
QPushButton:hover {
    background: rgba(212, 197, 161, 40);
    border-radius: 4px;
}
"""

GHOST_BUTTON_STYLE = """
QPushButton {
    background: transparent;
    border: none;
}
"""

UPDATE_BANNER_STYLE = """
QPushButton {
    background: rgba(241, 219, 132, 215);
    color: #3a2d00;
    border: 1px solid rgba(164, 131, 52, 220);
    border-radius: 5px;
    font-size: 10px;
    font-weight: bold;
}
QPushButton:hover {
    background: rgba(247, 226, 150, 225);
}
"""


# ============================================================
# TOGGLES / BUTTON STATES
# ============================================================

TOGGLE_ON_STYLE = """
QPushButton {
    background: #4CAF50;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 9px;
}
QPushButton:hover {
    background: #45a049;
}
"""

TOGGLE_OFF_STYLE = """
QPushButton {
    background: rgba(60,60,60,0.75);
    color: #a0a0a0;
    border: none;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 9px;
}
QPushButton:hover {
    background: rgba(80,80,80,0.9);
    color: #d0d0d0;
}
"""

STEP_BUTTON_STYLE = f"""
QPushButton {{
    background: rgba(60,60,60,0.6);
    color: {GOLD};
    border-radius: 4px;
}}
QPushButton:hover {{
    background: rgba(90,90,90,0.8);
}}
"""


# ============================================================
# INPUTS / CONTROLS
# ============================================================

COMBO_STYLE = f"""
QComboBox {{
    background: rgba(35,35,35,0.8);
    border: none;
    border-radius: 4px;
    padding: 4px;
    color: {TEXT};
}}
"""

SEARCH_INPUT_STYLE = f"""
QLineEdit {{
    background: rgba(35,35,35,0.85);
    color: {TEXT};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: rgba(212, 197, 161, 0.28);
}}
QLineEdit:focus {{
    border: 1px solid rgba(212, 197, 161, 0.25);
}}
"""

SEARCH_HINT_STYLE = f"""
color: {TEXT_SUB};
font-size: 9px;
background: transparent;
border: none;
"""

VALUE_LABEL_STYLE = f"""
background: rgba(30,30,30,0.8);
color: {GOLD};
font-weight: bold;
border-radius: 4px;
padding: 2px;
"""


# ============================================================
# SLIDERS / SCROLLBARS
# ============================================================

SLIDER_STYLE = f"""
QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(120,120,120,0.3);
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {GOLD};
    width: 10px;
    margin: -4px 0;
    border-radius: 5px;
}}
"""

SCROLLBAR_STYLE = """
QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: rgba(255,255,255,0.03);
    width: 8px;
    margin: 2px 0 2px 0;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(212, 197, 161, 0.32);
    min-height: 26px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(212, 197, 161, 0.48);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    border: none;
    background: transparent;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


# ============================================================
# WINDOW CHROME
# ============================================================

WINDOW_TITLEBAR_STYLE = f"""
background: {BG_MAIN};
border-bottom: 1px solid #5a5a5a;
"""

WINDOW_FOOTER_STYLE = f"""
background: {BG_MAIN};
border: none;
"""

WINDOW_CLOSE_BUTTON_STYLE = """
QPushButton {
    background: transparent;
    color: #888;
    border: none;
    font-size: 13px;
}
QPushButton:hover {
    background: rgba(220,50,50,0.30);
    color: white;
    border-radius: 4px;
}
"""

DARK_SECTION_STYLE = f"""
background: {BG_DARK};
border-bottom: 1px solid rgba(255,255,255,0.08);
"""

FOOTER_DARK_STYLE = f"""
background: {BG_DARK};
border-top: 1px solid rgba(255,255,255,0.08);
"""


# ============================================================
# CALENDAR WINDOW
# ============================================================

CALENDAR_TRANSPARENT_STYLE = """
background: transparent;
border: none;
"""

CALENDAR_WINDOW_ROOT_STYLE = f"""
QWidget {{
    background: {BG_MAIN};
    color: {GOLD};
    border: none;
}}

QLabel {{
    background: transparent;
    border: none;
    color: {TEXT};
}}

QPushButton {{
    border: none;
}}
"""

CALENDAR_DAY_HEADER_STYLE = f"""
color: {GOLD};
font-weight: bold;
font-size: 12px;
background: transparent;
border: none;
"""

CALENDAR_DAY_HEADER_TODAY_STYLE = f"""
color: {COLOR_SUCCESS};
font-weight: bold;
font-size: 12px;
background: rgba(255,255,255,0.04);
border: none;
"""

CALENDAR_DAY_UNDERLINE_STYLE = """
background: rgba(212,197,161,0.45);
border: none;
"""

CALENDAR_DAY_UNDERLINE_TODAY_STYLE = f"""
background: {COLOR_SUCCESS};
border: none;
"""

CALENDAR_DAY_COLUMN_NORMAL_STYLE = """
background-color: transparent;
border: none;
"""

CALENDAR_DAY_COLUMN_TODAY_STYLE = """
background-color: rgba(60, 60, 60, 0.4);
border: none;
"""

CALENDAR_EVENT_BUTTON_NORMAL_STYLE = f"""
QPushButton {{
    text-align: left;
    padding: 2px 6px;
    border: none;
    color: {GOLD};
    font-weight: normal;
    background: transparent;
}}
QPushButton:hover {{
    background: rgba(100,100,100,0.18);
    border-radius: 3px;
}}
"""

CALENDAR_EVENT_BUTTON_PAST_STYLE = """
QPushButton {
    text-align: left;
    padding: 2px 6px;
    border: none;
    color: #7d7d7d;
    font-weight: normal;
    background: transparent;
}
QPushButton:hover {
    background: rgba(120,120,120,0.16);
    border-radius: 3px;
}
"""

CALENDAR_EVENT_BUTTON_TODAY_STYLE = f"""
QPushButton {{
    text-align: left;
    padding: 2px 6px;
    border: none;
    color: {COLOR_SUCCESS};
    font-weight: normal;
    background: transparent;
}}
QPushButton:hover {{
    background: rgba(76,175,80,0.15);
    border-radius: 3px;
    color: #EFBF04;
}}
"""

CALENDAR_POPUP_STYLE = """
QFrame#eventPopupCard {
    background-color: #2c2c2c;
    color: #d4c5a1;
    border: none;
    border-radius: 8px;
}
QLabel {
    background: transparent;
    border: none;
}
"""

CALENDAR_POPUP_TITLE_STYLE = """
color: #EFBF04;
background: transparent;
border: none;
font-size: 16px;
font-weight: bold;
"""

CALENDAR_POPUP_CLOSE_BUTTON_STYLE = """
QPushButton {
    background: transparent;
    color: #888;
    border: none;
    font-size: 13px;
    border-radius: 4px;
}
QPushButton:hover {
    background: rgba(255,255,255,0.08);
    color: white;
}
"""

CALENDAR_POPUP_INFO_FRAME_STYLE = """
QFrame {
    background-color: rgba(60, 60, 60, 0.4);
    border: none;
    border-radius: 8px;
}
"""

CALENDAR_POPUP_BODY_FRAME_STYLE = """
QFrame {
    background-color: rgba(60, 60, 60, 0.4);
    border: none;
    border-radius: 8px;
}
"""

CALENDAR_POPUP_INFO_TEXT_STYLE = f"""
color: {GOLD};
background: transparent;
border: none;
"""

CALENDAR_POPUP_INFO_SUBTLE_STYLE = """
color: #a6a6a6;
background: transparent;
border: none;
"""

CALENDAR_POPUP_INFO_WARNING_STYLE = f"""
color: {COLOR_ACCENT};
background: transparent;
border: none;
"""

CALENDAR_POPUP_SECTION_TITLE_STYLE = f"""
color: {GOLD};
background: transparent;
border: none;
padding: 0 0 2px 0;
"""

CALENDAR_POPUP_DESC_STYLE = f"""
color: {GOLD};
background: transparent;
border: none;
"""

CALENDAR_POPUP_REWARD_STYLE = """
color: #00FF00;
background: transparent;
border: none;
"""

CALENDAR_POPUP_REQUIREMENT_STYLE = """
color: #FF4500;
background: transparent;
border: none;
"""

CALENDAR_POPUP_QUEST_STYLE = """
color: #00CCFF;
background: transparent;
border: none;
"""


# ============================================================
# UNIQUE MANAGER / UNIQUE DIALOGS
# ============================================================

UNIQUE_WINDOW_STYLE = f"""
QWidget {{
    background: {BG_MAIN};
    color: {TEXT};
    border: none;
}}

QLabel {{
    background: transparent;
    border: none;
    color: {TEXT};
}}
"""

UNIQUE_DIALOG_STYLE = f"""
QDialog {{
    background: {BG_MAIN};
    color: {TEXT};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
}}

QDialog QLabel {{
    background: transparent;
    border: none;
    color: {TEXT};
}}

QDialogButtonBox QPushButton {{
    background: rgba(60,60,60,0.75);
    color: {TEXT};
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 9px;
}}

QDialogButtonBox QPushButton:hover {{
    background: rgba(80,80,80,0.9);
}}
"""

UNIQUE_ACTION_BUTTON_STYLE = f"""
QPushButton {{
    background: rgba(60,60,60,0.75);
    color: {GOLD};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 9px;
}}
QPushButton:hover {{
    background: rgba(80,80,80,0.9);
    color: #ffffff;
}}
QPushButton:pressed {{
    background: rgba(45,45,45,0.95);
}}
"""

UNIQUE_DANGER_BUTTON_STYLE = """
QPushButton {
    background: rgba(160,40,40,0.85);
    color: white;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 9px;
}
QPushButton:hover {
    background: rgba(200,50,50,0.9);
}
"""

UNIQUE_PAD_BUTTON_STYLE = f"""
QPushButton#uniquePadButton {{
    background: rgba(60,60,60,0.9);
    color: {GOLD};
    border: none;
    border-radius: 4px;
    font-weight: bold;
}}
QPushButton#uniquePadButton:hover {{
    background: rgba(80,80,80,0.9);
}}
"""

UNIQUE_INPUT_STYLE = f"""
QLineEdit {{
    background: rgba(35,35,35,0.92);
    color: {GOLD};
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px;
    padding: 0px 4px;
    font-size: 12px;
    font-weight: bold;
    min-width: 52px;
}}
"""

UNIQUE_ACTIVE_INPUT_STYLE = f"""
QLineEdit {{
    background: rgba(45,45,45,1.0);
    color: {GOLD};
    border: 2px solid {GOLD};
    border-radius: 6px;
    padding: 0px 3px;
    font-size: 12px;
    font-weight: bold;
}}
"""

UNIQUE_KEYPAD_BUTTON_STYLE = f"""
QPushButton {{
    background: rgba(45,45,45,0.85);
    color: {TEXT};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 4px;
    font-size: 10px;
}}
QPushButton:hover {{
    background: rgba(70,70,70,0.95);
}}
"""

UNIQUE_STEP_BUTTON_STYLE = f"""
QPushButton {{
    background: rgba(60,60,60,0.75);
    color: {GOLD};
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 4px;
    font-size: 10px;
}}
QPushButton:hover {{
    background: rgba(80,80,80,0.9);
}}
"""

TOAST_STYLE = """
QFrame#toastPopup {
    background-color: rgb(48, 51, 58);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 12px;
}

QFrame#toastPopup QLabel {
    color: rgb(235, 235, 235);
    background: transparent;
}
"""