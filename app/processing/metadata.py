"""Filesystem metadata collection."""

from __future__ import annotations

import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import ScannedFile
from app.processing.file_signature import inspect_format


def _timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def describe_file(path: Path, *, root: Path, supported_extensions: set[str]) -> ScannedFile:
    """Collect metadata for one file without reading its full contents.

    Raises:
        OSError: If the file cannot be statted.
    """

    stat = path.stat()
    extension = path.suffix.lower()
    detected = inspect_format(path, extension)
    mime_type = mimetypes.guess_type(path.name)[0]
    supported = extension in supported_extensions or detected in {
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "text",
        "image",
        "vector-image",
    }
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    return ScannedFile(
        path=path,
        relative_path=relative,
        filename=path.name,
        extension=extension,
        size=stat.st_size,
        modified_at=_timestamp(stat.st_mtime),
        created_at=_timestamp(stat.st_ctime),
        mime_type=mime_type,
        detected_format=detected,
        supported=supported,
    )
