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

from ..theme import COLORS
from ...database import AuditStore
from ...rules_engine import RuleMatch
from ..dialogs import BatchDetailDialog
from .common import make_table, make_container, section_title, truncate_path


class ActionsPage(QWidget):
    """ACTIONS PAGE WITH APPROVE/REJECT AND BATCH HISTORY."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._action_id_map: dict[int, int] = {}

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
        toolbar.addWidget(btn_approve)

        btn_approve_all = QPushButton("Approve All")
        btn_approve_all.setToolTip("Approve all pending actions")
        btn_approve_all.clicked.connect(self.approve_all)
        toolbar.addWidget(btn_approve_all)

        btn_reject = QPushButton("Reject Selected")
        btn_reject.setToolTip("Reject the selected actions")
        btn_reject.clicked.connect(self.reject_selected)
        toolbar.addWidget(btn_reject)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # ACTIONS TABLE
        self.actions_table = make_table(
            ["ID", "Action", "Source", "Target", "Rule"],
            stretch_column=2,
            select_mode=self.actions_table_select_mode(),
        )
        root.addWidget(make_container(self.actions_table))

        # EXECUTE / UNDO TOOLBAR
        exec_toolbar = QHBoxLayout()
        exec_toolbar.setSpacing(8)

        btn_execute = QPushButton("Execute Batch")
        btn_execute.setToolTip("Execute all approved actions as a batch")
        btn_execute.setEnabled(False)
        btn_execute.clicked.connect(self._execute_batch)
        self._btn_execute = btn_execute
        exec_toolbar.addWidget(btn_execute)

        btn_undo = QPushButton("Undo Last Batch")
        btn_undo.setToolTip("Undo the last executed batch")
        btn_undo.setEnabled(False)
        btn_undo.clicked.connect(self._undo_last_batch)
        self._btn_undo = btn_undo
        exec_toolbar.addWidget(btn_undo)

        exec_toolbar.addStretch()
        root.addLayout(exec_toolbar)

        # BATCH HISTORY
        root.addWidget(section_title("Batch History"))
        self.batch_table = make_table(
            ["Batch ID", "Timestamp", "Actions", "Status", "Profile"],
            stretch_column=4,
        )
        self.batch_table.setMaximumHeight(150)
        self.batch_table.doubleClicked.connect(self._on_batch_double_clicked)
        root.addWidget(make_container(self.batch_table))

        root.addStretch()

    @staticmethod
    def actions_table_select_mode():
        """RETURN EXTENDED SELECTION MODE FOR ACTIONS TABLE."""
        from PyQt6.QtWidgets import QTableWidget
        return QTableWidget.SelectionMode.ExtendedSelection

    # ── MAIN WINDOW REFERENCE ──────────────────────────────────────────────

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # ── FILL ACTIONS ───────────────────────────────────────────────────────

    def fill_actions(self, matches: list[RuleMatch], action_id_map: dict[int, int]):
        """POPULATE ACTIONS TABLE FROM RULE MATCHES."""
        self._action_id_map = action_id_map
        self.actions_table.setSortingEnabled(False)
        self.actions_table.setRowCount(len(matches))

        for r, match in enumerate(matches):
            db_id = action_id_map.get(r, r)

            id_item = QTableWidgetItem(str(db_id))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            action_item = QTableWidgetItem(match.action)
            action_item.setToolTip(match.action)

            source_item = QTableWidgetItem(truncate_path(match.source))
            source_item.setToolTip(match.source)

            target_item = QTableWidgetItem(truncate_path(match.target))
            target_item.setToolTip(match.target)

            rule_item = QTableWidgetItem(match.rule_name)
            rule_item.setToolTip(match.rule_name)

            self.actions_table.setItem(r, 0, id_item)
            self.actions_table.setItem(r, 1, action_item)
            self.actions_table.setItem(r, 2, source_item)
            self.actions_table.setItem(r, 3, target_item)
            self.actions_table.setItem(r, 4, rule_item)

        self.actions_table.setSortingEnabled(True)
        self.refresh_actions_count()

    # ── APPROVE / REJECT ───────────────────────────────────────────────────

    def approve_selected(self):
        """APPROVE SELECTED ACTIONS AND PERSIST TO DB."""
        selected = self.actions_table.selectionModel().selectedRows()
        if not selected:
            return

        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        for idx in selected:
            row = idx.row()
            id_item = self.actions_table.item(row, 0)
            if id_item is not None:
                action_id = int(id_item.text())
                store.approve_action(action_id)

        self.refresh_actions_count()

    def approve_all(self):
        """APPROVE ALL ACTIONS AND PERSIST TO DB."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        for r in range(self.actions_table.rowCount()):
            id_item = self.actions_table.item(r, 0)
            if id_item is not None:
                action_id = int(id_item.text())
                store.approve_action(action_id)

        self.refresh_actions_count()

    def reject_selected(self):
        """REMOVE SELECTED ACTIONS FROM TABLE AND DB."""
        selected = self.actions_table.selectionModel().selectedRows()
        if not selected:
            return

        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        rows_to_remove = []
        for idx in selected:
            row = idx.row()
            id_item = self.actions_table.item(row, 0)
            if id_item is not None:
                action_id = int(id_item.text())
                store.reject_action(action_id)
            rows_to_remove.append(row)

        # REMOVE ROWS IN REVERSE ORDER
        for row in sorted(rows_to_remove, reverse=True):
            self.actions_table.removeRow(row)

        self.refresh_actions_count()

    # ── REFRESH COUNT ──────────────────────────────────────────────────────

    def refresh_actions_count(self):
        """UPDATE COUNT LABEL AND EXECUTE BUTTON STATE."""
        count = self.actions_table.rowCount()
        self.count_label.setText(f"{count} actions")
        self._btn_execute.setEnabled(count > 0)

    # ── BATCH HISTORY ──────────────────────────────────────────────────────

    def refresh_batch_history(self):
        """POPULATE BATCH HISTORY TABLE."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        batches = store.get_batch_history()
        self.batch_table.setSortingEnabled(False)
        self.batch_table.setRowCount(len(batches))

        for r, batch in enumerate(batches):
            batch_id = str(batch.get("id", ""))
            timestamp = str(batch.get("timestamp", ""))
            actions_count = str(batch.get("actions_count", ""))
            status = str(batch.get("status", ""))
            profile = str(batch.get("profile", ""))

            self.batch_table.setItem(r, 0, QTableWidgetItem(batch_id))
            self.batch_table.setItem(r, 1, QTableWidgetItem(timestamp))
            self.batch_table.setItem(r, 2, QTableWidgetItem(actions_count))
            self.batch_table.setItem(r, 3, QTableWidgetItem(status))
            self.batch_table.setItem(r, 4, QTableWidgetItem(profile))

        self.batch_table.setSortingEnabled(True)

    def _on_batch_double_clicked(self, index):
        """OPEN BATCHDETAILDIALOG FOR THE DOUBLE-CLICKED BATCH."""
        row = index.row()
        id_item = self.batch_table.item(row, 0)
        if id_item is None:
            return

        batch_id = int(id_item.text())
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        store: AuditStore = self._main.store
        batch_details = store.get_batch_details(batch_id)
        dialog = BatchDetailDialog(self, batch_details=batch_details)
        dialog.exec()

    # ── EXECUTE / UNDO ────────────────────────────────────────────────────

    def _execute_batch(self):
        """EXECUTE ALL APPROVED ACTIONS AS A BATCH."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        reply = QMessageBox.question(
            self,
            "Execute Batch",
            "Execute all approved actions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        store: AuditStore = self._main.store
        store.execute_batch()
        self.refresh_actions_count()
        self.refresh_batch_history()

    def _undo_last_batch(self):
        """UNDO THE LAST EXECUTED BATCH."""
        if self._main is None or not hasattr(self._main, "store") or self._main.store is None:
            return

        reply = QMessageBox.question(
            self,
            "Undo Batch",
            "Undo the last executed batch?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        store: AuditStore = self._main.store
        store.undo_last_batch()
        self.refresh_actions_count()
        self.refresh_batch_history()
