"""Background workers.

All long-running work (scanning, analysis, semantic search, execution) runs in a
``QThreadPool``. The worker only emits signals; widgets update on the GUI thread.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.core.progress import CancellationToken, OperationCancelled

TaskFunction = Callable[[Callable[[Any], None], CancellationToken], Any]


class WorkerSignals(QObject):
    """Signals emitted by :class:`Task`."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class Task(QRunnable):
    """Run ``fn(progress, cancel)`` off the GUI thread."""

    def __init__(self, fn: TaskFunction, *, label: str = "task") -> None:
        super().__init__()
        self.fn = fn
        self.label = label
        self.signals = WorkerSignals()
        self._token = CancellationToken()
        self.setAutoDelete(True)

    def cancel(self) -> None:
        self._token.cancel(wait=False)

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    @Slot()
    def run(self) -> None:  # pragma: no cover - requires a Qt event loop
        try:
            result = self.fn(self.signals.progress.emit, self._token)
        except OperationCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            traceback.print_exc()
            self.signals.failed.emit(str(exc))
        else:
            self.signals.finished.emit(result)


__all__ = ["Task", "TaskFunction", "WorkerSignals"]
