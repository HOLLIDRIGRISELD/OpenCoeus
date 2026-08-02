from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..theme import THEME


_RULE_TYPES = ["regex", "glob", "extension", "keyword", "nlp"]
_ACTION_TYPES = ["move", "copy", "rename", "archive"]


class RuleEditDialog(QDialog):
    def __init__(self, parent=None, rule: dict | None = None) -> None:
        super().__init__(parent)
        self._rule = rule
        self.setWindowTitle("Edit Rule" if rule else "New Rule")
        self.setMinimumWidth(500)
        self.setStyleSheet(THEME.dialog_stylesheet())

        self._name_edit = QLineEdit()
        self._type_combo = QComboBox()
        self._action_combo = QComboBox()
        self._pattern_edit = QPlainTextEdit()
        self._template_edit = QLineEdit()
        self._priority_spin = QLineEdit()

        self._build_ui()
        if rule:
            self._populate(rule)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Create Rule" if not self._rule else "Edit Rule")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding-bottom: 8px;")
        layout.addWidget(title)

        form = QFormLayout()
        self._name_edit.setPlaceholderText("Rule name")
        form.addRow("Name:", self._name_edit)

        self._type_combo.addItems(_RULE_TYPES)
        form.addRow("Type:", self._type_combo)

        self._action_combo.addItems(_ACTION_TYPES)
        form.addRow("Action:", self._action_combo)

        self._pattern_edit.setPlaceholderText("Pattern (regex, glob, or comma-separated extensions/keywords)")
        self._pattern_edit.setMaximumHeight(80)
        form.addRow("Pattern:", self._pattern_edit)

        self._template_edit.setPlaceholderText("Destination template, e.g. /sorted/{category}/{filename}")
        form.addRow("Template:", self._template_edit)

        self._priority_spin.setPlaceholderText("Priority (higher = first)")
        self._priority_spin.setText("0")
        form.addRow("Priority:", self._priority_spin)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _populate(self, rule: dict) -> None:
        self._name_edit.setText(rule.get("name", ""))
        idx = self._type_combo.findText(rule.get("rule_type", ""))
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        idx = self._action_combo.findText(rule.get("action_type", ""))
        if idx >= 0:
            self._action_combo.setCurrentIndex(idx)
        self._pattern_edit.setPlainText(rule.get("pattern", ""))
        self._template_edit.setText(rule.get("destination_template", ""))
        self._priority_spin.setText(str(rule.get("priority", 0)))

    def get_rule_data(self) -> dict:
        return {
            "name": self._name_edit.text().strip(),
            "rule_type": self._type_combo.currentText(),
            "action_type": self._action_combo.currentText(),
            "pattern": self._pattern_edit.toPlainText().strip(),
            "destination_template": self._template_edit.text().strip(),
            "priority": int(self._priority_spin.text() or "0"),
            "enabled": True,
        }
