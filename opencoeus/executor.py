from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import default_application_data_directory
from .database import AuditStore
from .hashing import sha256_file
from .models import BatchStatus, EntryStatus, TransactionEntry


# HOLDING AREA STORED IN THE APPLICATION DATA DIRECTORY (CONSISTENT WITH DATABASE)
HOLDING_ROOT = default_application_data_directory() / "transactions"

# MODULE LEVEL LOCK TO PREVENT CONCURRENT BATCH EXECUTION
_batch_lock = threading.Lock()


@dataclass
class ExecutionResult:
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    batch_id: int | None = None


# COLLISION RESOLUTION


def resolve_collision(destination: Path) -> Path:
    """If destination exists, append (2), (3), etc. until unique."""
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 2
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# SAFE MOVE


def safe_move(source: Path, destination: Path) -> Path:
    """Atomic move with collision resolution. Returns actual destination path."""
    actual_destination = resolve_collision(destination)
    actual_destination.parent.mkdir(parents=True, exist_ok=True)
    # ATTEMPT RENAME FIRST (FAST, SAME FS)
    try:
        os.rename(source, actual_destination)
        return actual_destination
    except OSError:
        pass
    # FALLBACK TO COPY PLUS DELETE FOR CROSS FS OR LOCKED FILES
    max_retries = 3
    for attempt in range(max_retries):
        try:
            shutil.copy2(source, actual_destination)
            source.unlink()
            # VERIFY DESTINATION EXISTS AFTER COPY DELETE TO PREVENT ORPHANS
            if actual_destination.exists():
                return actual_destination
            raise OSError("Destination missing after move")
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise
        except OSError:
            # COPY SUCCEEDED BUT DELETE FAILED, CLEAN UP ORPHANED COPY
            if actual_destination.exists() and source.exists():
                try:
                    actual_destination.unlink()
                except OSError:
                    pass
            raise

# FILE INTEGRITY VERIFICATION


def verify_file_integrity(file_path: Path, expected_hash: str, expected_size: int) -> tuple[str | None, str]:
    """Re-hash a file and compare to expected values.
    Returns (error_message, actual_hash); error is None on success."""
    if not file_path.exists():
        return (f"File not found: {file_path}", "")
    actual_size = file_path.stat().st_size
    if actual_size != expected_size:
        return (f"Size mismatch: expected {expected_size}, got {actual_size} for {file_path}", "")
    actual_hash = sha256_file(file_path) if expected_hash else ""
    if expected_hash and actual_hash != expected_hash:
        return (f"Hash mismatch: expected {expected_hash[:12]}..., got {actual_hash[:12]}... for {file_path}", actual_hash)
    return (None, actual_hash)


# HOLDING AREA MANAGEMENT


def get_holding_dir(batch_id: int) -> Path:
    """Return the holding directory path for a batch."""
    return HOLDING_ROOT / str(batch_id)


def create_holding_area(batch_id: int) -> Path:
    """Create the holding directory for a batch."""
    holding_dir = get_holding_dir(batch_id)
    holding_dir.mkdir(parents=True, exist_ok=True)
    return holding_dir


def cleanup_holding_area(batch_id: int) -> None:
    """Remove the holding directory and all its contents."""
    holding_dir = get_holding_dir(batch_id)
    if holding_dir.exists():
        shutil.rmtree(holding_dir, ignore_errors=True)


# EMPTY FOLDER CLEANUP


def cleanup_empty_folders(root_path: Path, excluded_folders: set[str] | None = None) -> int:
    """Walk the directory tree bottom-up and remove empty folders.
    Skips excluded folders and the root itself.
    Returns the number of folders removed."""
    excluded = excluded_folders or set()
    removed = 0
    # USE OS WALK TOP DOWN FALSE FOR MEMORY EFFICIENT BOTTOM UP TRAVERSAL
    for dirpath, _dirnames, _filenames in os.walk(root_path, topdown=False):
        dir_path = Path(dirpath)
        if dir_path == root_path:
            continue
        if dir_path.name == ".opencoeus":
            continue
        if any(
            dir_path.as_posix().startswith(Path(ex).as_posix() + "/") or
            dir_path.as_posix() == Path(ex).as_posix()
            for ex in excluded
        ):
            continue
        # RECHECK ACTUAL CONTENTS (OS WALK DIRNAMES STALE AFTER CHILD REMOVAL)
        try:
            if not any(dir_path.iterdir()):
                dir_path.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


# PRE FLIGHT CHECKS


def pre_execution_check(
    entries: list[TransactionEntry], store: AuditStore,
) -> tuple[list[TransactionEntry], list[str]]:
    """Verify source files exist and hashes match. Marks failures in DB.
    Returns (passing_entries, errors)."""
    passing: list[TransactionEntry] = []
    errors: list[str] = []
    for entry in entries:
        source = Path(entry.source_path)
        if not source.exists():
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=f"File not found: {source}")
            errors.append(f"File not found: {entry.source_path}")
            continue
        error, _ = verify_file_integrity(source, entry.source_hash, entry.source_size)
        if error:
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=error)
            errors.append(error)
            continue
        passing.append(entry)
    return passing, errors


# CRASH RECOVERY


def recover_crashed_batches(store: AuditStore) -> int:
    """Mark batches stuck in EXECUTING status as failed; restore files from holding.
    Returns the number of recovered batches.
    Acquires the batch lock to prevent racing with concurrent execution."""
    import logging
    from sqlalchemy import select
    from .models import TransactionBatch
    logger = logging.getLogger(__name__)
    _batch_lock.acquire(blocking=True)
    try:
        recovered = 0
        with store.session_factory() as session:
            crashed = list(session.scalars(
                select(TransactionBatch).where(TransactionBatch.status == BatchStatus.EXECUTING)
            ).all())
            for batch in crashed:
                batch.status = BatchStatus.FAILED
                recovered += 1
                # RESTORE ANY ENTRIES STILL IN HOLDING BACK TO ORIGINAL SOURCE
                for entry in session.scalars(
                    select(TransactionEntry).where(
                        TransactionEntry.batch_id == batch.id,
                        TransactionEntry.status == EntryStatus.MOVED_TO_HOLDING,
                    )
                ).all():
                    holding_path = Path(entry.holding_path) if entry.holding_path else None
                    source_path = Path(entry.source_path)
                    if holding_path and holding_path.exists():
                        try:
                            safe_move(holding_path, source_path)
                            entry.status = EntryStatus.FAILED
                            entry.error_message = "Batch crashed — file restored to original location"
                            entry.holding_path = None
                            logger.info("Restored %s to %s after crash", holding_path, source_path)
                        except Exception as exc:
                            entry.status = EntryStatus.FAILED
                            entry.error_message = f"Batch crashed — file in holding at {holding_path}: {exc}"
                            logger.error("Failed to restore %s: %s", holding_path, exc)
                    else:
                        entry.status = EntryStatus.FAILED
                        entry.error_message = "Batch crashed — holding file missing"
            session.commit()
        # CLEANUP HOLDING AREAS FOR RECOVERED BATCHES (FILES ALREADY RESTORED ABOVE)
        for batch in crashed:
            cleanup_holding_area(batch.id)
        return recovered
    finally:
        _batch_lock.release()


# BATCH EXECUTION


def execute_batch(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> ExecutionResult:
    """Main execution pipeline: pre-flight, move to holding, move to destination, cleanup.
    Uses a module-level lock to prevent concurrent execution."""
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

    # PRE FLIGHT: VERIFY SOURCE FILES AND FILTER OUT FAILURES
    passing_entries, preflight_errors = pre_execution_check(pending_entries, store)
    if preflight_errors:
        result.errors.extend(preflight_errors)
        result.failed += len(preflight_errors)
        if not passing_entries:
            store.mark_batch(batch_id, BatchStatus.FAILED)
            return result

    # UPDATE BATCH STATUS TO EXECUTING
    store.mark_batch(batch_id, BatchStatus.EXECUTING)

    # CREATE HOLDING AREA
    holding_dir = create_holding_area(batch_id)

    # PHASE 1: MOVE SOURCE TO HOLDING AREA
    moved_to_holding: list[tuple[TransactionEntry, Path]] = []
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
            # ROLLBACK: RESTORE FILES ALREADY MOVED TO HOLDING
            rollback_errors = rollback_partial(moved_to_holding, store)
            if rollback_errors:
                result.errors.extend(rollback_errors)
            store.mark_batch(batch_id, BatchStatus.FAILED)
            # ONLY CLEANUP HOLDING IF ROLLBACK SUCCEEDED FOR ALL FILES
            if not rollback_errors:
                cleanup_holding_area(batch_id)
            else:
                result.errors.append("Some files remain in holding, manual cleanup may be needed")
            return result

    # PHASE 2: MOVE HOLDING TO FINAL DESTINATION
    completed_entries: list[tuple[TransactionEntry, Path]] = []
    for entry, holding_path in moved_to_holding:
        destination = Path(entry.destination_path)
        try:
            actual_dest = safe_move(holding_path, destination)
            # VERIFY FILE INTEGRITY AT DESTINATION AGAINST SOURCE HASH
            integrity_error, dest_hash = verify_file_integrity(actual_dest, entry.source_hash, entry.source_size)
            if integrity_error:
                # DESTINATION CORRUPTED, ROLLBACK THIS FILE TO ORIGINAL SOURCE
                safe_move(actual_dest, Path(entry.source_path))
                store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=f"Integrity check failed: {integrity_error}")
                result.errors.append(f"Integrity check failed for {entry.source_path}: {integrity_error}")
                result.failed += 1
                continue
            # USE THE HASH COMPUTED DURING INTEGRITY CHECK (AVOIDS SECOND HASH)
            if not dest_hash:
                dest_hash = sha256_file(actual_dest)
            store.update_entry(
                entry.id,
                status=EntryStatus.COMPLETED,
                destination_path=str(actual_dest),
                destination_hash=dest_hash,
                executed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            # MARK THE PROPOSED ACTION AS APPLIED
            if entry.action_id:
                store.approve_action(entry.action_id)
            completed_entries.append((entry, actual_dest))
            result.completed += 1
            if progress_callback:
                action_label = "Renamed" if entry.action_type == "rename" else "Completed"
                progress_callback(f"{action_label}: {source.name} -> {actual_dest.name}")
        except Exception as exc:
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=str(exc))
            result.errors.append(f"Failed to move {entry.source_path} to destination: {exc}")
            result.failed += 1
            # ROLLBACK: RESTORE REMAINING HOLDING FILES TO ORIGINAL SOURCE
            rollback_errors = rollback_remaining(moved_to_holding, completed_entries, store, failed_entry_id=entry.id)
            if rollback_errors:
                result.errors.extend(rollback_errors)
            store.mark_batch(batch_id, BatchStatus.FAILED)
            # ONLY CLEANUP HOLDING IF ROLLBACK SUCCEEDED FOR ALL FILES
            if not rollback_errors:
                cleanup_holding_area(batch_id)
            else:
                result.errors.append("Some files remain in holding, manual cleanup may be needed")
            return result

    # CLEANUP: REMOVE HOLDING AREA AND EMPTY FOLDERS
    cleanup_holding_area(batch_id)
    # DERIVE ROOT PATH FROM ENTRIES AND CLEANUP EMPTY FOLDERS LEFT BY MOVES
    if completed_entries:
        source_dirs = {Path(e.source_path).parent for e, _ in completed_entries}
        root_path = Path(os.path.commonpath([str(d) for d in source_dirs]))
        cleanup_empty_folders(root_path)
    store.mark_batch(batch_id, BatchStatus.COMPLETED, completed_at=datetime.now(UTC).replace(tzinfo=None))
    return result


def rollback_partial(
    moved: list[tuple[TransactionEntry, Path]],
    store: AuditStore,
) -> list[str]:
    """Restore files from holding back to original source (partial rollback).
    Returns a list of errors (empty if all restored)."""
    import logging
    logger = logging.getLogger(__name__)
    errors: list[str] = []
    for entry, holding_path in reversed(moved):
        source = Path(entry.source_path)
        try:
            if holding_path.exists():
                safe_move(holding_path, source)
                store.update_entry(entry.id, status=EntryStatus.PENDING, holding_path=None, error_message=None)
            else:
                errors.append(f"Holding file missing for {entry.source_path}")
                store.update_entry(entry.id, status=EntryStatus.FAILED, error_message="Holding file missing")
        except Exception as exc:
            errors.append(f"Failed to restore {holding_path} to {source}: {exc}")
            logger.error("Rollback failed for %s: %s", holding_path, exc)
    return errors


def rollback_remaining(
    all_moved: list[tuple[TransactionEntry, Path]],
    completed: list[tuple[TransactionEntry, Path]],
    store: AuditStore,
    failed_entry_id: int | None = None,
) -> list[str]:
    """Restore uncompleted holding files to original sources.
    Skips the entry that triggered the failure (already marked failed).
    Returns a list of errors (empty if all restored)."""
    import logging
    logger = logging.getLogger(__name__)
    errors: list[str] = []
    completed_ids = {e.id for e, _ in completed}
    for entry, holding_path in reversed(all_moved):
        if entry.id in completed_ids:
            continue
        source = Path(entry.source_path)
        try:
            if holding_path.exists():
                safe_move(holding_path, source)
                if entry.id != failed_entry_id:
                    store.update_entry(entry.id, status=EntryStatus.PENDING, holding_path=None, error_message=None)
            else:
                errors.append(f"Holding file missing for {entry.source_path}")
                if entry.id != failed_entry_id:
                    store.update_entry(entry.id, status=EntryStatus.FAILED, error_message="Holding file missing")
        except Exception as exc:
            errors.append(f"Failed to restore {holding_path} to {source}: {exc}")
            logger.error("Rollback failed for %s: %s", holding_path, exc)
    return errors


# UNDO


def undo_batch(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> list[str]:
    """Reverse all completed entries in a batch, newest first.
    Acquires the batch lock to prevent racing with concurrent execution."""
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
        # CLEANUP EMPTY CATEGORY FOLDERS LEFT BY UNDO
        dest_dirs = {Path(e.destination_path).parent for e in entries if e.destination_path}
        if dest_dirs:
            undo_root = Path(os.path.commonpath([str(d) for d in dest_dirs]))
            cleanup_empty_folders(undo_root)
        return errors
    finally:
        _batch_lock.release()
