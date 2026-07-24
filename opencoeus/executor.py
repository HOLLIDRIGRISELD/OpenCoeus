from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .database import AuditStore
from .hashing import sha256_file
from .models import BatchStatus, EntryStatus, TransactionEntry


HOLDING_ROOT = Path.home() / ".opencoeus" / "transactions"


@dataclass
class ExecutionResult:
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    batch_id: int | None = None


# ------------------------------------------------------------------ #
#  COLLISION RESOLUTION                                                 #
# ------------------------------------------------------------------ #


def resolve_collision(destination: Path) -> Path:
    # IF DESTINATION EXISTS, APPEND (2), (3), ETC. UNTIL UNIQUE.
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


# ------------------------------------------------------------------ #
#  SAFE MOVE                                                           #
# ------------------------------------------------------------------ #


def safe_move(source: Path, destination: Path) -> Path:
    # ATOMIC MOVE WITH COLLISION RESOLUTION. RETURNS ACTUAL DESTINATION PATH.
    actual_destination = resolve_collision(destination)
    actual_destination.parent.mkdir(parents=True, exist_ok=True)
    # ATTEMPT RENAME FIRST (FAST, SAME-FS).
    try:
        os.rename(source, actual_destination)
        return actual_destination
    except OSError:
        pass
    # FALLBACK TO COPY + DELETE FOR CROSS-FS OR LOCKED FILES.
    max_retries = 3
    for attempt in range(max_retries):
        try:
            shutil.copy2(source, actual_destination)
            source.unlink()
            return actual_destination
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise


# ------------------------------------------------------------------ #
#  FILE INTEGRITY VERIFICATION                                         #
# ------------------------------------------------------------------ #


def verify_file_integrity(file_path: Path, expected_hash: str, expected_size: int) -> str | None:
    # RE-HASHES A FILE AND COMPARES TO EXPECTED VALUES. RETURNS ERROR MESSAGE OR NONE.
    if not file_path.exists():
        return f"File not found: {file_path}"
    actual_size = file_path.stat().st_size
    if actual_size != expected_size:
        return f"Size mismatch: expected {expected_size}, got {actual_size} for {file_path}"
    if expected_hash:
        actual_hash = sha256_file(file_path)
        if actual_hash != expected_hash:
            return f"Hash mismatch: expected {expected_hash[:12]}..., got {actual_hash[:12]}... for {file_path}"
    return None


# ------------------------------------------------------------------ #
#  HOLDING AREA MANAGEMENT                                             #
# ------------------------------------------------------------------ #


def get_holding_dir(batch_id: int) -> Path:
    # RETURNS THE HOLDING DIRECTORY PATH FOR A BATCH.
    return HOLDING_ROOT / str(batch_id)


def create_holding_area(batch_id: int) -> Path:
    # CREATES THE HOLDING DIRECTORY FOR A BATCH.
    holding_dir = get_holding_dir(batch_id)
    holding_dir.mkdir(parents=True, exist_ok=True)
    return holding_dir


def cleanup_holding_area(batch_id: int) -> None:
    # REMOVES THE HOLDING DIRECTORY AND ALL ITS CONTENTS.
    holding_dir = get_holding_dir(batch_id)
    if holding_dir.exists():
        shutil.rmtree(holding_dir, ignore_errors=True)


# ------------------------------------------------------------------ #
#  EMPTY FOLDER CLEANUP                                                #
# ------------------------------------------------------------------ #


def cleanup_empty_folders(root_path: Path, excluded_folders: set[str] | None = None) -> int:
    # WALKS THE DIRECTORY TREE BOTTOM-UP AND REMOVES EMPTY FOLDERS.
    # SKIPS EXCLUDED FOLDERS (node_modules, venv, .git, etc.) AND THE ROOT ITSELF.
    # RETURNS THE NUMBER OF FOLDERS REMOVED.
    excluded = excluded_folders or set()
    removed = 0
    # SORT BY DEPTH DESCENDING (BOTTOM-UP) SO CHILDREN ARE CHECKED BEFORE PARENTS.
    all_dirs = sorted(root_path.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    for dir_path in all_dirs:
        if not dir_path.is_dir():
            continue
        if dir_path == root_path:
            continue
        if dir_path.name == ".opencoeus":
            continue
        if any(dir_path.as_posix().startswith(Path(ex).as_posix()) for ex in excluded):
            continue
        try:
            if not any(dir_path.iterdir()):
                dir_path.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


# ------------------------------------------------------------------ #
#  PRE-FLIGHT CHECKS                                                    #
# ------------------------------------------------------------------ #


def pre_execution_check(entries: list[TransactionEntry]) -> list[str]:
    # VERIFIES ALL SOURCE FILES STILL EXIST AND HASHES MATCH. RETURNS ERRORS.
    errors: list[str] = []
    for entry in entries:
        source = Path(entry.source_path)
        if not source.exists():
            errors.append(f"File not found: {entry.source_path}")
            continue
        error = verify_file_integrity(source, entry.source_hash, entry.source_size)
        if error:
            errors.append(error)
    return errors


# ------------------------------------------------------------------ #
#  BATCH EXECUTION                                                     #
# ------------------------------------------------------------------ #


def execute_batch(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> ExecutionResult:
    # MAIN EXECUTION PIPELINE: PRE-FLIGHT, MOVE TO HOLDING, MOVE TO DESTINATION, CLEANUP.
    result = ExecutionResult(batch_id=batch_id)
    entries = store.get_entries_by_batch(batch_id)
    pending_entries = [e for e in entries if e.status == EntryStatus.PENDING]
    result.total = len(pending_entries)
    if not pending_entries:
        result.skipped = len(entries) - len(pending_entries)
        return result

    # PRE-FLIGHT: VERIFY SOURCE FILES.
    errors = pre_execution_check(pending_entries)
    if errors:
        for error in errors:
            result.errors.append(error)
            result.failed += 1
            result.total -= 1
        if result.failed == result.total:
            store.mark_batch(batch_id, BatchStatus.FAILED)
            return result

    # UPDATE BATCH STATUS TO EXECUTING.
    store.mark_batch(batch_id, BatchStatus.EXECUTING)

    # CREATE HOLDING AREA.
    holding_dir = create_holding_area(batch_id)

    # PHASE 1: MOVE SOURCE → HOLDING AREA.
    moved_to_holding: list[tuple[TransactionEntry, Path]] = []
    for entry in pending_entries:
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
                progress_callback(f"Moved to holding: {source.name}")
        except Exception as exc:
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=str(exc))
            result.errors.append(f"Failed to move {source.name} to holding: {exc}")
            result.failed += 1
            # ROLLBACK: RESTORE FILES ALREADY MOVED TO HOLDING.
            rollback_partial(moved_to_holding, store)
            store.mark_batch(batch_id, BatchStatus.FAILED)
            cleanup_holding_area(batch_id)
            return result

    # PHASE 2: MOVE HOLDING → FINAL DESTINATION.
    completed_entries: list[tuple[TransactionEntry, Path]] = []
    for entry, holding_path in moved_to_holding:
        destination = Path(entry.destination_path)
        try:
            actual_dest = safe_move(holding_path, destination)
            # HASH AT DESTINATION.
            dest_hash = sha256_file(actual_dest)
            store.update_entry(
                entry.id,
                status=EntryStatus.COMPLETED,
                destination_path=str(actual_dest),
                destination_hash=dest_hash,
                executed_at=datetime.now(UTC).replace(tzinfo=None),
            )
            # MARK THE PROPOSED ACTION AS APPLIED.
            if entry.action_id:
                store.approve_action(entry.action_id)  # REUSE: MARKS APPLIED VIA BATCH
            completed_entries.append((entry, actual_dest))
            result.completed += 1
            if progress_callback:
                progress_callback(f"Completed: {actual_dest.name}")
        except Exception as exc:
            store.update_entry(entry.id, status=EntryStatus.FAILED, error_message=str(exc))
            result.errors.append(f"Failed to move {entry.source_path} to destination: {exc}")
            result.failed += 1
            # ROLLBACK: RESTORE REMAINING HOLDING FILES TO ORIGINAL SOURCE.
            rollback_remaining(moved_to_holding, completed_entries, store)
            store.mark_batch(batch_id, BatchStatus.FAILED)
            cleanup_holding_area(batch_id)
            return result

    # CLEANUP: REMOVE HOLDING AREA AND EMPTY FOLDERS.
    cleanup_holding_area(batch_id)
    # DERIVE ROOT PATH FROM ENTRIES AND CLEANUP EMPTY FOLDERS LEFT BY MOVES.
    if completed_entries:
        source_dirs = {Path(e.source_path).parent for e, _ in completed_entries}
        # USE THE DEEPEST COMMON ANCESTOR AS ROOT.
        root_path = Path(os.path.commonpath([str(d) for d in source_dirs]))
        cleanup_empty_folders(root_path)
    store.mark_batch(batch_id, BatchStatus.COMPLETED, completed_at=datetime.now(UTC).replace(tzinfo=None))
    return result


def rollback_partial(
    moved: list[tuple[TransactionEntry, Path]],
    store: AuditStore,
) -> None:
    # RESTORES FILES FROM HOLDING BACK TO ORIGINAL SOURCE (PARTIAL ROLLBACK).
    for entry, holding_path in reversed(moved):
        source = Path(entry.source_path)
        try:
            if holding_path.exists():
                safe_move(holding_path, source)
                store.update_entry(entry.id, status=EntryStatus.PENDING, holding_path=None, error_message=None)
        except Exception:
            pass


def rollback_remaining(
    all_moved: list[tuple[TransactionEntry, Path]],
    completed: list[tuple[TransactionEntry, Path]],
    store: AuditStore,
) -> None:
    # RESTORES UNCOMPLETED HOLDING FILES TO ORIGINAL SOURCES.
    completed_ids = {e.id for e, _ in completed}
    for entry, holding_path in reversed(all_moved):
        if entry.id in completed_ids:
            continue
        source = Path(entry.source_path)
        try:
            if holding_path.exists():
                safe_move(holding_path, source)
                store.update_entry(entry.id, status=EntryStatus.PENDING, holding_path=None, error_message=None)
        except Exception:
            pass


# ------------------------------------------------------------------ #
#  UNDO                                                                #
# ------------------------------------------------------------------ #


def undo_batch(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> list[str]:
    # REVERSES ALL COMPLETED ENTRIES IN A BATCH, NEWEST FIRST.
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
    # CLEANUP EMPTY CATEGORY FOLDERS LEFT BY UNDO.
    dest_dirs = {Path(e.destination_path).parent for e in entries if e.destination_path}
    if dest_dirs:
        undo_root = Path(os.path.commonpath([str(d) for d in dest_dirs]))
        cleanup_empty_folders(undo_root)
    return errors
