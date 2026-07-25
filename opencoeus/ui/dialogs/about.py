from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ..theme import COLORS, dialog_stylesheet, text_button_qss


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About OpenCoeus")
        self.setFixedSize(400, 250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(12)

        # APP NAME
        name_label = QLabel("OpenCoeus")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 28px; font-weight: bold;")
        layout.addWidget(name_label)

        # VERSION
        version_label = QLabel(f"Version {__version__}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet(f"color: {COLORS['text2']}; font-size: 13px;")
        layout.addWidget(version_label)

        # DESCRIPTION
        desc_label = QLabel("Offline-first Data Lifecycle Management")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setStyleSheet(f"color: {COLORS['text3']}; font-size: 12px;")
        layout.addWidget(desc_label)

        layout.addStretch()

        # CLOSE BUTTON
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(text_button_qss())
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setStyleSheet(dialog_stylesheet())
