from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from opencoeus.db import AuditStore
from opencoeus.executor import undo_batch
from opencoeus.journal import prepare_execution, undo_last_batch
from opencoeus.rules.engine import RuleMatch


class _ExecutionWorker(QThread):
    message = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, batch_id: int, store: AuditStore,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._batch_id = batch_id
        self._store = store

    def run(self) -> None:
        try:
            from opencoeus.journal import run_execution
            result = run_execution(self._batch_id, self._store, self.message.emit)
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class _UndoWorker(QThread):
    message = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, batch_id: int, store: AuditStore,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._batch_id = batch_id
        self._store = store

    def run(self) -> None:
        try:
            errors = undo_batch(self._batch_id, self._store, self.message.emit)
            self.done.emit(errors)
        except Exception as e:
            self.failed.emit(str(e))


class _ApproveWorker(QThread):
    done = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, action_ids: list[int], store: AuditStore,
                 approve: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._action_ids = action_ids
        self._store = store
        self._approve = approve

    def run(self) -> None:
        try:
            if self._approve:
                count = self._store.approve_actions(self._action_ids)
            else:
                count = self._store.reject_actions(self._action_ids)
            self.done.emit(count)
        except Exception as e:
            self.failed.emit(str(e))


class _ApproveAllWorker(QThread):
    done = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, profile_id: int, store: AuditStore,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._profile_id = profile_id
        self._store = store

    def run(self) -> None:
        try:
            count = self._store.approve_all_actions(self._profile_id)
            self.done.emit(count)
        except Exception as e:
            self.failed.emit(str(e))


class ActionController(QObject):
    log_message = pyqtSignal(str)
    actions_saved = pyqtSignal(list)
    approval_done = pyqtSignal(int)
    preparation_done = pyqtSignal(int, int)
    execution_done = pyqtSignal(object)
    undo_done = pyqtSignal(object)
    operation_failed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, store: AuditStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._worker: QThread | None = None

    def _profile_id(self) -> int:
        profiles = self._store.list_profiles()
        if profiles:
            return profiles[0].id
        from opencoeus.profiles import create_profile
        p = create_profile(self._store, "default")
        return p.profile_id

    def save_actions(self, matches: list[RuleMatch]) -> list:
        pid = self._profile_id()
        actions = [
            {
                "original_path": m.original_path,
                "proposed_path": m.proposed_path,
                "action_type": m.action_type,
                "rule_id": m.rule_id or 0,
                "reason": m.reason,
                "original_filename": m.original_filename or "",
                "new_filename": m.new_filename or "",
            }
            for m in matches
        ]
        self._store.save_proposed_actions(pid, actions)
        result = self._store.get_proposed_actions(pid)
        self.actions_saved.emit(result)
        return result

    def _wire_worker_signals(self, worker: QThread) -> None:
        worker.done.connect(self._on_worker_done)
        worker.done.connect(lambda: self.busy_changed.emit(False))
        worker.failed.connect(lambda e: self.operation_failed.emit(e))
        worker.failed.connect(lambda: self.busy_changed.emit(False))
        worker.failed.connect(self._on_worker_done)
        worker.finished.connect(worker.deleteLater)

    def approve_selected(self, action_ids: list[int]) -> None:
        if not action_ids:
            return
        self._cancel()
        self.busy_changed.emit(True)
        worker = _ApproveWorker(action_ids, self._store, approve=True, parent=self)
        worker.done.connect(lambda c: self.approval_done.emit(c))
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def reject_selected(self, action_ids: list[int]) -> None:
        if not action_ids:
            return
        self._cancel()
        self.busy_changed.emit(True)
        worker = _ApproveWorker(action_ids, self._store, approve=False, parent=self)
        worker.done.connect(lambda c: self.approval_done.emit(c))
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def approve_all(self) -> None:
        self._cancel()
        self.busy_changed.emit(True)
        worker = _ApproveAllWorker(self._profile_id(), self._store, parent=self)
        worker.done.connect(lambda c: self.approval_done.emit(c))
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def prepare_and_execute(self) -> None:
        self._cancel()
        self.busy_changed.emit(True)
        batch_id, count = prepare_execution(self._store, self._profile_id(), "Batch from UI")
        self.preparation_done.emit(batch_id, count)
        self._run_execution(batch_id)

    def _run_execution(self, batch_id: int) -> None:
        worker = _ExecutionWorker(batch_id, self._store, self)
        worker.message.connect(self.log_message)
        worker.done.connect(lambda r: self.execution_done.emit(r))
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def undo_last(self) -> None:
        self._cancel()
        batch_id, errors = undo_last_batch(self._store, None)
        if batch_id is None:
            self.operation_failed.emit("No completed batches to undo")
            return
        self.busy_changed.emit(True)
        worker = _UndoWorker(batch_id, self._store, self)
        worker.message.connect(self.log_message)
        worker.done.connect(lambda e: self.undo_done.emit(e))
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def get_batches(self, limit: int = 20):
        return self._store.get_all_batches(None, limit)

    def _on_worker_done(self, *args) -> None:
        worker = self.sender()
        if worker and self._worker is worker:
            self._worker = None

    def cancel(self) -> None:
        self._cancel()

    def _cancel(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.quit()
            if not worker.wait(3000):
                worker.finished.connect(worker.deleteLater)
