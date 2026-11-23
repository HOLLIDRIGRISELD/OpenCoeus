"""Content hashing used for duplicate detection and integrity checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.core.exceptions import FileAccessError

_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file.

    Raises:
        FileAccessError: If the file cannot be read.
    """

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                digest.update(chunk)
    except OSError as exc:
        raise FileAccessError(f"Cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """Hash a string using UTF-8 encoding (useful for cache keys)."""

    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
