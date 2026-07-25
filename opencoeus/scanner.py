from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator


@dataclass(frozen=True)
class FileRecord:
    path: Path
    size: int
    # STAGE 2: EXTENDED METADATA FOR RULE MATCHING AND FOLDER DISPLAY.
    relative_path: str = ""
    extension: str = ""
    modified_at: datetime | None = None
    folder_path: str = ""


def iter_files(root_directory: Path, error_callback: Callable[[str], None] | None = None) -> Iterator[FileRecord]:
    """WALKS A FOLDER WITHOUT FOLLOWING LINKS OR STOPPING ON UNREADABLE ITEMS."""
    def walk(current_directory: Path, depth: int = 0) -> Iterator[FileRecord]:
        if depth > 50:
            return
        try:
            with os.scandir(current_directory) as directory_entries:
                for directory_entry in directory_entries:
                    try:
                        # SKIPS SYMBOLIC LINKS TO PREVENT LOOPS AND UNEXPECTED LOCATIONS.
                        if directory_entry.is_symlink():
                            continue
                        item_path = Path(directory_entry.path)
                        if directory_entry.is_dir(follow_symlinks=False):
                            yield from walk(item_path, depth + 1)
                        elif directory_entry.is_file(follow_symlinks=False):
                            file_stat = directory_entry.stat(follow_symlinks=False)
                            file_size = file_stat.st_size
                            # COMPUTES EXTENDED METADATA FOR STAGE 2 RULE MATCHING.
                            relative_path_value = item_path.relative_to(root_directory).as_posix()
                            extension_value = item_path.suffix.lower()
                            modified_at_value = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc)
                            folder_path_value = item_path.parent.as_posix()
                            yield FileRecord(
                                path=item_path,
                                size=file_size,
                                relative_path=relative_path_value,
                                extension=extension_value,
                                modified_at=modified_at_value,
                                folder_path=folder_path_value,
                            )
                    except OSError as file_error:
                        if error_callback:
                            error_callback(f"Skipped {directory_entry.path}: {file_error}")
        except OSError as directory_error:
            if error_callback:
                error_callback(f"Cannot read {current_directory}: {directory_error}")

    yield from walk(root_directory)
