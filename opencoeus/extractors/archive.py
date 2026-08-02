from __future__ import annotations

import logging
import tarfile
import zipfile
from pathlib import Path

from .signals import FileSignals

logger = logging.getLogger(__name__)


def _extract_archive(file_path: Path, result: FileSignals) -> None:
    ext = file_path.suffix.lower()
    try:
        names = []
        if ext == ".zip":
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
        elif ext in {".tar", ".gz", ".bz2", ".xz", ".zst"}:
            mode = "r:*"
            with tarfile.open(file_path, mode) as tf:
                names = [m.name for m in tf.getmembers()]
        if names:
            result.metadata["archive_contents"] = names[:50]
            result.metadata["archive_count"] = str(len(names))
            result.signals_present.append("archive_listing")
            result.confidence_hint = max(result.confidence_hint, 0.3)
    except Exception as exc:
        logger.debug("Archive extraction failed for %s: %s", file_path, exc)
