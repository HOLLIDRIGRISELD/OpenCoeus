from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..models.app_state import AppState
from ..models.rule_table_model import RuleTableModel
from ..theme import THEME
from ..widgets.table_view import TableView
from .common import section_title


class RulesPage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._model = RuleTableModel()
        self._table = TableView()
        self._info_label = QLabel()

        self._build_ui()
        self._state.state_changed.connect(self._refresh)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(section_title("Organization Rules"))

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Rule")
        edit_btn = QPushButton("Edit Selected")
        self._delete_btn = THEME.btn_danger("Delete Selected")
        toggle_btn = QPushButton("Toggle Enabled")
        add_btn.clicked.connect(self._add)
        edit_btn.clicked.connect(self._edit)
        self._delete_btn.clicked.connect(self._delete)
        toggle_btn.clicked.connect(self._toggle)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(self._delete_btn)
        btn_row.addWidget(toggle_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._table.setModel(self._model)
        layout.addWidget(self._table, 1)

        self._info_label.setStyleSheet(f"color: {THEME.text2}; font-size: 12px;")
        layout.addWidget(self._info_label)

    def _add(self) -> None:
        from ..dialogs.rule_edit_dialog import RuleEditDialog
        dlg = RuleEditDialog(self)
        if dlg.exec():
            from ..main_window import MainWindow
            w = self.window()
            if isinstance(w, MainWindow):
                w.rule_controller.add(dlg.get_rule_data())

    def _edit(self) -> None:
        rows = self._table.selected_rows()
        if not rows:
            return
        rule = self._model.get_rule(rows[0])
        if not rule:
            return
        from ..dialogs.rule_edit_dialog import RuleEditDialog
        rdict = rule if isinstance(rule, dict) else {
            "id": rule.id, "name": rule.name, "rule_type": rule.rule_type,
            "action_type": rule.action_type, "pattern": rule.pattern,
            "destination_template": rule.destination_template, "priority": rule.priority,
        }
        dlg = RuleEditDialog(self, rdict)
        if dlg.exec():
            from ..main_window import MainWindow
            w = self.window()
            if isinstance(w, MainWindow):
                rid = rdict.get("id")
                w.rule_controller.update(rid, **dlg.get_rule_data())

    def _delete(self) -> None:
        rows = self._table.selected_rows()
        if not rows:
            return
        from ..main_window import MainWindow
        w = self.window()
        if not isinstance(w, MainWindow):
            return
        for row in rows:
            r = self._model.get_rule(row)
            if r:
                rid = r.get("id") if isinstance(r, dict) else r.id
                w.rule_controller.delete(rid)

    def _toggle(self) -> None:
        rows = self._table.selected_rows()
        if not rows:
            return
        from ..main_window import MainWindow
        w = self.window()
        if not isinstance(w, MainWindow):
            return
        for row in rows:
            r = self._model.get_rule(row)
            if r:
                rid = r.get("id") if isinstance(r, dict) else r.id
                w.rule_controller.toggle(rid)

    def _refresh(self) -> None:
        if self._state.rules:
            self._model.load(self._state.rules)
            self._info_label.setText(f"{len(self._state.rules)} rule(s)")

    def refresh_theme(self) -> None:
        t = THEME
        self._info_label.setStyleSheet(f"color: {t.text2}; font-size: 12px;")
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.red}; color: #fff; border: none;
                border-radius: 6px; padding: 6px 16px;
                font-weight: 600; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #f87171; }}
            QPushButton:pressed {{ background-color: #dc2626; }}
            QPushButton:disabled {{ background-color: {t.surface3}; color: {t.text3}; }}
        """)
