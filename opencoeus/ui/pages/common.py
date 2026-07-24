from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHeaderView, QLabel, QTableWidget, QVBoxLayout


def section_title(text: str) -> QLabel:
    from ..theme import COLORS
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {COLORS['text']}; font-size: 18px; font-weight: bold; padding: 0;"
    )
    return lbl


def section_sub(text: str) -> QLabel:
    from ..theme import COLORS
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {COLORS['text2']}; font-size: 12px; padding: 0;"
    )
    lbl.setWordWrap(True)
    return lbl


def make_table(headers, stretch_column=0, select_mode=None):
    from PyQt6.QtWidgets import QTableWidget, QHeaderView
    from PyQt6.QtCore import Qt
    if select_mode is None:
        select_mode = QTableWidget.SelectionMode.SingleSelection
    table = QTableWidget()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    for col in range(len(headers)):
        if col == stretch_column:
            table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch
            )
        else:
            table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
    table.horizontalHeader().setMinimumSectionSize(60)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(select_mode)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(38)
    table.setShowGrid(False)
    table.setSortingEnabled(True)
    table.viewport().setAutoFillBackground(False)
    return table


def make_container(widget) -> QFrame:
    from PyQt6.QtWidgets import QFrame, QVBoxLayout
    from ..theme import COLORS
    frame = QFrame()
    frame.setStyleSheet(
        f"""
        QFrame {{
            background: {COLORS["surface"]};
            border-radius: 12px;
            border: none;
        }}
        """
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.addWidget(widget)
    return frame


def truncate_path(path: str, max_parts: int = 3) -> str:
    if not path:
        return ""
    parts = Path(path).parts
    if len(parts) <= max_parts:
        return path
    return ".../" + "/".join(parts[-max_parts:])


def fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1048576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1048576:.1f} MB"
