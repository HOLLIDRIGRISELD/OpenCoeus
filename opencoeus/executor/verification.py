from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from ..core.hashing import sha256_file
from ..db import AuditStore, EntryStatus

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_TRAILING_DOT = re.compile(r"[ .]+$")


def resolve_collision(destination: Path) -> Path:
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


def safe_move(source: Path, destination: Path) -> Path:
    actual_destination = resolve_collision(destination)
    actual_destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(source, actual_destination)
        return actual_destination
    except OSError:
        pass
    max_retries = 3
    for attempt in range(max_retries):
        try:
            shutil.copy2(source, actual_destination)
            source.unlink()
            if actual_destination.exists():
                return actual_destination
            raise OSError("Destination missing after move")
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise
        except OSError:
            if actual_destination.exists() and source.exists():
                try:
                    actual_destination.unlink()
                except OSError:
                    pass
            raise


def verify_file_integrity(file_path: Path, expected_hash: str, expected_size: int) -> tuple[str | None, str]:
    if not file_path.exists():
        return (f"File not found: {file_path}", "")
    actual_size = file_path.stat().st_size
    if actual_size != expected_size:
        return (f"Size mismatch: expected {expected_size}, got {actual_size} for {file_path}", "")
    actual_hash = sha256_file(file_path) if expected_hash else ""
    if expected_hash and actual_hash != expected_hash:
        return (f"Hash mismatch: expected {expected_hash[:12]}..., got {actual_hash[:12]}... for {file_path}", actual_hash)
    return (None, actual_hash)


def pre_execution_check(
    entries, store: AuditStore,
) -> tuple[list, list[str]]:
    passing: list = []
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
        destination = Path(entry.destination_path)
        if not _is_valid_destination(destination):
            store.update_entry(
                entry.id,
                status=EntryStatus.FAILED,
                error_message=f"Invalid destination filename: {destination.name}",
            )
            errors.append(f"Invalid destination filename for {entry.source_path}")
            continue
        passing.append(entry)
    return passing, errors


def _is_valid_destination(destination: Path) -> bool:
    name = destination.name
    if not name or name in {".", ".."}:
        return False
    if _INVALID_CHARS.search(name):
        return False
    if _TRAILING_DOT.search(name):
        return False
    return True
