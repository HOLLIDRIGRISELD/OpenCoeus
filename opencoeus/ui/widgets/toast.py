from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..theme import THEME


class Toast(QWidget):
    def __init__(self, parent: QWidget, message: str, duration: int = 3000,
                 color: str | None = None) -> None:
        super().__init__(parent)
        bg = color or THEME.accent
        self.setStyleSheet(f"""
            background-color: {bg}; color: #fff;
            border-radius: 8px; padding: 10px 18px;
        """)
        self.setVisible(False)

        label = QLabel(message)
        label.setStyleSheet("color: #fff; font-size: 12px; font-weight: 600; background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)

        self.adjustSize()
        self._reposition()
        self.setVisible(True)

        QTimer.singleShot(duration, self._fade_out)

    def _reposition(self) -> None:
        p = self.parent()
        if p:
            x = p.width() - self.width() - 20
            y = 20
            self.move(x, y)

    def _fade_out(self) -> None:
        self.deleteLater()


class ToastManager:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent

    def show(self, message: str, duration: int = 3000, color: str | None = None) -> None:
        Toast(self._parent, message, duration, color)
