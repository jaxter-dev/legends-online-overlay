from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton


# ============================================================
# SHARED TOKENS
# ============================================================

GOLD = "#d4c5a1"
BORDER = "#5a5a5a"
BG = "rgb(40, 40, 40)"
BG_DARK = "rgb(28, 28, 28)"

BTN_PADDING = "1px 8px"
BTN_HEIGHT = 24
FOOTER_BTN_WIDTH = 104


# ============================================================
# SETTINGS WINDOW ROOT STYLE
# ============================================================

SETTINGS_STYLE = f"""
QWidget {{
    background-color: {BG};
    color: {GOLD};
    font-family: Arial;
    font-size: 12px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG};
    top: -1px;
}}

QTabBar::tab {{
    background: {BG_DARK};
    color: #888;
    padding: 7px 16px;
    border: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    margin-right: 2px;
    font-size: 12px;
    font-weight: normal;
}}

QTabBar::tab:selected {{
    background: {BG};
    color: #f2d97d;
    font-weight: normal;
    border-bottom: 1px solid #EFBF04;
}}

QCheckBox {{
    color: {GOLD};
    spacing: 7px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {BORDER};
    border-radius: 2px;
    background: {BG_DARK};
}}

QCheckBox::indicator:checked {{
    background: #4CAF50;
    border-color: #4CAF50;
}}

QRadioButton {{
    color: {GOLD};
    spacing: 7px;
    background: transparent;
}}

QRadioButton::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {BORDER};
    border-radius: 7px;
    background: {BG_DARK};
}}

QRadioButton::indicator:checked {{
    background: #4CAF50;
    border-color: #4CAF50;
}}

QComboBox {{
    background: {BG_DARK};
    color: {GOLD};
    border: 1px solid {BORDER};
    padding: 3px 8px;
    border-radius: 3px;
    min-height: 22px;
}}

QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

QComboBox QAbstractItemView {{
    background: {BG_DARK};
    color: {GOLD};
    selection-background-color: rgb(60,60,60);
    border: 1px solid {BORDER};
}}

QSpinBox {{
    background: {BG_DARK};
    color: {GOLD};
    border: 1px solid {BORDER};
    padding: 3px 6px;
    border-radius: 3px;
    min-height: 22px;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: {BG_DARK};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: rgba(212,197,161,0.40);
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QLabel {{
    background: transparent;
    color: {GOLD};
}}
"""


# ============================================================
# SMALL STYLE HELPERS
# ============================================================

def _button_style(
    *,
    background: str,
    color: str,
    border: str,
    hover_background: str,
    border_radius: int = 4,
    font_size: int = 9,
    font_weight: str | None = None,
    padding: str = BTN_PADDING,
) -> str:
    """
    Shared helper za QPushButton stylesheet string.

    Zakaj obstaja:
    - style_small_button
    - style_footer_button
    - style_save_button

    imajo zelo podobno strukturo, razlikujejo se samo v nekaj vrednostih.
    """
    weight_line = f" font-weight: {font_weight};" if font_weight else ""

    return (
        "QPushButton {"
        f" background: {background};"
        f" color: {color};"
        f" border: {border};"
        f" border-radius: {border_radius}px;"
        f" font-size: {font_size}px;"
        f"{weight_line}"
        f" padding: {padding};"
        "}"
        f"QPushButton:hover {{ background: {hover_background}; }}"
    )


# ============================================================
# UI HELPERS
# ============================================================

def build_group(title: str) -> QFrame:
    """
    Ustvari shared group container za settings sekcije.

    Opomba:
    funkcija samo pripravi frame + naslovni label.
    Parent layout mora sam dodati vsebino v frame.
    """
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{"
        f" background: rgba(50,50,50,0.6);"
        f" border: 1px solid {BORDER};"
        f" border-radius: 5px;"
        f"}}"
    )

    title_label = QLabel(f"  {title}", frame)
    title_label.setFont(QFont("Arial", 9, QFont.Weight.Bold))
    title_label.setFixedHeight(26)
    title_label.setStyleSheet(
        f"color: #f2d97d;"
        f" background: rgba(0,0,0,0.25);"
        f" border-bottom: 1px solid {BORDER};"
        f" border-radius: 5px 5px 0 0;"
    )

    return frame


def style_small_button(btn: QPushButton):
    """
    Standard small action button za settings tab gumbe.
    """
    btn.setFixedHeight(BTN_HEIGHT)
    btn.setStyleSheet(
        _button_style(
            background="rgba(60,60,60,0.9)",
            color="#ccc",
            border=f"1px solid {BORDER}",
            hover_background="rgba(80,80,80,0.9)",
            border_radius=3,
            font_size=9,
            padding=BTN_PADDING,
        )
    )


def style_footer_button(btn: QPushButton):
    """
    Standard footer button (npr. Cancel).
    """
    btn.setFixedSize(FOOTER_BTN_WIDTH, BTN_HEIGHT)
    btn.setStyleSheet(
        _button_style(
            background="rgb(50,50,50)",
            color="#aaa",
            border=f"1px solid {BORDER}",
            hover_background="rgb(65,65,65)",
            border_radius=4,
            font_size=9,
            padding=BTN_PADDING,
        )
    )


def style_save_button(btn: QPushButton):
    """
    Primary save/confirm button.
    """
    btn.setFixedSize(FOOTER_BTN_WIDTH, BTN_HEIGHT)
    btn.setStyleSheet(
        _button_style(
            background="#4CAF50",
            color="white",
            border="none",
            hover_background="#45a049",
            border_radius=4,
            font_size=9,
            font_weight="bold",
            padding=BTN_PADDING,
        )
    )