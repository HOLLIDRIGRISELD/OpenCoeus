from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..models.app_state import AppState
from .common import section_title


class LogPage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._log = QPlainTextEdit()
        self._auto_scroll = True

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(section_title("Activity Log"))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_btn = QPushButton("Clear")
        copy_btn = QPushButton("Copy All")
        clear_btn.clicked.connect(self._log.clear)
        copy_btn.clicked.connect(self._copy)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        self._log.setReadOnly(True)
        layout.addWidget(self._log, 1)

    def append(self, msg: str) -> None:
        self._log.appendPlainText(msg)
        if self._auto_scroll:
            sb = self._log.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._log.toPlainText())
