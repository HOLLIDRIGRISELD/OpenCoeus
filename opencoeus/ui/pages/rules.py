from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, accent_button_qss, text_button_qss, warning_button_qss, danger_button_qss
from ...database import AuditStore
from ..dialogs import RuleEditDialog
from .common import make_table, make_container, section_title


DEFAULT_RULES = [
    {"name": "Move duplicates to archive", "action": "move", "condition": "size > 1MB"},
    {"name": "Delete old temporary files", "action": "delete", "condition": "age > 30 days"},
]


class RulesPage(QWidget):
    """ORGANIZATION RULES PAGE WITH CRUD OPERATIONS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._store: AuditStore | None = None

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

        # RULES TABLE
        self.rules_table = make_table(
            ["ID", "Name", "Action", "Condition", "Enabled", "Priority"],
            stretch_column=1,
        )
        root.addWidget(make_container(self.rules_table))

        root.addStretch()

    # MAIN WINDOW REFERENCE

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # STORE REFERENCE

    def set_store(self, store: AuditStore):
        """SET THE AUDITSTORE REFERENCE."""
        self._store = store

    # LOAD RULES

    def load_rules(self, profile_id):
        """LOAD RULES FROM DATABASE, FALL BACK TO DEFAULT_RULES."""
        if self._store is not None:
            enabled_rules = self._store.get_enabled_rules(profile_id)
            all_rules = self._store.get_rules(profile_id)
            if enabled_rules or all_rules:
                self._all_rules = all_rules if all_rules else enabled_rules
                self.refresh_table()
                return

        self._all_rules = DEFAULT_RULES[:]
        self.refresh_table()

    # REFRESH TABLE

    def refresh_table(self):
        """POPULATE RULES TABLE FROM LOADED RULES."""
        rules = getattr(self, "_all_rules", [])
        self.rules_table.setSortingEnabled(False)
        self.rules_table.setRowCount(len(rules))

        for r, rule in enumerate(rules):
            rule_id = str(rule.get("id", ""))
            name = rule.get("name", "")
            action = rule.get("action", "")
            condition = rule.get("condition", "")
            enabled = "Yes" if rule.get("enabled", True) else "No"
            priority = str(rule.get("priority", ""))

            self.rules_table.setItem(r, 0, QTableWidgetItem(rule_id))
            self.rules_table.setItem(r, 1, QTableWidgetItem(name))
            self.rules_table.setItem(r, 2, QTableWidgetItem(action))
            self.rules_table.setItem(r, 3, QTableWidgetItem(condition))

            enabled_item = QTableWidgetItem(enabled)
            if enabled == "No":
                enabled_item.setForeground(self._color("text2", "#7f848e"))
            else:
                enabled_item.setForeground(self._color("green", "#98c379"))
            self.rules_table.setItem(r, 4, enabled_item)

            self.rules_table.setItem(r, 5, QTableWidgetItem(priority))

        self.rules_table.setSortingEnabled(True)

    # ADD RULE

    def _add_rule(self):
        """OPEN RULEEDITDIALOG AND SAVE TO DB."""
        dialog = RuleEditDialog(self)
        if dialog.exec():
            rule = dialog.get_data()
            if self._store is not None:
                self._store.add_rule(rule)
            if self._main is not None and hasattr(self._main, "current_profile") and hasattr(self._main.current_profile, "profile_id"):
                self.load_rules(self._main.current_profile.profile_id)

    # EDIT RULE

    def _edit_rule(self):
        """OPEN RULEEDITDIALOG WITH THE SELECTED RULE AND UPDATE IN DB."""
        selected = self.rules_table.selectionModel().selectedRows()
        if not selected:
            return

        row = selected[0].row()
        rules = getattr(self, "_all_rules", [])
        if row >= len(rules):
            return

        rule = rules[row]
        dialog = RuleEditDialog(self, rule=rule)
        if dialog.exec():
            updated = dialog.get_data()
            if self._store is not None and "id" in rule:
                self._store.update_rule(rule["id"], updated)
            if self._main is not None and hasattr(self._main, "current_profile") and hasattr(self._main.current_profile, "profile_id"):
                self.load_rules(self._main.current_profile.profile_id)

    # TOGGLE RULE

    def _toggle_rule(self):
        """TOGGLE ENABLED/DISABLED IN DB."""
        selected = self.rules_table.selectionModel().selectedRows()
        if not selected:
            return

        if self._store is None:
            return

        rules = getattr(self, "_all_rules", [])
        for idx in selected:
            row = idx.row()
            if row >= len(rules):
                continue
            rule = rules[row]
            if "id" in rule:
                new_state = not rule.get("enabled", True)
                self._store.toggle_rule(rule["id"], new_state)

        if self._main is not None and hasattr(self._main, "current_profile") and hasattr(self._main.current_profile, "profile_id"):
            self.load_rules(self._main.current_profile.profile_id)

    # DELETE RULE

    def _delete_rule(self):
        """DELETE SELECTED RULES FROM DB."""
        selected = self.rules_table.selectionModel().selectedRows()
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

        rules = getattr(self, "_all_rules", [])
        for idx in selected:
            row = idx.row()
            if row >= len(rules):
                continue
            rule = rules[row]
            if "id" in rule:
                self._store.delete_rule(rule["id"])

        if self._main is not None and hasattr(self._main, "current_profile") and hasattr(self._main.current_profile, "profile_id"):
            self.load_rules(self._main.current_profile.profile_id)

    # HELPERS

    @staticmethod
    def _color(key: str, default: str) -> QColor:
        """GET COLOR FROM THEME OR FALLBACK."""
        try:
            from ..theme import COLORS as _C
            return QColor(_C.get(key, default))
        except ImportError:
            return QColor(default)
