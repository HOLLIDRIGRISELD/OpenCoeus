"""Cross-process advisory lock for state shared by GUI and CLI processes."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.exceptions import OperationConflictError

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - non-Windows hosts
    import fcntl

DATA_LOCK_NAME = "organisation.lock"


class ProcessLock:
    """Non-blocking advisory lock backed by one byte in a shared file."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the lock for the duration of the context, or fail immediately."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                self._acquire(handle.fileno())
            except OSError as exc:
                raise OperationConflictError(
                    "Another OpenCoeus process is using this data. Wait and try again.",
                    user_message="Another OpenCoeus process is using this data. Wait and try again.",
                ) from exc
            try:
                yield
            finally:
                self._release(handle.fileno())

    @staticmethod
    def _acquire(file_descriptor: int) -> None:
        if os.name == "nt":
            msvcrt.locking(file_descriptor, msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - non-Windows hosts
            fcntl.flock(file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release(file_descriptor: int) -> None:
        if os.name == "nt":
            msvcrt.locking(file_descriptor, msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - non-Windows hosts
            fcntl.flock(file_descriptor, fcntl.LOCK_UN)


__all__ = ["DATA_LOCK_NAME", "ProcessLock"]
