from __future__ import annotations

import threading

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...database import AuditStore
from ...model_download import (
    download_model,
    download_llama_cli,
    is_model_downloaded,
    is_llama_cli_downloaded,
    model_path,
    llama_cli_path,
    PHI3_GGUF_FILENAME,
    Qwen25_GGUF_FILENAME,
)
from ...profiles import ProfileConfig, create_profile, update_profile
from ..theme import COLORS, dialog_stylesheet, accent_button_qss, text_button_qss


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

        self.nlp_threshold_input = QDoubleSpinBox()
        self.nlp_threshold_input.setRange(0.0, 1.0)
        self.nlp_threshold_input.setSingleStep(0.05)
        self.nlp_threshold_input.setDecimals(2)
        self.nlp_threshold_input.setValue(
            profile.nlp_confidence_threshold if profile else 0.0
        )
        self.nlp_threshold_input.setToolTip(
            "Minimum NLP confidence (0.0–1.0) to override rule-based results.\n"
            "0.0 = always apply NLP when available."
        )
        form.addRow("NLP confidence threshold:", self.nlp_threshold_input)

        self.installer_action_input = QComboBox()
        self.installer_action_input.addItems(["skip", "keep", "remove"])
        self.installer_action_input.setCurrentText(
            profile.installer_action if profile else "skip"
        )
        self.installer_action_input.setToolTip(
            "Action for installer/system files (exe, dmg, dll, etc.):\n"
            "skip – exclude from scan\n"
            "keep – scan but do not rename\n"
            "remove – flag for deletion"
        )
        form.addRow("Installer action:", self.installer_action_input)

        # LLM ENHANCEMENT
        llm_group = QGroupBox("LLM Enhancement")
        llm_group.setStyleSheet(
            f"QGroupBox {{ color: {COLORS['text']}; font-weight: bold; border: 1px solid {COLORS.get('surface3', '#252642')}; "
            f"border-radius: 6px; margin-top: 12px; padding-top: 16px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px; }}"
        )
        llm_layout = QFormLayout(llm_group)
        llm_layout.setSpacing(10)

        self.llm_enabled_check = QCheckBox("Use local LLM for smart filenames and destinations")
        self.llm_enabled_check.setChecked(profile.llm_enabled if profile else False)
        self.llm_enabled_check.toggled.connect(self._on_llm_toggled)
        llm_layout.addRow("", self.llm_enabled_check)

        self.llm_model_input = QComboBox()
        self.llm_model_input.addItems(["phi3", "qwen2.5"])
        self.llm_model_input.setCurrentText(profile.llm_model if profile else "phi3")
        self.llm_model_input.setToolTip(
            "phi3 – Phi-3-mini-4k-instruct (~2.5 GB, higher quality)\n"
            "qwen2.5 – Qwen2.5-1.5B-Instruct (~1 GB, faster)"
        )
        llm_layout.addRow("Model:", self.llm_model_input)

        self.llm_temp_input = QDoubleSpinBox()
        self.llm_temp_input.setRange(0.0, 1.0)
        self.llm_temp_input.setSingleStep(0.05)
        self.llm_temp_input.setDecimals(2)
        self.llm_temp_input.setValue(profile.llm_temperature if profile else 0.3)
        self.llm_temp_input.setToolTip("Lower = more deterministic; higher = more creative")
        llm_layout.addRow("Temperature:", self.llm_temp_input)

        self.llm_status_label = QLabel("")
        llm_layout.addRow("Status:", self.llm_status_label)

        self.llm_download_btn = QPushButton("Download Model")
        self.llm_download_btn.clicked.connect(self._on_download_llm)
        llm_layout.addRow("", self.llm_download_btn)

        self.llm_progress = QProgressBar()
        self.llm_progress.hide()
        llm_layout.addRow("", self.llm_progress)

        self.llm_enabled_check.setChecked(profile.llm_enabled if profile else False)
        self._update_llm_status()
        self._on_llm_toggled(self.llm_enabled_check.isChecked())

        form.addRow(llm_group)

        lay.addLayout(form)
        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(text_button_qss())
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(90)
        save_btn.setStyleSheet(accent_button_qss())
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        self.setStyleSheet(dialog_stylesheet())

    def _on_llm_toggled(self, enabled: bool) -> None:
        self.llm_model_input.setEnabled(enabled)
        self.llm_temp_input.setEnabled(enabled)
        self.llm_download_btn.setEnabled(enabled)
        if enabled:
            self._update_llm_status()

    def _update_llm_status(self) -> None:
        model_name = self.llm_model_input.currentText()
        if model_name == "phi3":
            filename = PHI3_GGUF_FILENAME
        elif model_name == "qwen2.5":
            filename = Qwen25_GGUF_FILENAME
        else:
            self.llm_status_label.setText("Unknown model")
            return

        if is_model_downloaded(filename):
            cli_ok = is_llama_cli_downloaded()
            try:
                from importlib.util import find_spec
                has_llama_cpp = find_spec("llama_cpp") is not None
            except Exception:
                has_llama_cpp = False
            if has_llama_cpp or cli_ok:
                self.llm_status_label.setText("Ready (model downloaded)")
                self.llm_status_label.setStyleSheet(f"color: {COLORS['green']};")
                self.llm_download_btn.setText("Redownload Model")
            else:
                self.llm_status_label.setText("Model downloaded; needs llama-cli backend")
                self.llm_status_label.setStyleSheet(f"color: {COLORS.get('yellow', '#fbbf24')};")
                self.llm_download_btn.setText("Download Backend")
        else:
            self.llm_status_label.setText("Not downloaded")
            self.llm_status_label.setStyleSheet(f"color: {COLORS.get('red', '#f87171')};")
            self.llm_download_btn.setText("Download Model (~2.5 GB)")

    def _on_download_llm(self) -> None:
        model_name = self.llm_model_input.currentText()
        if model_name == "phi3":
            filename = PHI3_GGUF_FILENAME
        elif model_name == "qwen2.5":
            filename = Qwen25_GGUF_FILENAME
        else:
            QMessageBox.warning(self, "LLM", f"Unknown model: {model_name}")
            return

        self.llm_download_btn.setEnabled(False)
        self.llm_progress.setRange(0, 0)
        self.llm_progress.show()
        self.llm_status_label.setText("Downloading...")

        def _do_download():
            try:
                download_model(filename)
                if not is_llama_cli_downloaded():
                    download_llama_cli()
            except Exception as exc:
                self.llm_progress.hide()
                self.llm_download_btn.setEnabled(True)
                self.llm_status_label.setText(f"Download failed: {exc}")
                self.llm_status_label.setStyleSheet(f"color: {COLORS.get('red', '#f87171')};")
                return
            self.llm_progress.hide()
            self.llm_download_btn.setEnabled(True)
            self._update_llm_status()

        threading.Thread(target=_do_download, daemon=True).start()

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
            "nlp_confidence_threshold": self.nlp_threshold_input.value(),
            "installer_action": self.installer_action_input.currentText(),
            "llm_enabled": self.llm_enabled_check.isChecked(),
            "llm_model": self.llm_model_input.currentText(),
            "llm_temperature": self.llm_temp_input.value(),
        }
        if self.is_new:
            create_profile(self.store, **kwargs)
        else:
            update_profile(self.store, self.profile.profile_id, **kwargs)
        self.saved.emit()
        self.close()
