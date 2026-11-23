"""File-format identification.

Extensions are a claim, not proof. The inspector reads a small header and, for
ZIP-based Office formats, inspects the archive directory to distinguish DOCX,
PPTX and XLSX. Documents that disagree with their extension are still discovered
but are routed to the ``unknown`` extractor rather than trusted blindly.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

PDF_MAGIC = b"%PDF"
ZIP_MAGIC = b"PK\x03\x04"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
EPS_MAGIC = b"%!PS"

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
VECTOR_IMAGE_EXTENSIONS = {".eps", ".svg"}


def inspect_format(path: Path, extension: str | None = None) -> str:
    """Return a normalised format name.

    Possible values: ``pdf``, ``docx``, ``pptx``, ``xlsx``, ``image``,
    ``vector-image`` (EPS/SVG), ``text``, ``ole`` (legacy Office), ``zip``,
    ``unknown``.
    """

    suffix = (extension or path.suffix).lower()
    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return "unknown"

    if header.startswith(PDF_MAGIC):
        return "pdf"
    if header.startswith(JPEG_MAGIC) or header.startswith(PNG_MAGIC):
        return "image"
    if header.startswith(ZIP_MAGIC):
        return _inspect_zip(path, suffix)
    if header.startswith(OLE_MAGIC):
        return "ole"
    if header.startswith(EPS_MAGIC) or suffix in VECTOR_IMAGE_EXTENSIONS:
        return "vector-image"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in TEXT_EXTENSIONS or _looks_like_text(path):
        return "text"
    return "unknown"


def _inspect_zip(path: Path, suffix: str) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return "unknown"

    if any(name.startswith("word/") for name in names):
        return "docx"
    if any(name.startswith("ppt/") for name in names):
        return "pptx"
    if any(name.startswith("xl/") for name in names):
        return "xlsx"

    if suffix in {".docx", ".pptx", ".xlsx"}:
        return "unknown"
    return "zip"


def _looks_like_text(path: Path, sample_size: int = 4096) -> bool:
    """Heuristic: decode a sample and require mostly printable characters."""

    try:
        with path.open("rb") as handle:
            sample = handle.read(sample_size)
    except OSError:
        return False
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = sample.decode("cp1252")
        except UnicodeDecodeError:
            return False
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
    return printable / max(len(text), 1) > 0.9
