from __future__ import annotations

import os
import shutil
from pathlib import Path

_RESERVED_FOLDER_NAMES = frozenset({".opencoeus", "db", "logs", "cache"})


def get_holding_dir(batch_id: int) -> Path:
    # RESOLVED LAZILY SO THAT MONKEYPATCHING opencoeus.executor.HOLDING_ROOT
    # IN TESTS AFFECTS ALL HOLDING OPERATIONS.
    import opencoeus.executor as executor_mod
    return executor_mod.HOLDING_ROOT / str(batch_id)


def create_holding_area(batch_id: int) -> Path:
    holding_dir = get_holding_dir(batch_id)
    holding_dir.mkdir(parents=True, exist_ok=True)
    return holding_dir


def cleanup_holding_area(batch_id: int) -> None:
    holding_dir = get_holding_dir(batch_id)
    if holding_dir.exists():
        shutil.rmtree(holding_dir, ignore_errors=True)


def cleanup_stale_holding_folders() -> int:
    """Remove empty orphan folders directly under the holding root."""
    import opencoeus.executor as executor_mod
    holding_root = executor_mod.HOLDING_ROOT
    if not holding_root.exists():
        return 0
    removed = 0
    for child in holding_root.iterdir():
        try:
            if child.is_dir() and not any(child.iterdir()):
                child.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def cleanup_empty_folders(root_path: Path, excluded_folders: set[str] | None = None) -> int:
    excluded = excluded_folders or set()
    removed = 0
    for dirpath, _dirnames, _filenames in os.walk(root_path, topdown=False):
        dir_path = Path(dirpath)
        if dir_path == root_path:
            continue
        if dir_path.name.lower() in _RESERVED_FOLDER_NAMES:
            continue
        if any(
            dir_path.as_posix().startswith(Path(ex).as_posix() + "/") or
            dir_path.as_posix() == Path(ex).as_posix()
            for ex in excluded
        ):
            continue
        try:
            if not any(dir_path.iterdir()):
                dir_path.rmdir()
                removed += 1
        except OSError:
            pass
    return removed
