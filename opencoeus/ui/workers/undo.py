from __future__ import annotations
from PyQt6.QtCore import QThread, pyqtSignal
from ...database import AuditStore


class UndoWorker(QThread):
    finished_undo = pyqtSignal(object)
    message = pyqtSignal(str)

    def __init__(self, batch_id: int, store: AuditStore) -> None:
        super().__init__()
        self.batch_id = batch_id
        self.store = store

    def run(self) -> None:
        try:
            from ...executor import undo_batch
            errors = undo_batch(self.batch_id, self.store, lambda msg: self.message.emit(str(msg)))
            self.finished_undo.emit(errors)
        except Exception as exc:
            self.finished_undo.emit([f"Undo crashed: {exc}"])
