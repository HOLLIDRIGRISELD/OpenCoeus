from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, accent_button_qss, text_button_qss, danger_button_qss
from ..widgets import StatCard
from ...profiles import (
    ProfileConfig,
    create_profile,
    delete_profile,
    list_profiles,
    load_profile_by_name,
    update_profile,
)
from ...database import AuditStore
from ..dialogs import ProfileEditDialog
from .common import section_title, section_sub


class HomePage(QWidget):
    """HOME PAGE WITH STAT CARDS AND PROFILE MANAGEMENT."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # TITLE
        root.addWidget(section_title("OpenCoeus"))
        root.addWidget(section_sub("Duplicate file scanner and organizer."))

        # STAT CARDS GRID
        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_folders = StatCard("Folders", "0", COLORS["accent"])
        self.card_files = StatCard("Files", "0", COLORS["text2"])
        self.card_duplicates = StatCard("Duplicates", "0", COLORS["yellow"])
        self.card_actions = StatCard("Actions", "0", COLORS["green"])
        grid.addWidget(self.card_folders, 0, 0)
        grid.addWidget(self.card_files, 0, 1)
        grid.addWidget(self.card_duplicates, 1, 0)
        grid.addWidget(self.card_actions, 1, 1)
        root.addLayout(grid)

        # PROFILE SECTION
        profile_header = QHBoxLayout()
        profile_header.addWidget(section_title("Profiles"))
        profile_header.addStretch()

        btn_new = QPushButton("+ New")
        btn_new.setToolTip("Create a new scan profile")
        btn_new.setStyleSheet(accent_button_qss())
        btn_new.clicked.connect(self._create_new_profile)
        profile_header.addWidget(btn_new)

        btn_edit = QPushButton("Edit")
        btn_edit.setToolTip("Edit the selected profile")
        btn_edit.setStyleSheet(text_button_qss())
        btn_edit.clicked.connect(self._edit_selected_profile)
        profile_header.addWidget(btn_edit)

        btn_delete = QPushButton("Delete")
        btn_delete.setToolTip("Delete the selected profile")
        btn_delete.setStyleSheet(danger_button_qss())
        btn_delete.clicked.connect(self._delete_selected_profile)
        profile_header.addWidget(btn_delete)

        root.addLayout(profile_header)

        # PROFILE LIST
        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(120)
        self.profile_list.setToolTip("Select a scan profile")
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        root.addWidget(self.profile_list)

        root.addStretch()

    # MAIN WINDOW REFERENCE

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW FOR CROSS-PAGE ACCESS."""
        self._main = main

    # PROFILE MANAGEMENT

    def load_profiles(self, store: AuditStore):
        """POPULATE PROFILE LIST FROM DATABASE."""
        self.profile_list.clear()
        profiles = list_profiles(store)
        if not profiles:
            self.profile_list.addItem("No profiles yet")
            return
        for p in profiles:
            self.profile_list.addItem(p.name)

    def _on_profile_selected(self, current, prev):
        """SET CURRENT PROFILE WHEN LIST SELECTION CHANGES."""
        if self._main is None:
            return
        if current is None:
            return
        name = current.text()
        if name == "No profiles yet":
            return
        self._main.current_profile = load_profile_by_name(self._main.store, name)

    def _create_new_profile(self):
        """OPEN PROFILEEDITDIALOG FOR A NEW PROFILE."""
        dialog = ProfileEditDialog(self._main.store, profile=None, parent=self)
        dialog.saved.connect(lambda: self.load_profiles(self._main.store))
        dialog.exec()

    def _edit_selected_profile(self):
        """OPEN PROFILEEDITDIALOG WITH THE CURRENT PROFILE."""
        item = self.profile_list.currentItem()
        if item is None or item.text() == "No profiles yet":
            return
        if self._main is None or self._main.store is None:
            return
        name = item.text()
        profile = load_profile_by_name(self._main.store, name)
        if profile is None:
            return
        dialog = ProfileEditDialog(self._main.store, profile=profile, parent=self)
        dialog.saved.connect(lambda: self.load_profiles(self._main.store))
        dialog.exec()

    def _delete_selected_profile(self):
        """CONFIRM THEN DELETE THE SELECTED PROFILE."""
        item = self.profile_list.currentItem()
        if item is None or item.text() == "No profiles yet":
            return
        name = item.text()
        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._main is not None and self._main.store is not None:
                profile = load_profile_by_name(self._main.store, name)
                if profile is not None:
                    delete_profile(self._main.store, profile.profile_id)
                    self.load_profiles(self._main.store)

    # STATS

    def update_stats(self, folders, files, duplicates, actions):
        """UPDATE THE 4 STAT CARD VALUES."""
        self.card_folders.set_value(str(folders))
        self.card_files.set_value(str(files))
        self.card_duplicates.set_value(str(duplicates))
        self.card_actions.set_value(str(actions))
