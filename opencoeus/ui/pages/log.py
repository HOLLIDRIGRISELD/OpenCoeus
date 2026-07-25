from __future__ import annotations

from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, text_button_qss
from .common import section_title, section_sub

MAX_LOG_LINES = 5000


class LogPage(QWidget):
    """ACTIVITY LOG PAGE WITH REAL-TIME MESSAGES."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # HEADER ROW
        header_row = QHBoxLayout()
        header_row.addWidget(section_title("Activity Log"))
        header_row.addStretch()

        btn_clear = QPushButton("Clear")
        btn_clear.setToolTip("Clear the log")
        btn_clear.setStyleSheet(text_button_qss())
        btn_clear.clicked.connect(self.clear_log)
        header_row.addWidget(btn_clear)

        root.addLayout(header_row)

        root.addWidget(section_sub("Real-time log of scan operations."))

        # LOG TEXT EDIT
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            f"background: {COLORS.get('surface', '#2b2b2b')}; "
            f"color: {COLORS.get('text', '#ffffff')}; "
            "border-radius: 8px; padding: 8px; font-family: monospace; font-size: 12px;"
        )
        root.addWidget(self.log_text)

    # ── MAIN WINDOW REFERENCE ──────────────────────────────────────────────

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # ── APPEND MESSAGE ─────────────────────────────────────────────────────

    def append_message(self, msg: str):
        """APPEND MESSAGE TO LOG, CAP AT 5000 LINES."""
        self.log_text.append(msg)

        # TRIM TO MAX LINES
        block_count = self.log_text.document().blockCount()
        if block_count > MAX_LOG_LINES:
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.MoveAnchor,
                block_count - MAX_LOG_LINES,
            )
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.removeSelectedText()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            self.log_text.setTextCursor(cursor)

        # SCROLL TO BOTTOM
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ── CLEAR LOG ──────────────────────────────────────────────────────────

    def clear_log(self):
        """CLEAR THE LOG TEXT."""
        self.log_text.clear()
