"""Shared page base class with task helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import QWidget

from app.services.context import AppContext
from app.ui.workers import Task, TaskFunction


class BasePage(QWidget):
    """A page that owns a context and can run background tasks safely."""

    message = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = context
        self._tasks: set[Task] = set()

    def refresh(self) -> None:
        """Reload data from the database. Subclasses override."""

    def has_running_tasks(self) -> bool:
        return bool(self._tasks)

    def cancel_tasks(self) -> None:
        for task in list(self._tasks):
            task.cancel()

    def run_task(
        self,
        fn: TaskFunction,
        *,
        label: str = "task",
        on_done: Callable[[Any], None] | None = None,
        on_failed: Callable[[str], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
    ) -> Task:
        task = Task(fn, label=label)
        self._tasks.add(task)

        def finish(result: object) -> None:
            self._tasks.discard(task)
            if on_done is not None:
                on_done(result)
            else:
                self.message.emit(f"{label} finished.")

        def fail(error: str) -> None:
            self._tasks.discard(task)
            if on_failed is not None:
                on_failed(error)
            else:
                self.message.emit(f"{label} failed: {error}")

        def cancel() -> None:
            self._tasks.discard(task)
            if on_cancelled is not None:
                on_cancelled()
            else:
                self.message.emit(f"{label} cancelled.")

        task.signals.finished.connect(finish)
        task.signals.failed.connect(fail)
        task.signals.cancelled.connect(cancel)
        if on_progress is not None:
            task.signals.progress.connect(on_progress)
        QThreadPool.globalInstance().start(task)
        return task


__all__ = ["BasePage"]
