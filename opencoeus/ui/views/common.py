from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from ..theme import THEME


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {THEME.text}; font-size: 18px; font-weight: 700; "
        f"background: transparent; padding-bottom: 4px;"
    )
    return label


def fmt_size(size: int) -> str:
    if size >= 1073741824:
        return f"{size / 1073741824:.1f} GB"
    if size >= 1048576:
        return f"{size / 1048576:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"
