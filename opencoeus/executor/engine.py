from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from ..db import AuditStore, BatchStatus, EntryStatus
from ..core.hashing import sha256_file
from .holding import cleanup_empty_folders, cleanup_holding_area, create_holding_area
from .rollback import rollback_partial, rollback_remaining
from .types import _batch_lock, ExecutionResult
from .verification import pre_execution_check, safe_move, verify_file_integrity

logger = logging.getLogger(__name__)


def execute_batch(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> ExecutionResult:
    if not _batch_lock.acquire(blocking=False):
        return ExecutionResult(
            batch_id=batch_id,
            errors=["Another batch is already executing"],
        )
    try:
        return _execute_batch_inner(batch_id, store, progress_callback)
    finally:
        _batch_lock.release()


def _execute_batch_inner(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> ExecutionResult:
    result = ExecutionResult(batch_id=batch_id)
    entries = store.get_entries_by_batch(batch_id)
    pending_entries = [e for e in entries if e.status == EntryStatus.PENDING]
    result.total = len(pending_entries)
    if not pending_entries:
        result.skipped = len(entries) - len(pending_entries)
        return result

    passing_entries, preflight_errors = pre_execution_check(pending_entries, store)
    if preflight_errors:
        result.errors.extend(preflight_errors)
        result.failed += len(preflight_errors)
        if not passing_entries:
            store.mark_batch(batch_id, BatchStatus.FAILED)
            return result

    store.mark_batch(batch_id, BatchStatus.EXECUTING)

    holding_dir = create_holding_area(batch_id)

    moved_to_holding: list[tuple] = []
    for entry in passing_entries:
        source = Path(entry.source_path)
        if not source.exists():
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=f"File not found: {entry.source_path}")
            result.failed += 1
            continue
        try:
            actual_dest = safe_move(source, holding_dir / source.name)
            store.update_entry(entry.id, status=EntryStatus.MOVED_TO_HOLDING, holding_path=str(actual_dest))
            moved_to_holding.append((entry, actual_dest))
            if progress_callback:
                action_label = "Renamed" if entry.action_type == "rename" else "Moved"
                progress_callback(f"{action_label} to holding: {source.name}")
        except Exception as exc:
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=str(exc))
            result.errors.append(f"Failed to move {source.name} to holding: {exc}")
            result.failed += 1
            rollback_errors = rollback_partial(moved_to_holding, store)
            if rollback_errors:
                result.errors.extend(rollback_errors)
            store.mark_batch(batch_id, BatchStatus.FAILED)
            if not rollback_errors:
                cleanup_holding_area(batch_id)
            else:
                result.errors.append("Some files remain in holding, manual cleanup may be needed")
            return result

    completed_entries: list[tuple] = []
    for entry, holding_path in moved_to_holding:
        destination = Path(entry.destination_path)
        try:
            actual_dest = safe_move(holding_path, destination)
            integrity_error, dest_hash = verify_file_integrity(actual_dest, entry.source_hash, entry.source_size)
            if integrity_error:
                safe_move(actual_dest, Path(entry.source_path))
                store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=f"Integrity check failed: {integrity_error}")
                result.errors.append(f"Integrity check failed for {entry.source_path}: {integrity_error}")
                result.failed += 1
                continue
            if not dest_hash:
                dest_hash = sha256_file(actual_dest)
            store.update_entry(
                entry.id,
                status=EntryStatus.COMPLETED,
                destination_path=str(actual_dest),
                destination_hash=dest_hash,
                executed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            if entry.action_id:
                store.approve_action(entry.action_id)
            completed_entries.append((entry, actual_dest))
            result.completed += 1
            if progress_callback:
                action_label = "Renamed" if entry.action_type == "rename" else "Completed"
                progress_callback(f"{action_label}: {Path(entry.source_path).name} -> {actual_dest.name}")
        except Exception as exc:
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=str(exc))
            result.errors.append(f"Failed to move {entry.source_path} to destination: {exc}")
            result.failed += 1
            rollback_errors = rollback_remaining(moved_to_holding, completed_entries, store, failed_entry_id=entry.id)
            if rollback_errors:
                result.errors.extend(rollback_errors)
            store.mark_batch(batch_id, BatchStatus.FAILED)
            if not rollback_errors:
                cleanup_holding_area(batch_id)
            else:
                result.errors.append("Some files remain in holding, manual cleanup may be needed")
            return result

    cleanup_holding_area(batch_id)
    if completed_entries:
        source_dirs = {Path(e.source_path).parent for e, _ in completed_entries}
        root_path = Path(os.path.commonpath([str(d) for d in source_dirs]))
        cleanup_empty_folders(root_path)
    store.mark_batch(batch_id, BatchStatus.COMPLETED, completed_at=datetime.now(UTC).replace(tzinfo=None))
    return result


def undo_batch(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> list[str]:
    if not _batch_lock.acquire(blocking=True):
        return ["Another batch operation is in progress"]
    try:
        errors: list[str] = []
        entries = store.get_entries_by_batch(batch_id, status=EntryStatus.COMPLETED)
        if not entries:
            return ["No completed entries to undo"]

        for entry in reversed(entries):
            destination = Path(entry.destination_path)
            source = Path(entry.source_path)
            if not destination.exists():
                errors.append(f"Destination file missing: {entry.destination_path}")
                store.update_entry(entry.id, status=EntryStatus.UNDONE, error_message="Destination missing")
                continue
            try:
                safe_move(destination, source)
                store.update_entry(entry.id, status=EntryStatus.UNDONE)
                if progress_callback:
                    progress_callback(f"Undone: {destination.name}")
            except Exception as exc:
                errors.append(f"Failed to undo {entry.destination_path}: {exc}")
                store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=str(exc))

        store.mark_batch(batch_id, BatchStatus.UNDONE, undone_at=datetime.now(UTC).replace(tzinfo=None))
        cleanup_holding_area(batch_id)
        dest_dirs = {Path(e.destination_path).parent for e in entries if e.destination_path}
        if dest_dirs:
            undo_root = Path(os.path.commonpath([str(d) for d in dest_dirs]))
            cleanup_empty_folders(undo_root)
        return errors
    finally:
        _batch_lock.release()
