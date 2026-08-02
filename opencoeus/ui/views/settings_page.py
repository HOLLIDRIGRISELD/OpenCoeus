from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..models.app_state import AppState
from ..theme import THEME
from .common import section_title


class SettingsPage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(section_title("Settings"))

        self._appearance_card = self._make_card(
            "Appearance",
            [
                self._check_box(
                    "Dark mode",
                    self._state.settings.dark_theme if self._state.settings else THEME.dark,
                    self._on_dark_mode_toggled,
                ),
            ],
        )
        layout.addWidget(self._appearance_card)

        settings = self._state.settings
        self._behavior_card = self._make_card(
            "Behavior",
            [
                self._check_box(
                    "Run rules automatically after scan",
                    settings.organize_after_scan if settings else True,
                    self._on_organize_toggled,
                ),
                self._check_box(
                    "Ask before executing actions",
                    settings.confirm_execute if settings else True,
                    self._on_confirm_execute_toggled,
                ),
                self._check_box(
                    "Ask before undoing the last batch",
                    settings.confirm_undo if settings else True,
                    self._on_confirm_undo_toggled,
                ),
            ],
        )
        layout.addWidget(self._behavior_card)

        layout.addStretch()

    def _make_card(self, title: str, rows: list[QWidget]) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background-color: {THEME.surface}; border: 1px solid {THEME.border}; "
            f"border-radius: 8px; padding: 16px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)
        card_title = QLabel(title)
        card_title.setStyleSheet(
            f"color: {THEME.text}; font-size: 14px; font-weight: 600; background: transparent;"
        )
        card_layout.addWidget(card_title)
        for row in rows:
            row_layout = QHBoxLayout()
            row_layout.addWidget(row)
            row_layout.addStretch()
            card_layout.addLayout(row_layout)
        return card

    def _check_box(self, text: str, checked: bool, slot) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(checked)
        box.setStyleSheet(self._checkbox_stylesheet())
        box.toggled.connect(slot)
        return box

    @staticmethod
    def _checkbox_stylesheet() -> str:
        t = THEME
        return f"""
            QCheckBox {{
                color: {t.text2}; font-size: 13px; spacing: 10px; background: transparent;
            }}
            QCheckBox:hover {{ color: {t.text}; }}
            QCheckBox::indicator {{
                width: 18px; height: 18px; border-radius: 5px;
                border: 2px solid {t.border_lt}; background: {t.surface};
            }}
            QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
            QCheckBox::indicator:checked {{
                background: {t.accent}; border-color: {t.accent};
            }}
        """

    def _on_dark_mode_toggled(self, checked: bool) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow) and checked != THEME.dark:
            w.toggle_theme()

    def _on_organize_toggled(self, checked: bool) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow):
            w.set_organize_after_scan(checked)

    def _on_confirm_execute_toggled(self, checked: bool) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow):
            w.set_confirm_execute(checked)

    def _on_confirm_undo_toggled(self, checked: bool) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow):
            w.set_confirm_undo(checked)

    def refresh_theme(self) -> None:
        for card in (self._appearance_card, self._behavior_card):
            if card is not None:
                card.setStyleSheet(
                    f"background-color: {THEME.surface}; border: 1px solid {THEME.border}; "
                    f"border-radius: 8px; padding: 16px;"
                )
        for box in self.findChildren(QCheckBox):
            box.setStyleSheet(self._checkbox_stylesheet())
        self._set_checkbox("Dark mode", THEME.dark)

    def _set_checkbox(self, text: str, checked: bool) -> None:
        for box in self.findChildren(QCheckBox):
            if box.text() == text:
                box.blockSignals(True)
                box.setChecked(checked)
                box.blockSignals(False)
                return
