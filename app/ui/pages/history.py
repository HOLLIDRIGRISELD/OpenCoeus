"""History page: audit trail, undo, backups and database maintenance."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from app.ui.base import BasePage
from app.ui.theme import AMBER, GREEN, MUTED, RED
from app.ui.widgets import (
    Card,
    EmptyState,
    FlowLayout,
    add_actions,
    format_datetime,
    format_size,
    hint_label,
    make_table,
    muted_label,
    reveal_in_folder,
    scrollable_page,
    selected_data,
    set_cell,
)

STATUS_FILTERS = ["All statuses", "completed", "failed", "rolled_back", "pending"]


class HistoryPage(BasePage):
    """Every applied operation, with a safe undo path."""

    library_changed = Signal()
    navigate = Signal(str)

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._operations: dict[int, object] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = scrollable_page(self)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        top = add_actions(layout, self.refresh_button)
        top.insertWidget(
            0,
            muted_label(
                "OpenCoeus keeps an append-only log. Undo restores the original path and "
                "refuses to overwrite anything that appeared in the meantime."
            ),
            1,
        )

        operations_card = Card("Operation history", subtitle="newest first")
        filter_row = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(STATUS_FILTERS)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(QLabel("Show"))
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch(1)
        self.undo_button = QPushButton("Undo selected…")
        self.undo_button.setProperty("danger", True)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo_selected)
        filter_row.addWidget(self.undo_button)
        operations_card.add_layout(filter_row)

        self.operation_table = make_table(
            ["#", "File", "Type", "Status", "Undoable", "When"],
            stretch=1,
        )
        self.operation_table.itemSelectionChanged.connect(self._selection_changed)
        operations_card.add(self.operation_table)
        self.operation_hint = hint_label("")
        operations_card.add(self.operation_hint)
        self.empty_state = EmptyState(
            "No operations yet", "Run an approved plan to record it here."
        )
        self.empty_state.setVisible(False)
        operations_card.add(self.empty_state)
        layout.addWidget(operations_card, 3)

        backups_card = Card("Backups", subtitle="SQLite online backups")
        self.backup_table = make_table(
            ["File", "Size", "Created"],
            stretch=0,
        )
        self.backup_table.doubleClicked.connect(self._reveal_backup)
        backups_card.add(self.backup_table)
        backup_actions = FlowLayout()
        self.create_backup_button = QPushButton("Create backup")
        self.create_backup_button.setProperty("primary", True)
        self.create_backup_button.clicked.connect(self._create_backup)
        self.restore_button = QPushButton("Restore…")
        self.restore_button.setProperty("danger", True)
        self.restore_button.clicked.connect(self._restore_backup)
        self.show_backup_button = QPushButton("Backup folder")
        self.show_backup_button.setProperty("flat", True)
        self.show_backup_button.clicked.connect(self._show_backup_folder)
        backup_actions.addWidget(self.create_backup_button)
        backup_actions.addWidget(self.restore_button)
        backup_actions.addWidget(self.show_backup_button)
        backups_card.add_layout(backup_actions)
        backups_card.add(
            hint_label(
                "A restore replaces the live database. Close and reopen OpenCoeus afterwards."
            )
        )
        layout.addWidget(backups_card, 2)

        maintenance_card = Card("Maintenance")
        maintenance_actions = FlowLayout()
        self.integrity_button = QPushButton("Check integrity")
        self.integrity_button.clicked.connect(self._integrity_check)
        self.rebuild_index_button = QPushButton("Rebuild index")
        self.rebuild_index_button.clicked.connect(self._rebuild_index)
        self.vacuum_button = QPushButton("Compact database")
        self.vacuum_button.clicked.connect(self._vacuum)
        for button in (self.integrity_button, self.rebuild_index_button, self.vacuum_button):
            maintenance_actions.addWidget(button)
        maintenance_card.add_layout(maintenance_actions)
        self.maintenance_output = QLabel("")
        self.maintenance_output.setWordWrap(True)
        maintenance_card.add(self.maintenance_output)
        layout.addWidget(maintenance_card)

    def _set_busy(self, busy: bool) -> None:
        blocked = busy or self.has_running_tasks()
        for button in (
            self.refresh_button,
            self.create_backup_button,
            self.restore_button,
            self.show_backup_button,
            self.integrity_button,
            self.rebuild_index_button,
            self.vacuum_button,
        ):
            button.setEnabled(not blocked)
        if blocked:
            self.undo_button.setEnabled(False)
        else:
            self._selection_changed()

    def refresh(self) -> None:
        status = self.status_filter.currentText()
        try:
            operations = self.ctx.recovery.history(
                limit=300,
                status=None if status == "All statuses" else status,
            )
        except Exception as exc:
            self.message.emit(f"Could not load history: {exc}")
            self._operations.clear()
            self.operation_table.setRowCount(0)
            self.undo_button.setEnabled(False)
            self.operation_hint.setText("History could not be loaded.")
            self.empty_state.setVisible(True)
            return
        self._operations = {operation.id: operation for operation in operations}
        self.empty_state.setVisible(not operations)
        self.operation_table.setRowCount(0)
        for row, operation in enumerate(operations):
            self.operation_table.insertRow(row)
            set_cell(
                self.operation_table,
                row,
                0,
                str(operation.id),
                data=operation.id,
            )
            set_cell(self.operation_table, row, 1, operation.filename)
            set_cell(self.operation_table, row, 2, operation.operation_type.replace("_", " "))
            colour = {
                "completed": GREEN,
                "failed": RED,
                "rolled_back": AMBER,
            }.get(operation.status)
            set_cell(
                self.operation_table,
                row,
                3,
                operation.status.replace("_", " "),
                color=colour,
                tooltip=operation.error_message,
            )
            set_cell(
                self.operation_table,
                row,
                4,
                "yes" if operation.undoable else "no",
                color=GREEN if operation.undoable else None,
            )
            set_cell(
                self.operation_table,
                row,
                5,
                format_datetime(operation.completed_at or operation.created_at),
            )
        self.operation_hint.setText(
            f"{len(operations)} operation(s). Select an undoable row to restore the original file."
            if operations
            else "No operations recorded yet."
        )
        self._selection_changed()
        self._refresh_backups()

    def _refresh_backups(self) -> None:
        try:
            backups = self.ctx.recovery.list_backups()
        except Exception as exc:
            self.message.emit(f"Could not load backups: {exc}")
            backups = []
        self.backup_table.setRowCount(0)
        for row, backup in enumerate(backups):
            self.backup_table.insertRow(row)
            set_cell(
                self.backup_table,
                row,
                0,
                backup.path.name,
                data=str(backup.path),
                tooltip=str(backup.path),
            )
            set_cell(self.backup_table, row, 1, format_size(backup.size))
            set_cell(self.backup_table, row, 2, format_datetime(backup.created_at))
        if not backups:
            self.message.emit("No backups yet; create one before organising a large library.")

    def _selection_changed(self) -> None:
        raw = selected_data(self.operation_table)
        operation = self._operations.get(int(raw)) if raw is not None else None
        self.undo_button.setEnabled(bool(operation and operation.undoable))

    def _undo_selected(self) -> None:
        raw = selected_data(self.operation_table)
        if raw is None:
            return
        operation = self._operations.get(int(raw))
        if operation is None or not operation.undoable:
            return
        answer = QMessageBox.question(
            self,
            "Undo operation",
            f"Restore {operation.filename} to its original path?\n\n"
            f"{operation.destination_path}\n→ {operation.source_path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        operation_id = int(raw)
        self.undo_button.setEnabled(False)
        self._set_busy(True)

        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.recovery.undo(operation_id)

        self.run_task(
            work,
            label="Undo",
            on_done=self._undo_done,
            on_failed=self._undo_failed,
            on_cancelled=self._undo_cancelled,
        )

    def _undo_done(self, result: object) -> None:
        self._set_busy(False)
        message = getattr(result, "message", None) or "Operation undone."
        self.message.emit(message)
        self.refresh()
        self.library_changed.emit()

    def _undo_failed(self, error: str) -> None:
        self._set_busy(False)
        self.message.emit(f"Undo failed: {error}")
        QMessageBox.critical(self, "Undo failed", error)
        self.refresh()

    def _undo_cancelled(self) -> None:
        self._set_busy(False)
        self.message.emit("Undo cancelled.")
        self.refresh()

    def _create_backup(self) -> None:
        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.recovery.backup()

        self._set_busy(True)
        self.run_task(
            work,
            label="Backup",
            on_done=self._backup_done,
            on_failed=self._backup_failed,
        )

    def _backup_done(self, path: object) -> None:
        self._set_busy(False)
        self.message.emit(f"Backup written to {path}.")
        self._refresh_backups()

    def _backup_failed(self, error: str) -> None:
        self._set_busy(False)
        self.message.emit(f"Backup failed: {error}")

    def _restore_backup(self) -> None:
        raw = selected_data(self.backup_table)
        if raw is None:
            QMessageBox.information(self, "Choose a backup", "Select a backup file first.")
            return
        backup = Path(str(raw))
        answer = QMessageBox.warning(
            self,
            "Restore database",
            f"Replace the live database with {backup.name}?\n\n"
            "OpenCoeus must be restarted afterwards. Any changes made since the backup "
            "will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        window = self.window()
        if window is not None and hasattr(window, "stop_for_restore"):
            window.stop_for_restore()

        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.recovery.restore(backup)

        def done(_result: object) -> None:
            self._set_busy(False)
            QMessageBox.information(
                self,
                "Restore complete",
                "The database was replaced. Close and reopen OpenCoeus before doing anything else.",
            )
            self.message.emit("Database restored; restart OpenCoeus to continue.")
            if window is not None and hasattr(window, "close"):
                window.close()

        def failed(error: str) -> None:
            self._set_busy(False)
            if window is not None and hasattr(window, "setEnabled"):
                window.setEnabled(True)
            QMessageBox.critical(self, "Restore failed", error)

        self._set_busy(True)
        self.run_task(work, label="Restore", on_done=done, on_failed=failed)

    def _reveal_backup(self) -> None:
        raw = selected_data(self.backup_table)
        if raw:
            reveal_in_folder(Path(str(raw)))

    def _show_backup_folder(self) -> None:
        reveal_in_folder(self.ctx.config.backup_dir)

    def _integrity_check(self) -> None:
        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.recovery.integrity_check()

        def done(ok: object) -> None:
            self._set_busy(False)
            self._maintenance_text(
                "Database integrity check passed." if ok else "Integrity check FAILED.",
                GREEN if ok else RED,
            )

        def failed(error: str) -> None:
            self._set_busy(False)
            self._maintenance_text(f"Integrity check failed: {error}", RED)

        self._set_busy(True)
        self.run_task(
            work, label="Integrity check", on_done=done, on_failed=failed
        )

    def _rebuild_index(self) -> None:
        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.recovery.rebuild_search_index()

        def done(count: object) -> None:
            self._set_busy(False)
            self._maintenance_text(f"Search index rebuilt for {count} file(s).", GREEN)

        self._set_busy(True)
        self._maintenance_text("Rebuilding the search index…", None)
        self.run_task(work, label="Index rebuild", on_done=done, on_failed=self._index_failed)

    def _index_failed(self, error: str) -> None:
        self._set_busy(False)
        self.message.emit(f"Index rebuild failed: {error}")
        self._maintenance_text(f"Index rebuild failed: {error}", RED)

    def _vacuum(self) -> None:
        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.recovery.vacuum()

        def done(_result: object) -> None:
            self._set_busy(False)
            self._maintenance_text("Database compacted; unused pages were reclaimed.", GREEN)

        def failed(error: str) -> None:
            self._set_busy(False)
            self._maintenance_text(f"Compaction failed: {error}", RED)

        self._set_busy(True)
        self.run_task(work, label="Compaction", on_done=done, on_failed=failed)

    def _maintenance_text(self, text: str, colour: str | None) -> None:
        self.maintenance_output.setText(text)
        self.maintenance_output.setStyleSheet(f"color: {colour or MUTED};")
        self.message.emit(text)


__all__ = ["HistoryPage"]
