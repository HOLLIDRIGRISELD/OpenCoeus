"""Limits for ZIP-based office documents before extraction expands them."""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.exceptions import ExtractionError

MAX_ARCHIVE_ENTRIES = 1000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


def enforce_archive_limits(path: Path) -> None:
    """Reject archives that could exhaust memory or disk while being read."""

    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ExtractionError(
                    f"Archive has too many entries ({len(infos)} > {MAX_ARCHIVE_ENTRIES})."
                )
            total = sum(info.file_size for info in infos)
            if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ExtractionError(
                    "Archive uncompressed size exceeds "
                    f"{MAX_ARCHIVE_UNCOMPRESSED_BYTES:,} bytes."
                )
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExtractionError(f"Cannot inspect archive {path.name}: {exc}") from exc


__all__ = ["enforce_archive_limits"]
