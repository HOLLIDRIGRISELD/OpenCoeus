from __future__ import annotations
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from ..theme import COLORS


class StatCard(QWidget):

    def __init__(self, title: str, value: str, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {COLORS['text2']}; font-size: 12px; border: none;")
        self._val = QLabel(value)
        self._val.setStyleSheet(f"color: {accent}; font-size: 28px; font-weight: bold; border: none;")
        layout.addWidget(title_lbl)
        layout.addWidget(self._val)

        self.setFixedHeight(90)
        self.setStyleSheet(f"""
            StatCard {{
                background: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-left: 3px solid {accent};
                border-radius: 14px;
            }}
        """)

    def set_value(self, value: str) -> None:
        self._val.setText(value)
