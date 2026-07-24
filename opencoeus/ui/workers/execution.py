from __future__ import annotations
from PyQt6.QtCore import QThread, pyqtSignal
from ...database import AuditStore
from ...executor import ExecutionResult


class ExecutionWorker(QThread):
    finished_execution = pyqtSignal(object)
    message = pyqtSignal(str)

    def __init__(self, batch_id: int, store: AuditStore) -> None:
        super().__init__()
        self.batch_id = batch_id
        self.store = store

    def run(self) -> None:
        try:
            from ...journal import run_execution
            result = run_execution(self.batch_id, self.store, lambda msg: self.message.emit(str(msg)))
            self.finished_execution.emit(result)
        except Exception as exc:
            result = ExecutionResult.__new__(ExecutionResult)
            result.total = 0
            result.completed = 0
            result.failed = 1
            result.skipped = 0
            result.errors = [f"Execution crashed: {exc}"]
            result.batch_id = self.batch_id
            self.finished_execution.emit(result)
