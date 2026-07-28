from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, accent_button_qss, text_button_qss, warning_button_qss, danger_button_qss
from ...database import AuditStore
from ..dialogs import RuleEditDialog
from .common import CardTable, make_container, section_title


# COLUMN WIDTHS FOR RULES TABLE: [ID, Name, Type, Action, Template, Enabled, Priority].
_RULES_COL_WIDTHS = [40, 140, 80, 80, 180, 70, 60]


class RulesPage(QWidget):
    """Organization rules page with crud operations."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._store: AuditStore | None = None
        self._all_rules: list = []

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(section_title("Organization Rules"))

        # TOOLBAR
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_add = QPushButton("+ Add Rule")
        btn_add.setToolTip("Add a new organization rule")
        btn_add.setStyleSheet(accent_button_qss())
        btn_add.clicked.connect(self._add_rule)
        toolbar.addWidget(btn_add)

        btn_edit = QPushButton("Edit")
        btn_edit.setToolTip("Edit the selected rule")
        btn_edit.setStyleSheet(text_button_qss())
        btn_edit.clicked.connect(self._edit_rule)
        toolbar.addWidget(btn_edit)

        btn_toggle = QPushButton("Enable / Disable")
        btn_toggle.setToolTip("Toggle enabled state of the selected rule")
        btn_toggle.setStyleSheet(warning_button_qss())
        btn_toggle.clicked.connect(self._toggle_rule)
        toolbar.addWidget(btn_toggle)

        btn_delete = QPushButton("Delete")
        btn_delete.setToolTip("Delete the selected rules")
        btn_delete.setStyleSheet(danger_button_qss())
        btn_delete.clicked.connect(self._delete_rule)
        toolbar.addWidget(btn_delete)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # RULES TABLE (CARD-BASED)
        self.rules_table = CardTable(
            ["ID", "Name", "Type", "Action", "Template", "Enabled", "Priority"],
            column_widths=_RULES_COL_WIDTHS,
        )
        root.addWidget(make_container(self.rules_table))

        root.addStretch()

    # MAIN WINDOW REFERENCE

    def set_main(self, main):
        """Store reference to main window."""
        self._main = main

    # STORE REFERENCE

    def set_store(self, store: AuditStore):
        """Set the auditstore reference."""
        self._store = store

    # LOAD RULES

    def load_rules(self, profile_id):
        """Load rules from database, fall back to default rules."""
        if self._store is not None:
            enabled_rules = self._store.get_enabled_rules(profile_id)
            all_rules = self._store.get_rules(profile_id)
            if enabled_rules or all_rules:
                self._all_rules = all_rules if all_rules else enabled_rules
                self.refresh_table()
                return

        from ...rules_engine import DEFAULT_RULES
        self._all_rules = DEFAULT_RULES[:]
        self.refresh_table()

    # REFRESH TABLE

    def refresh_table(self):
        """Populate rules table from loaded rules."""
        rules = self._all_rules
        self.rules_table.clear()

        for rule in rules:
            # SUPPORT BOTH ORM OBJECTS AND DICTS
            if hasattr(rule, "id"):
                rule_id = str(rule.id)
                name = rule.name
                rule_type = rule.rule_type
                action_type = getattr(rule, "action_type", "move")
                template = rule.destination_template or getattr(rule, "rename_template", "") or ""
                enabled = "Yes" if rule.enabled else "No"
                priority = str(rule.priority)
            else:
                rule_id = str(rule.get("id", ""))
                name = rule.get("name", "")
                rule_type = rule.get("rule_type", "")
                action_type = rule.get("action_type", "move")
                template = rule.get("destination_template", "") or rule.get("rename_template", "")
                enabled = "Yes" if rule.get("enabled", True) else "No"
                priority = str(rule.get("priority", ""))

            # COLOR CODE ACTION TYPE
            action_label = action_type.upper()
            if action_type == "rename":
                action_color = COLORS.get("accent", "#38bdf8")
            elif action_type == "move+rename":
                action_color = COLORS.get("purple", "#a78bfa")
            else:
                action_color = COLORS.get("text", "#e2e8f0")

            # COLOR CODE ENABLED STATUS
            enabled_color = COLORS.get("green", "#4ade80") if enabled == "Yes" else COLORS.get("text2", "#7f848e")

            self.rules_table.addRow(
                widgets=[
                    (rule_id, None),
                    (name, None),
                    (rule_type, None),
                    (action_label, self._colored_label(action_label, action_color)),
                    (template, None),
                    (enabled, self._colored_label(enabled, enabled_color)),
                    (priority, None),
                ],
                tooltips=[name, "", action_type, template, "", "", ""],
            )

    @staticmethod
    def _colored_label(text: str, color: str) -> QLabel:
        """Create a colored label for table cells."""
        label = QLabel(text)
        label.setStyleSheet(f"color: {color}; font-size: 12px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    # ADD RULE

    def _add_rule(self):
        """Open rule edit dialog and save to db."""
        dialog = RuleEditDialog(self)
        if dialog.exec():
            rule = dialog.get_data()
            if self._store is not None and self._main is not None:
                profile_id = getattr(getattr(self._main, "current_profile", None), "profile_id", 1)
                self._store.add_rule(profile_id, rule)
                self.load_rules(profile_id)

    # EDIT RULE

    def _edit_rule(self):
        """Open rule edit dialog with the selected rule and update in db."""
        selected = self.rules_table.selectedRows()
        if not selected:
            return

        row = selected[0]
        if row >= len(self._all_rules):
            return

        rule = self._all_rules[row]
        # CONVERT ORM OBJECT TO DICT FOR THE DIALOG
        if hasattr(rule, "id"):
            rule_dict = {
                "id": rule.id, "name": rule.name, "rule_type": rule.rule_type,
                "rule_config": rule.rule_config, "destination_template": rule.destination_template,
                "priority": rule.priority, "enabled": rule.enabled,
                "action_type": getattr(rule, "action_type", "move"),
                "rename_template": getattr(rule, "rename_template", ""),
            }
        else:
            rule_dict = rule
        dialog = RuleEditDialog(self, rule=rule_dict)
        if dialog.exec():
            updated = dialog.get_data()
            if self._store is not None and hasattr(rule, "id"):
                self._store.update_rule(rule.id, **updated)
            elif self._store is not None and "id" in rule:
                self._store.update_rule(rule["id"], **updated)
            if self._main is not None and hasattr(self._main, "current_profile") and self._main.current_profile:
                self.load_rules(self._main.current_profile.profile_id)

    # TOGGLE RULE

    def _toggle_rule(self):
        """Toggle enabled/disabled in db."""
        selected = self.rules_table.selectedRows()
        if not selected:
            return

        if self._store is None:
            return

        for row in selected:
            if row >= len(self._all_rules):
                continue
            rule = self._all_rules[row]
            rule_id = rule.id if hasattr(rule, "id") else rule.get("id")
            if rule_id is not None:
                current_enabled = rule.enabled if hasattr(rule, "enabled") else rule.get("enabled", True)
                self._store.toggle_rule(rule_id, not current_enabled)

        if self._main is not None and hasattr(self._main, "current_profile") and self._main.current_profile:
            self.load_rules(self._main.current_profile.profile_id)

    # DELETE RULE

    def _delete_rule(self):
        """Delete selected rules from db."""
        selected = self.rules_table.selectedRows()
        if not selected:
            return

        reply = QMessageBox.question(
            self,
            "Delete Rules",
            f"Delete {len(selected)} selected rule(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._store is None:
            return

        for row in selected:
            if row >= len(self._all_rules):
                continue
            rule = self._all_rules[row]
            rule_id = rule.id if hasattr(rule, "id") else rule.get("id")
            if rule_id is not None:
                self._store.delete_rule(rule_id)

        if self._main is not None and hasattr(self._main, "current_profile") and self._main.current_profile:
            self.load_rules(self._main.current_profile.profile_id)
