"""Visual design tokens and the application stylesheet.

The interface uses a dark "editorial" palette: deep slate surfaces, a teal accent
for safe actions and amber/red for review and destructive actions. Styles are
expressed with Qt properties (``card``, ``primary``, ``danger``, ``role``) so
widgets can opt in without ad-hoc colour strings scattered through the pages.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

SLATE_950 = "#0b1120"
SLATE_900 = "#0f172a"
SLATE_850 = "#131d33"
SLATE_800 = "#1a2742"
SLATE_700 = "#243352"
SLATE_600 = "#33456b"
TEXT = "#e6edf7"
MUTED = "#94a8c6"
FAINT = "#7487a8"
ACCENT = "#2dd4bf"
ACCENT_DARK = "#0f766e"
ACCENT_SOFT = "#cdf5ef"
BORDER_STRONG = "#526aa0"
SCROLL_HOVER = "#6076a8"
BLUE = "#60a5fa"
AMBER = "#fbbf24"
RED = "#f87171"
GREEN = "#4ade80"

STATUS_COLORS: dict[str, str] = {
    "analysed": GREEN,
    "pending_review": AMBER,
    "organised": ACCENT,
    "discovered": BLUE,
    "failed": RED,
    "unsupported": FAINT,
    "unavailable": RED,
    "pending": AMBER,
    "accepted": GREEN,
    "applied": ACCENT,
    "rejected": FAINT,
    "draft": BLUE,
    "approved": GREEN,
    "executing": AMBER,
    "completed": GREEN,
    "partially_completed": AMBER,
    "rolled_back": FAINT,
    "pending_analysis": BLUE,
    "extracting": BLUE,
    "analysing": BLUE,
}


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status.lower(), MUTED)


def status_badge_style(status: str) -> str:
    colour = status_color(status)
    return (
        f"color: {colour}; background: {QColor(colour).name()}22; "
        f"border: 1px solid {QColor(colour).name()}55; border-radius: 9px; "
        "padding: 2px 9px; font-size: 11px; font-weight: 600;"
    )


def confidence_color(confidence: float | None) -> str:
    if confidence is None:
        return FAINT
    if confidence >= 0.85:
        return GREEN
    if confidence >= 0.60:
        return AMBER
    return RED


STYLESHEET = f"""
* {{
    font-family: "Inter", "Segoe UI", "Noto Sans", "Cantarell", sans-serif;
    outline: none;
}}
QWidget {{
    background-color: {SLATE_950};
    color: {TEXT};
    font-size: 13px;
}}
/* Labels and checkboxes sit on cards; painting the window colour behind them
   draws a dark rectangle on every card. Only their text should be visible. */
QLabel, QCheckBox {{
    background: transparent;
}}
QMainWindow, QDialog {{
    background-color: {SLATE_950};
}}
QToolTip {{
    background: {SLATE_800};
    color: {TEXT};
    border: 1px solid {SLATE_600};
    padding: 6px;
    border-radius: 6px;
}}
QFrame#Sidebar {{
    background-color: {SLATE_900};
    border-right: 1px solid {SLATE_800};
}}
QFrame#Header {{
    background-color: {SLATE_950};
    border-bottom: 1px solid {SLATE_800};
}}
QFrame[card="true"] {{
    background-color: {SLATE_900};
    border: 1px solid {SLATE_800};
    border-radius: 12px;
}}
QFrame[card="true"]:hover {{
    border-color: {SLATE_700};
}}
QLabel[role="brand"] {{
    color: {TEXT};
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.4px;
}}
QLabel[role="brandMark"] {{
    background: {ACCENT};
    color: {SLATE_950};
    border-radius: 9px;
    font-size: 15px;
    font-weight: 900;
}}
QLabel[role="pageTitle"] {{
    color: {TEXT};
    font-size: 24px;
    font-weight: 800;
}}
QLabel[role="pageSubtitle"] {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel[role="cardTitle"] {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 700;
}}
QLabel[role="stat"] {{
    color: {TEXT};
    font-size: 26px;
    font-weight: 800;
}}
QLabel[role="hint"] {{
    color: {FAINT};
    font-size: 11px;
}}
QLabel[role="muted"] {{
    color: {MUTED};
}}
QLabel[role="warning"] {{
    color: {AMBER};
    font-size: 11px;
}}
QLabel[role="danger"] {{
    color: {RED};
    font-size: 11px;
}}
QLabel[role="detail"] {{
    color: {TEXT};
    font-size: 12px;
}}
QLabel[role="surface"] {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel[role="field"] {{
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
}}
QLabel[role="code"] {{
    color: {FAINT};
    font-family: monospace;
    font-size: 11px;
}}
QTextBrowser {{
    background: transparent;
    border: none;
    color: {TEXT};
    padding: 0;
}}
QTextBrowser a {{
    color: {BLUE};
    text-decoration: none;
}}
QPushButton {{
    background-color: {SLATE_800};
    color: {TEXT};
    border: 1px solid {SLATE_700};
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {SLATE_700};
    border-color: {SLATE_600};
}}
QPushButton:pressed {{
    background-color: {SLATE_600};
}}
QPushButton:disabled {{
    color: {FAINT};
    background-color: {SLATE_900};
    border-color: {SLATE_800};
}}
QPushButton[primary="true"] {{
    background-color: {ACCENT};
    color: {SLATE_950};
    border-color: {ACCENT};
}}
QPushButton[primary="true"]:hover {{
    background-color: #5eead4;
}}
QPushButton[primary="true"]:disabled {{
    background-color: {ACCENT_DARK};
    color: {ACCENT_SOFT};
    border-color: {ACCENT_DARK};
}}
QPushButton[danger="true"] {{
    color: {RED};
    border-color: #7f1d1d;
    background: #2a1218;
}}
QPushButton[danger="true"]:hover {{
    background: #3b1720;
}}
QPushButton[flat="true"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {MUTED};
    text-align: left;
    padding: 8px 12px;
}}
QPushButton[flat="true"]:hover {{
    color: {TEXT};
    background: {SLATE_800};
}}
QPushButton[nav="true"] {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {MUTED};
    text-align: left;
    padding: 10px 12px;
    font-weight: 600;
}}
QPushButton[nav="true"]:hover {{
    color: {TEXT};
    background: {SLATE_800};
}}
QPushButton[nav="true"]:checked {{
    color: {SLATE_950};
    background: {ACCENT};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {SLATE_850};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 7px 9px;
    selection-background-color: {ACCENT_DARK};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {FAINT};
    background: {SLATE_900};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {SLATE_850};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_DARK};
    color: {TEXT};
    padding: 4px;
}}
QCheckBox {{
    color: {MUTED};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background: {SLATE_850};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QTableWidget, QTableView {{
    background-color: {SLATE_900};
    alternate-background-color: {SLATE_850};
    border: 1px solid {SLATE_800};
    border-radius: 10px;
    gridline-color: {SLATE_800};
    selection-background-color: {SLATE_700};
    selection-color: {TEXT};
}}
QTableWidget::item {{
    padding: 7px 8px;
    border: none;
}}
QHeaderView::section {{
    background-color: {SLATE_850};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {SLATE_800};
    padding: 8px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
}}
QTableCornerButton::section {{
    background: {SLATE_850};
    border: none;
}}
QProgressBar {{
    background: {SLATE_800};
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {SCROLL_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {SCROLL_HOVER};
}}
QSplitter::handle {{
    background: {SLATE_800};
}}
QTabWidget::pane {{
    border: 1px solid {SLATE_800};
    border-radius: 10px;
}}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 8px 14px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
QStatusBar {{
    background: {SLATE_900};
    color: {MUTED};
    border-top: 1px solid {SLATE_800};
    padding: 4px 12px;
}}
QStatusBar::item {{
    border: none;
}}
QMenu {{
    background: {SLATE_850};
    color: {TEXT};
    border: 1px solid {SLATE_700};
    padding: 4px;
}}
QMenu::item:selected {{
    background: {SLATE_700};
    border-radius: 4px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
"""
