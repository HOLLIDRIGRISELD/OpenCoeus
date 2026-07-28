from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QToolButton, QWidget
from ..theme import COLORS


class SidebarButton(QToolButton):

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(134, 40)
        self.setText(label)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setAutoRaise(True)
        self.setStyleSheet(f"""
            QToolButton {{
                border: none;
                border-radius: 12px;
                background: transparent;
                padding: 6px 20px 6px 12px;
                font-size: 13px;
                color: {COLORS["text2"]};
            }}
            QToolButton:hover {{
                background: {COLORS["surface3"]};
                color: {COLORS["text"]};
            }}
            QToolButton:checked {{
                background: {COLORS["accent2"]};
                color: #ffffff;
            }}
        """)
