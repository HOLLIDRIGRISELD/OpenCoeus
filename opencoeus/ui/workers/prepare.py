from __future__ import annotations
from PyQt6.QtCore import QThread, pyqtSignal
from ...database import AuditStore


class PrepareWorker(QThread):
    finished_preparation = pyqtSignal(int, int)
    failed = pyqtSignal(str)

    def __init__(self, store: AuditStore, profile_id: int, description: str) -> None:
        super().__init__()
        self.store = store
        self.profile_id = profile_id
        self.description = description

    def run(self) -> None:
        try:
            from ...journal import prepare_execution
            batch_id, count = prepare_execution(self.store, self.profile_id, self.description)
            self.finished_preparation.emit(batch_id, count)
        except Exception as exc:
            self.failed.emit(str(exc))
