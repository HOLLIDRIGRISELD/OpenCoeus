from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models.app_state import AppState
from ..theme import THEME


_CARD_STYLE = """
    QWidget#home-card {
        background-color: %s;
        border: 1px solid %s;
        border-radius: 8px;
        padding: 16px;
    }
"""

_STAT_CARD = """
    QWidget#stat-card {
        background-color: %s;
        border: 1px solid %s;
        border-radius: 8px;
        padding: 20px;
    }
"""


class HomePage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Select a folder to scan...")
        self._browse_btn = QPushButton("Browse")
        self._scan_btn = QPushButton("Scan & Organize")
        self._stat_folders = QLabel("0")
        self._stat_files = QLabel("0")
        self._stat_actions = QLabel("0")
        self._stat_batches = QLabel("0")
        self._recent_label = QLabel()
        self._stat_cards: list[QWidget] = []
        self._scan_card: QWidget | None = None

        self._build_ui()
        self._state.state_changed.connect(self._refresh)

    @staticmethod
    def _stat_card(value_label: QLabel, title: str, color: str) -> QWidget:
        card = QWidget()
        card.setObjectName("stat-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        value_label.setStyleSheet(
            f"color: {color}; font-size: 28px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(value_label)
        label = QLabel(title)
        label.setStyleSheet(
            f"color: {THEME.text2}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(label)
        card.title_label = label
        return card

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        welcome = QLabel("Welcome back")
        welcome.setStyleSheet(
            f"color: {THEME.text2}; font-size: 14px; background: transparent;"
        )
        layout.addWidget(welcome)

        # Stats grid
        stats = QGridLayout()
        stats.setSpacing(12)
        c1 = self._stat_card(self._stat_folders, "Scanned Folders", THEME.accent)
        c1.setStyleSheet(_STAT_CARD % (THEME.surface, THEME.border))
        stats.addWidget(c1, 0, 0)
        c2 = self._stat_card(self._stat_files, "Files Found", THEME.green)
        c2.setStyleSheet(_STAT_CARD % (THEME.surface, THEME.border))
        stats.addWidget(c2, 0, 1)
        c3 = self._stat_card(self._stat_actions, "Pending Actions", THEME.yellow)
        c3.setStyleSheet(_STAT_CARD % (THEME.surface, THEME.border))
        stats.addWidget(c3, 0, 2)
        c4 = self._stat_card(self._stat_batches, "Batches", THEME.orange)
        c4.setStyleSheet(_STAT_CARD % (THEME.surface, THEME.border))
        stats.addWidget(c4, 0, 3)
        layout.addLayout(stats)
        self._stat_cards = [c1, c2, c3, c4]

        # Scan card
        card = QWidget()
        card.setObjectName("home-card")
        card.setStyleSheet(_CARD_STYLE % (THEME.surface, THEME.border))
        self._scan_card = card

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)

        card_title = QLabel("Start a New Scan")
        card_title.setStyleSheet(
            f"color: {THEME.text}; font-size: 16px; font-weight: 600;"
        )
        card_layout.addWidget(card_title)

        path_row = QHBoxLayout()
        self._browse_btn.clicked.connect(self._browse)
        self._browse_btn.setStyleSheet(self._accent_button_style())
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(self._browse_btn)
        card_layout.addLayout(path_row)

        self._scan_btn.setEnabled(False)
        self._scan_btn.setStyleSheet(self._accent_button_style(big=True))
        self._scan_btn.clicked.connect(self._start_scan)
        card_layout.addWidget(self._scan_btn, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(card)

        self._recent_label.setStyleSheet(
            f"color: {THEME.text2}; font-size: 12px; background: transparent; padding: 4px 0;"
        )
        layout.addWidget(self._recent_label)
        layout.addStretch()

    def _accent_button_style(self, big: bool = False) -> str:
        padding = "10px 24px" if big else "8px 20px"
        font_size = "13px" if big else "12px"
        return (
            f"QPushButton {{ background-color: {THEME.accent}; color: #fff; "
            f"border: none; border-radius: 6px; padding: {padding}; "
            f"font-weight: 600; font-size: {font_size}; }}"
            f"QPushButton:hover {{ background-color: {THEME.accent_hov}; }}"
            f"QPushButton:disabled {{ background-color: {THEME.surface3}; color: {THEME.text3}; }}"
        )

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Root Folder")
        if folder:
            self._path_edit.setText(folder)
            self._state.folder = Path(folder)
            self._scan_btn.setEnabled(True)

    def _start_scan(self) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow) and self._state.folder:
            w.start_scan(self._state.folder)

    def _refresh(self) -> None:
        s = self._state
        self._stat_folders.setText(str(s.folder_count or 0))
        self._stat_files.setText(str(s.scanned_count or 0))
        self._stat_actions.setText(str(s.action_count))
        self._stat_batches.setText(str(s.batch_count))

        if s.batches:
            recent = s.batches[:5]
            parts = [f"Batch #{b.id}: {b.status}" for b in recent]
            self._recent_label.setText("Recent Batches: " + " | ".join(parts))
        else:
            self._recent_label.setText("")

    def refresh_theme(self) -> None:
        t = THEME
        for card in self._stat_cards:
            card.setStyleSheet(_STAT_CARD % (t.surface, t.border))
            title_label = getattr(card, "title_label", None)
            if title_label is not None:
                title_label.setStyleSheet(
                    f"color: {t.text2}; font-size: 12px; background: transparent;"
                )
        if self._scan_card:
            self._scan_card.setStyleSheet(_CARD_STYLE % (t.surface, t.border))
        for label, color in (
            (self._stat_folders, t.accent),
            (self._stat_files, t.green),
            (self._stat_actions, t.yellow),
            (self._stat_batches, t.orange),
        ):
            label.setStyleSheet(
                f"color: {color}; font-size: 28px; font-weight: 700; background: transparent;"
            )
        self._browse_btn.setStyleSheet(self._accent_button_style())
        self._scan_btn.setStyleSheet(self._accent_button_style(big=True))
        self._recent_label.setStyleSheet(
            f"color: {t.text2}; font-size: 12px; background: transparent; padding: 4px 0;"
        )
