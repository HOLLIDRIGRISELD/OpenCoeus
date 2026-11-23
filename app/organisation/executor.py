"""Executes approved plans with verification, logging and no overwrites.

Execution is deliberately sequential and observable. For every action the
executor re-validates the source and destination, records a pending operation in
the database, moves the file, verifies size/hash, updates the file identity and
search index, and finally marks the operation complete. A failure leaves the
file at a known location and is logged with its reason.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from app.core.exceptions import FileAccessError
from app.core.logging_config import get_logger
from app.core.progress import CancellationToken, ProgressCallback, ProgressEvent
from app.domain.enums import ActionType
from app.domain.models import OperationResult, PlannedAction
from app.infrastructure.repositories.files import FileRepository
from app.infrastructure.repositories.operations import OperationRepository
from app.organisation.fsops import move_no_overwrite, verify_destination
from app.organisation.validator import PathGuard
from app.processing.hashing import sha256_file
from app.search.indexer import SearchIndexer

logger = get_logger(__name__)

_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def path_lock(*paths: Path) -> Iterator[None]:
    """Serialise moves and undos that touch the same source or destination."""

    keys = sorted({str(Path(path).resolve(strict=False)).lower() for path in paths})
    with _PATH_LOCKS_GUARD:
        locks = [_PATH_LOCKS.setdefault(key, threading.RLock()) for key in keys]
    with ExitStack() as stack:
        for lock in locks:
            stack.enter_context(lock)
        yield


@dataclass(slots=True)
class ExecutionReport:
    """Outcome of executing a plan."""

    plan_id: int | None = None
    completed: list[OperationResult] = field(default_factory=list)
    failed: list[OperationResult] = field(default_factory=list)
    skipped: list[OperationResult] = field(default_factory=list)
    created_directories: list[Path] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def total(self) -> int:
        return len(self.completed) + len(self.failed) + len(self.skipped)

    @property
    def succeeded(self) -> int:
        return len(self.completed)

    @property
    def summary(self) -> str:
        return (
            f"{len(self.completed)} completed, {len(self.failed)} failed, "
            f"{len(self.skipped)} skipped"
        )


class FileOperationExecutor:
    """Performs approved rename/move operations.

    Args:
        files: File repository used to update the canonical location.
        operations: Repository recording the append-only operation log.
        indexer: Search indexer refreshed after each successful move.
        verify_hash: Hash files before and after the move (recommended).
        max_hash_bytes: Files above this size are verified by size only.
    """

    def __init__(
        self,
        files: FileRepository,
        operations: OperationRepository,
        indexer: SearchIndexer,
        *,
        verify_hash: bool = True,
        max_hash_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self._files = files
        self._operations = operations
        self._indexer = indexer
        self.verify_hash = verify_hash
        self.max_hash_bytes = max_hash_bytes

    def execute(
        self,
        root: Path,
        actions: list[PlannedAction],
        *,
        plan_id: int | None = None,
        progress: ProgressCallback | None = None,
        cancel: CancellationToken | None = None,
        sources: dict[int, Path] | None = None,
    ) -> ExecutionReport:
        report = ExecutionReport(plan_id=plan_id)
        started = time.perf_counter()
        guard = PathGuard(root)
        total = len(actions)

        for index, action in enumerate(actions, start=1):
            if cancel is not None:
                cancel.raise_if_cancelled()
            if progress:
                progress(
                    ProgressEvent(
                        phase="execute",
                        current=index - 1,
                        total=total,
                        message=f"Applying {action.new_name}",
                        item=str(action.source_path),
                    )
                )
            result, created = self._execute_one(action, guard, plan_id, sources)
            report.created_directories.extend(created)
            if result.success:
                report.completed.append(result)
            elif result.message and result.message.startswith("Skipped"):
                report.skipped.append(result)
            else:
                report.failed.append(result)

        report.duration_seconds = round(time.perf_counter() - started, 3)
        if progress:
            progress(
                ProgressEvent(
                    phase="execute",
                    current=total,
                    total=total,
                    message=f"Finished: {report.summary}",
                )
            )
        return report

    def _execute_one(
        self,
        action: PlannedAction,
        guard: PathGuard,
        plan_id: int | None,
        sources: dict[int, Path] | None,
    ) -> tuple[OperationResult, list[Path]]:
        source = Path(action.source_path)
        actual_source = sources.get(action.file_id, source) if sources else source
        with path_lock(actual_source, Path(action.destination_path)):
            return self._execute_unlocked(action, guard, plan_id, actual_source)

    def _execute_unlocked(
        self,
        action: PlannedAction,
        guard: PathGuard,
        plan_id: int | None,
        actual_source: Path,
    ) -> tuple[OperationResult, list[Path]]:
        source = Path(action.source_path)
        destination = Path(action.destination_path)

        if action.conflict:
            self._mark_item(action, "skipped")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    message=f"Skipped: {action.conflict}",
                    undoable=False,
                ),
                [],
            )

        if str(source) == str(destination):
            self._mark_item(action, "skipped")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    message="Skipped: no change required.",
                    undoable=False,
                ),
                [],
            )

        destination_check = guard.check_destination(destination, source=actual_source)
        if not destination_check.ok:
            self._mark_item(action, "skipped")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    message=f"Skipped: {destination_check.message}",
                    undoable=False,
                ),
                [],
            )

        source_errors = [issue for issue in guard.check_source(actual_source) if issue.is_error]
        if source_errors:
            self._mark_item(action, "failed")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    message=source_errors[0].message,
                    undoable=False,
                ),
                [],
            )

        try:
            size = actual_source.stat().st_size
            original_hash = (
                sha256_file(actual_source)
                if self.verify_hash and size <= self.max_hash_bytes
                else None
            )
        except (OSError, FileAccessError) as exc:
            self._mark_item(action, "failed")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    message=f"Could not read the source file: {exc}",
                    undoable=False,
                ),
                [],
            )

        if action.expected_hash and original_hash and original_hash != action.expected_hash:
            self._mark_item(action, "failed")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    message=f"Source changed since it was scanned: {actual_source}",
                    undoable=False,
                ),
                [],
            )

        operation_id = self._operations.record_operation(
            file_id=action.file_id,
            operation_type=action.action,
            source_path=source,
            destination_path=destination,
            original_hash=original_hash,
            plan_item_id=action.plan_item_id,
        )
        self._operations.add_event(
            operation_id,
            "plan_context",
            f"plan={plan_id}" if plan_id is not None else "manual execution",
        )

        created: list[Path] = []
        try:
            created = self._ensure_parent(destination.parent, operation_id)
            move_no_overwrite(
                actual_source,
                destination,
                expected_hash=original_hash,
                verify_copy_hash=self.verify_hash,
            )
            destination_hash = None
            ok, reason = verify_destination(destination, expected_size=size)
            if not ok:
                raise OSError(reason or "Verification failed.")
            if self.verify_hash and original_hash:
                destination_hash = sha256_file(destination)
                if destination_hash != original_hash:
                    raise OSError("Content hash changed during the move.")

            self._files.update_location(action.file_id, destination)
            try:
                self._indexer.index_file(action.file_id)
            except Exception:
                logger.exception("Could not refresh the search index for %s", destination.name)

            self._operations.complete_operation(operation_id, destination_hash=destination_hash)
            self._mark_item(action, "completed")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=True,
                    operation_id=operation_id,
                    message=f"{action.action.value.replace('_', ' ').title()}: {destination}",
                    undoable=True,
                ),
                created,
            )
        except Exception as exc:
            logger.exception("Operation %s failed: %s", operation_id, exc)
            restored = self._recover_after_failure(actual_source, destination)
            if restored:
                try:
                    self._files.update_location(action.file_id, actual_source)
                except Exception:
                    logger.exception("Could not restore the location for %s", action.new_name)
                try:
                    self._indexer.index_file(action.file_id)
                except Exception:
                    logger.exception("Could not refresh the search index for %s", action.new_name)
            self._operations.fail_operation(operation_id, str(exc))
            self._mark_item(action, "failed")
            return (
                OperationResult(
                    file_id=action.file_id,
                    action=action.action,
                    source_path=source,
                    destination_path=destination,
                    success=False,
                    operation_id=operation_id,
                    message=(
                        f"Failed: {exc}; file remains at {destination}"
                        if not restored
                        else f"Failed: {exc}"
                    ),
                    undoable=False,
                ),
                created,
            )

    def _ensure_parent(self, parent: Path, operation_id: int) -> list[Path]:
        if parent.exists():
            return []
        os.makedirs(parent, exist_ok=True)
        self._operations.add_event(
            operation_id, "created_directory", f"Created folder {parent}"
        )
        return [parent]

    @staticmethod
    def _recover_after_failure(source: Path, destination: Path) -> bool:
        """Best effort: put the file back if it was already moved."""

        if source.exists():
            return True
        if not destination.exists():
            return True
        try:
            move_no_overwrite(destination, source)
        except Exception:  # pragma: no cover - last-resort path
            logger.exception(
                "Could not restore %s after a failed operation; it remains at %s",
                source,
                destination,
            )
            return False
        return True

    def _mark_item(self, action: PlannedAction, status: str) -> None:
        if action.plan_item_id is not None:
            self._operations.set_item_status(action.plan_item_id, status)


__all__ = ["ExecutionReport", "FileOperationExecutor", "ActionType"]
