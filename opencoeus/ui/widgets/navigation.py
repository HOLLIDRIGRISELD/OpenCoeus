from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import THEME

_ICONS = ["\U0001f3e0", "\U0001f4c1", "\U0001f50d", "\U0001f4cb", "\U0001f4dd", "\U0001f6e0\ufe0f", "\u2699\ufe0f"]
_LABELS = ["Home", "Folders", "Results", "Actions", "Rules", "Log", "Settings"]


class SidebarButton(QPushButton):
    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_content()
        self._update_style(False)

    def _update_content(self) -> None:
        icon = _ICONS[self._index]
        label = _LABELS[self._index]
        self.setText(f"{icon}  {label}")
        self.setFixedWidth(170)

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self._update_style(active)

    def refresh_theme(self) -> None:
        self._update_style(self.isChecked())

    def _update_style(self, active: bool) -> None:
        t = THEME
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {t.accent}; color: #fff; border: none;
                    border-radius: 6px; padding: 8px 10px;
                    font-size: 13px; font-weight: 600; text-align: left;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent; color: {t.text2}; border: none;
                    border-radius: 6px; padding: 8px 10px;
                    font-size: 13px; font-weight: 500; text-align: left;
                }}
                QPushButton:hover {{ background-color: {t.surface2}; color: {t.text}; }}
            """)


class Sidebar(QWidget):
    page_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(200)
        self.setStyleSheet(f"background-color: {THEME.sidebar_bg};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 16)
        layout.setSpacing(2)

        self._brand = QLabel("OpenCoeus")
        self._brand.setStyleSheet(f"""
            color: {THEME.text}; font-size: 18px; font-weight: 700;
            background: transparent; padding: 4px 6px 12px 6px;
        """)
        layout.addWidget(self._brand)

        self._buttons: list[SidebarButton] = []
        for i in range(len(_LABELS)):
            btn = SidebarButton(i)
            btn.clicked.connect(lambda _checked, idx=i: self.page_changed.emit(idx))
            layout.addWidget(btn)
            self._buttons.append(btn)

        layout.addStretch()

    def set_active(self, index: int) -> None:
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == index)

    def refresh_theme(self) -> None:
        self.setStyleSheet(f"background-color: {THEME.sidebar_bg};")
        self._brand.setStyleSheet(f"""
            color: {THEME.text}; font-size: 18px; font-weight: 700;
            background: transparent; padding: 4px 6px 12px 6px;
        """)
        for btn in self._buttons:
            btn.refresh_theme()
