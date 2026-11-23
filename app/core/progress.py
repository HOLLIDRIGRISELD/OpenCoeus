"""Shared progress, cancellation and reporting primitives.

Long-running work (scanning, analysis, execution) runs off the UI thread but
must report progress back to it. These objects live in ``app.core`` so that the
organisation and service layers can use them without depending on the UI.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class ProgressEvent:
    """One progress notification.

    Args:
        phase: Pipeline stage, e.g. ``scan``, ``analyse`` or ``execute``.
        current: Number of completed units.
        total: Total units, or ``0`` when unknown.
        message: Short human-readable description.
        item: Filename or path currently being processed.
    """

    phase: str
    current: int = 0
    total: int = 0
    message: str = ""
    item: str | None = None

    @property
    def percent(self) -> int | None:
        if self.total <= 0:
            return None
        return max(0, min(100, round(self.current * 100 / self.total)))


ProgressCallback = Callable[[ProgressEvent], None]


class OperationCancelled(Exception):
    """Raised when the user cancels a running pipeline."""


class CancellationToken:
    """Cooperative cancellation shared between the UI and a worker thread."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._running = threading.Event()
        self._finished = threading.Event()

    def begin(self) -> None:
        """Mark a worker as running so ``cancel`` waits for it to finish."""

        self._running.set()
        self._finished.clear()

    def finish(self) -> None:
        """Signal that the registered worker has stopped."""

        self._finished.set()

    def cancel(self, *, wait: bool = True, timeout: float | None = None) -> None:
        self._event.set()
        if wait and self._running.is_set():
            self._finished.wait(timeout)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def event(self) -> threading.Event:
        """Underlying event, for APIs that accept one directly."""

        return self._event

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled


def emit(
    callback: ProgressCallback | None,
    phase: str,
    current: int,
    total: int,
    message: str,
    item: str | None = None,
) -> None:
    """Send a progress event when a callback is registered."""

    if callback is None:
        return
    callback(
        ProgressEvent(
            phase=phase,
            current=current,
            total=total,
            message=message,
            item=item,
        )
    )
