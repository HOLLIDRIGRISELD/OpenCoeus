from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...database import AuditStore
from ...profiles import ProfileConfig, create_profile, update_profile
from ..theme import COLORS, dialog_stylesheet


class ProfileEditDialog(QDialog):
    saved = pyqtSignal()

    def __init__(self, store: AuditStore, profile: ProfileConfig | None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.profile = profile
        self.is_new = profile is None
        self.setWindowTitle("New Profile" if self.is_new else f"Edit: {profile.name}")
        self.setMinimumSize(500, 480)
        self.setModal(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)

        title = QLabel("New Profile" if self.is_new else "Edit Profile")
        title.setStyleSheet(f"color: {COLORS['text']}; font-size: 20px; font-weight: bold;")
        lay.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. My Project")
        if profile:
            self.name_input.setText(profile.name)
        form.addRow("Name:", self.name_input)

        self.root_input = QLineEdit()
        self.root_input.setPlaceholderText("Default scan root folder")
        if profile and profile.root_path:
            self.root_input.setText(profile.root_path)
        form.addRow("Root path:", self.root_input)

        self.included_input = QTextEdit()
        self.included_input.setPlaceholderText("One folder path per line\nLeave empty to scan all folders")
        self.included_input.setMaximumHeight(80)
        if profile and profile.included_folders:
            self.included_input.setPlainText("\n".join(profile.included_folders))
        form.addRow("Include folders:", self.included_input)

        self.excluded_input = QTextEdit()
        self.excluded_input.setPlaceholderText("One folder path per line\nThese folders will be excluded from scanning")
        self.excluded_input.setMaximumHeight(80)
        if profile and profile.excluded_folders:
            self.excluded_input.setPlainText("\n".join(profile.excluded_folders))
        form.addRow("Exclude folders:", self.excluded_input)

        self.patterns_input = QTextEdit()
        self.patterns_input.setPlaceholderText("One regex pattern per line\nThese patterns add custom folder classifications")
        self.patterns_input.setMaximumHeight(80)
        if profile and profile.custom_protected_patterns:
            self.patterns_input.setPlainText("\n".join(profile.custom_protected_patterns))
        form.addRow("Custom patterns:", self.patterns_input)

        self.extraction_check = QCheckBox("Extract text from PDF/DOCX files")
        self.extraction_check.setChecked(
            profile.document_extraction if profile else True
        )
        form.addRow("Document extraction:", self.extraction_check)

        lay.addLayout(form)
        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS["accent2"]}; color: #fff; border: 1px solid {COLORS["accent"]}; font-weight: bold; }}
            QPushButton:hover {{ background: {COLORS["accent"]}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        self.setStyleSheet(dialog_stylesheet())

    def _parse_list(self, text: str) -> list[str]:
        return [line.strip() for line in text.strip().splitlines() if line.strip()]

    def _save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Profile", "Name is required.")
            return
        kwargs = {
            "name": name,
            "root_path": self.root_input.text().strip(),
            "included_folders": self._parse_list(self.included_input.toPlainText()),
            "excluded_folders": self._parse_list(self.excluded_input.toPlainText()),
            "custom_protected_patterns": self._parse_list(self.patterns_input.toPlainText()),
            "document_extraction": self.extraction_check.isChecked(),
        }
        if self.is_new:
            create_profile(self.store, **kwargs)
        else:
            update_profile(self.store, self.profile.profile_id, **kwargs)
        self.saved.emit()
        self.close()
