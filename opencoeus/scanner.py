from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


@dataclass(frozen=True)
class FileRecord:
    path: Path
    size: int


def iter_files(root_directory: Path, error_callback: Callable[[str], None] | None = None) -> Iterator[FileRecord]:
    """WALKS A FOLDER WITHOUT FOLLOWING LINKS OR STOPPING ON UNREADABLE ITEMS."""
    def walk(current_directory: Path) -> Iterator[FileRecord]:
        try:
            with os.scandir(current_directory) as directory_entries:
                for directory_entry in directory_entries:
                    try:
                        # SKIPS SYMBOLIC LINKS TO PREVENT LOOPS AND UNEXPECTED LOCATIONS.
                        if directory_entry.is_symlink():
                            continue
                        item_path = Path(directory_entry.path)
                        if directory_entry.is_dir(follow_symlinks=False):
                            yield from walk(item_path)
                        elif directory_entry.is_file(follow_symlinks=False):
                            file_size = directory_entry.stat(follow_symlinks=False).st_size
                            yield FileRecord(item_path, file_size)
                    except OSError as file_error:
                        if error_callback:
                            error_callback(f"Skipped {directory_entry.path}: {file_error}")
        except OSError as directory_error:
            if error_callback:
                error_callback(f"Cannot read {current_directory}: {directory_error}")

    yield from walk(root_directory)
