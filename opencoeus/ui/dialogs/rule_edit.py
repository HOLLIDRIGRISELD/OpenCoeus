from __future__ import annotations

import json

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ..theme import COLORS, accent_button_qss, dialog_stylesheet


class RuleEditDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, rule: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Rule" if rule else "Add Rule")
        self.setMinimumWidth(450)
        self.rule = rule or {}

        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.name_input = QLineEdit(self.rule.get("name", ""))
        self.name_input.setPlaceholderText("Rule name")
        layout.addRow("Name:", self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["extension", "pattern", "date", "size", "folder", "status", "always"])
        idx = self.type_combo.findText(self.rule.get("rule_type", "extension"))
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        layout.addRow("Type:", self.type_combo)

        self.priority_input = QLineEdit(str(self.rule.get("priority", 10)))
        self.priority_input.setPlaceholderText("10")
        layout.addRow("Priority:", self.priority_input)

        self.template_input = QLineEdit(self.rule.get("destination_template", ""))
        self.template_input.setPlaceholderText("{folder}/Documents/{filename}")
        layout.addRow("Destination:", self.template_input)

        self.config_input = QLineEdit(self.rule.get("rule_config", "{}"))
        self.config_input.setPlaceholderText('{"extensions": [".pdf", ".docx"]}')
        layout.addRow("Config (JSON):", self.config_input)

        self._config_warning = QLabel("")
        self._config_warning.setStyleSheet(f"color: {COLORS['red']}; font-size: 11px;")
        self._config_warning.hide()
        layout.addRow("", self._config_warning)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(self.rule.get("enabled", True))
        layout.addRow("", self.enabled_check)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(accent_button_qss())
        save_btn.clicked.connect(self._on_save)
        buttons.addWidget(save_btn)
        layout.addRow(buttons)

        self.setStyleSheet(dialog_stylesheet())

    def _on_save(self) -> None:
        config_text = self.config_input.text().strip()
        if config_text:
            try:
                json.loads(config_text)
            except json.JSONDecodeError as exc:
                self._config_warning.setText(f"Invalid JSON: {exc.msg}")
                self._config_warning.show()
                return
        self._config_warning.hide()
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.name_input.text(),
            "rule_type": self.type_combo.currentText(),
            "priority": int(self.priority_input.text() or "10"),
            "destination_template": self.template_input.text(),
            "rule_config": self.config_input.text(),
            "enabled": self.enabled_check.isChecked(),
        }
