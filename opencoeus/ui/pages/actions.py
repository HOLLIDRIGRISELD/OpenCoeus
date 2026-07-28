from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, success_button_qss, danger_button_qss, accent_button_qss, warning_button_qss
from ...database import AuditStore
from ...rules_engine import RuleMatch
from ..dialogs import BatchDetailDialog
from .common import (
    CardTable, section_title, truncate_path, status_badge, make_container,
)


# COLUMN WIDTHS FOR ACTIONS TABLE: [ID, Status, Action, Source, Target, Old Name, New Name, Rule].
_ACTIONS_COL_WIDTHS = [50, 110, 70, 200, 200, 120, 120, 80]

# COLUMN WIDTHS FOR BATCH HISTORY: [BatchID, Description, Status, Actions, Date].
_BATCH_COL_WIDTHS = [60, 200, 110, 60, 160]


class ActionsPage(QWidget):
    """Actions page with approve/reject and batch history."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._action_id_map: dict[str, int] = {}

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # TITLE ROW
        title_row = QHBoxLayout()
        title_row.addWidget(section_title("Proposed Actions"))
        title_row.addStretch()
        self.count_label = QLabel("0 actions")
        self.count_label.setStyleSheet(
            f"color: {COLORS.get('text2', '#7f848e')}; font-size: 12px;"
        )
        title_row.addWidget(self.count_label)
        root.addLayout(title_row)

        # TOOLBAR
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_approve = QPushButton("Approve Selected")
        btn_approve.setToolTip("Approve the selected actions")
        btn_approve.clicked.connect(self.approve_selected)
        btn_approve.setStyleSheet(success_button_qss())
        toolbar.addWidget(btn_approve)

        btn_approve_all = QPushButton("Approve All")
        btn_approve_all.setToolTip("Approve all pending actions")
        btn_approve_all.clicked.connect(self.approve_all)
        btn_approve_all.setStyleSheet(success_button_qss())
        toolbar.addWidget(btn_approve_all)

        btn_reject = QPushButton("Reject Selected")
        btn_reject.setToolTip("Reject the selected actions")
        btn_reject.clicked.connect(self.reject_selected)
        btn_reject.setStyleSheet(danger_button_qss())
        toolbar.addWidget(btn_reject)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # FILTER BAR
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)
        self._filter_buttons: list[QPushButton] = []
        filter_options = [("All", ""), ("Move", "move"), ("Rename", "rename"), ("Move+Rename", "move+rename")]
        for i, (label, ftype) in enumerate(filter_options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda checked, ft=ftype: self._filter_actions(ft))
            btn.setStyleSheet(self._filter_btn_qss(i == 0))
            filter_bar.addWidget(btn)
            self._filter_buttons.append(btn)
        filter_bar.addStretch()
        root.addLayout(filter_bar)

        # ACTIONS TABLE (CARD-BASED).
        self.actions_table = CardTable(
            ["ID", "Status", "Action", "Source", "Target", "Old Name", "New Name", "Rule"],
            column_widths=_ACTIONS_COL_WIDTHS,
        )
        self.actions_table.row_double_clicked.connect(self._on_action_double_clicked)
        root.addWidget(make_container(self.actions_table))

        # EXECUTE / UNDO TOOLBAR
        exec_toolbar = QHBoxLayout()
        exec_toolbar.setSpacing(8)

        btn_execute = QPushButton("Execute Batch")
        btn_execute.setToolTip("Execute all approved actions as a batch")
        btn_execute.setEnabled(False)
        btn_execute.clicked.connect(self._execute_batch)
        btn_execute.setStyleSheet(accent_button_qss())
        self._btn_execute = btn_execute
        exec_toolbar.addWidget(btn_execute)

        btn_undo = QPushButton("Undo Last Batch")
        btn_undo.setToolTip("Undo the last executed batch")
        btn_undo.setEnabled(False)
        btn_undo.clicked.connect(self._undo_last_batch)
        btn_undo.setStyleSheet(warning_button_qss())
        exec_toolbar.addWidget(btn_undo)

        exec_toolbar.addStretch()
        root.addLayout(exec_toolbar)

        # BATCH HISTORY
        root.addWidget(section_title("Batch History"))
        self.batch_table = CardTable(
            ["Batch ID", "Description", "Status", "Actions", "Date"],
            column_widths=_BATCH_COL_WIDTHS,
        )
        self.batch_table.row_double_clicked.connect(self._on_batch_double_clicked)
        root.addWidget(make_container(self.batch_table))

        root.addStretch()

    # MAIN WINDOW REFERENCE

    def set_main(self, main):
        """Store reference to main window."""
        self._main = main

    # FILTER

    def _filter_btn_qss(self, active: bool) -> str:
        """Stylesheet for filter buttons based on active state."""
        if active:
            return (
                f"background: {COLORS.get('accent', '#38bdf8')}; color: white;"
                f" padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        return (
            f"background: {COLORS.get('surface', '#1e1e2e')};"
            f" color: {COLORS.get('text', '#e2e8f0')};"
            f" padding: 4px 12px; border-radius: 4px;"
        )

    def _filter_actions(self, action_filter: str):
        """Filter actions table by action type: '' is all, 'move', 'rename', 'move+rename'."""
        for btn, (label, ftype) in zip(self._filter_buttons,
                                         [("All", ""), ("Move", "move"), ("Rename", "rename"), ("Move+Rename", "move+rename")]):
            active = (ftype == action_filter)
            btn.setChecked(active)
            btn.setStyleSheet(self._filter_btn_qss(active))
        for row in range(self.actions_table.rowCount()):
            action_text = ""
            action_widget = self.actions_table.cellWidget(row, 2)
            if action_widget is not None and hasattr(action_widget, "text"):
                action_text = action_widget.text()
            self.actions_table.setRowHidden(row, action_filter and action_text.lower() != action_filter.lower())

    # FILL ACTIONS

    def fill_actions(self, matches: list[RuleMatch], action_id_map: dict[str, int]):
        """Populate actions table from rule matches."""
        self._action_id_map = action_id_map

        approved_ids = self._load_approved_ids()
        self.actions_table.clear()

        for match in matches:
            db_id = action_id_map.get(match.original_path, 0)
            is_approved = db_id in approved_ids if db_id else False

            if is_approved:
                badge = status_badge("APPROVED", COLORS['green'], COLORS.get('green_bg', '#14302a'))
            else:
                badge = status_badge("PENDING", COLORS['yellow'], COLORS.get('yellow_bg', '#332e0e'))

            # COLOR CODE ACTION TYPE BADGES
            action_type = match.action_type.upper()
            if match.action_type == "rename":
                action_badge = status_badge(action_type, COLORS.get('accent', '#38bdf8'), COLORS.get('surface2', '#1f2038'))
            elif match.action_type == "move+rename":
                action_badge = status_badge(action_type, COLORS.get('purple', '#a78bfa'), COLORS.get('surface2', '#1f2038'))
            else:
                action_badge = status_badge(action_type, COLORS.get('text', '#e2e8f0'), COLORS.get('surface2', '#1f2038'))

            self.actions_table.addRow(
                widgets=[
                    (str(db_id) if db_id else "", None),
                    ("", badge),
                    ("", action_badge),
                    (truncate_path(match.original_path), None),
                    (truncate_path(match.proposed_path), None),
                    (match.original_filename, None),
                    (match.new_filename if match.new_filename else "", None),
                    (str(match.rule_id) if match.rule_id else "", None),
                ],
                tooltips=[
                    "", "", match.action_type,
                    match.original_path, match.proposed_path,
                    match.original_filename, match.new_filename, match.reason,
                ],
            )

        self.refresh_actions_count()

    def _load_approved_ids(self) -> set[int]:
        """Load set of approved action ids from db."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return set()
        store: AuditStore = self._main.store
        profile_id = None
        if hasattr(self._main, "current_profile") and self._main.current_profile:
            profile_id = self._main.current_profile.profile_id
        if profile_id is None:
            return set()
        actions = store.get_proposed_actions(profile_id)
        return {a.id for a in actions if a.approved}

    # APPROVE / REJECT

    def approve_selected(self):
        """Approve selected actions and persist to db."""
        selected = self.actions_table.selectedRows()
        if not selected:
            return
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        for row in selected:
            id_lbl = self.actions_table.item(row, 0)
            if id_lbl is not None:
                text = id_lbl.text()
                if text and text.isdigit():
                    store.approve_action(int(text))

        self._refresh_action_status()

    def approve_all(self):
        """Approve all actions and persist to db."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        for r in range(self.actions_table.rowCount()):
            id_lbl = self.actions_table.item(r, 0)
            if id_lbl is not None:
                text = id_lbl.text()
                if text and text.isdigit():
                    store.approve_action(int(text))

        self._refresh_action_status()

    def reject_selected(self):
        """Remove selected actions from table and db."""
        selected = self.actions_table.selectedRows()
        if not selected:
            return
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        for row in sorted(selected, reverse=True):
            id_lbl = self.actions_table.item(row, 0)
            if id_lbl is not None:
                text = id_lbl.text()
                if text and text.isdigit():
                    store.reject_action(int(text))
            self.actions_table.removeRow(row)

        self.refresh_actions_count()

    def _refresh_action_status(self):
        """Update status badges in-place after approval/rejection."""
        approved_ids = self._load_approved_ids()
        for r in range(self.actions_table.rowCount()):
            id_lbl = self.actions_table.item(r, 0)
            if id_lbl is None:
                continue
            text = id_lbl.text()
            if not text or not text.isdigit():
                continue
            db_id = int(text)
            is_approved = db_id in approved_ids

            if is_approved:
                badge = status_badge("APPROVED", COLORS['green'], COLORS.get('green_bg', '#14302a'))
            else:
                badge = status_badge("PENDING", COLORS['yellow'], COLORS.get('yellow_bg', '#332e0e'))

            self.actions_table.setCellWidget(r, 1, badge)

        self.refresh_actions_count()

    # REFRESH COUNT

    def refresh_actions_count(self):
        """Update count label and execute button state."""
        count = self.actions_table.rowCount()
        self.count_label.setText(f"{count} actions")
        self._btn_execute.setEnabled(count > 0)

    # BATCH HISTORY

    def refresh_batch_history(self):
        """Populate batch history table."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        profile_id = None
        if hasattr(self._main, "current_profile") and self._main.current_profile:
            profile_id = self._main.current_profile.profile_id

        all_batches = store.get_all_batches(profile_id, limit=20)
        batch_ids = [b.id for b in all_batches]
        entry_counts = store.get_batch_entry_counts(batch_ids)

        self.batch_table.clear()

        for batch in all_batches:
            status_text = batch.status.upper()
            if status_text == "COMPLETED":
                badge = status_badge(status_text, COLORS['green'], COLORS.get('green_bg', '#14302a'))
            elif status_text == "FAILED":
                badge = status_badge(status_text, COLORS['red'], COLORS.get('red_bg', '#3b1518'))
            else:
                badge = status_badge(status_text, COLORS['yellow'], COLORS.get('yellow_bg', '#332e0e'))

            date_str = batch.completed_at or batch.undone_at or batch.created_at
            date_text = str(date_str)[:19] if date_str else "—"

            self.batch_table.addRow(
                widgets=[
                    (str(batch.id), None),
                    (batch.description or "—", None),
                    ("", badge),
                    (str(entry_counts.get(batch.id, 0)), None),
                    (date_text, None),
                ],
                tooltips=["", "", "", "", ""],
            )

    def _on_action_double_clicked(self, row: int):
        """Show action details on double click."""
        pass

    def _on_batch_double_clicked(self, row: int):
        """Open batch detail dialog for the double-clicked batch."""
        id_lbl = self.batch_table.item(row, 0)
        if id_lbl is None:
            return
        batch_id = int(id_lbl.text())
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return
        store: AuditStore = self._main.store
        dialog = BatchDetailDialog(store, batch_id, parent=self)
        dialog.exec()

    # EXECUTE / UNDO

    def _execute_batch(self):
        """Delegate batch execution to main window."""
        if self._main is None:
            return
        if hasattr(self._main, "_execute_approved"):
            self._main._execute_approved()

    def _undo_last_batch(self):
        """Delegate undo to main window."""
        if self._main is None:
            return
        if hasattr(self._main, "_undo_last_batch"):
            self._main._undo_last_batch()
