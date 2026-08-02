from __future__ import annotations

import logging
from pathlib import Path

from .audio import _extract_audio
from .archive import _extract_archive
from .code import _extract_code, _extract_text, _extract_text_fallback
from .image import _extract_image
from .office import _extract_docx, _extract_pptx, _extract_spreadsheet
from .pdf import _extract_pdf
from .signals import FileSignals

logger = logging.getLogger(__name__)


_INSTALLER_EXTENSIONS = frozenset({
    ".exe", ".msi", ".dmg", ".deb", ".rpm", ".appimage",
    ".pkg", ".run", ".sh", ".bin",
})

_SYSTEM_EXTENSIONS = frozenset({
    ".dll", ".sys", ".so", ".dylib", ".kext", ".drv",
    ".o", ".obj", ".lib", ".a",
})

_TEMP_EXTENSIONS = frozenset({
    ".tmp", ".temp", ".swp", ".bak", "~", ".log", ".cache",
})

_CODE_EXTENSIONS = frozenset({
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".rb", ".go", ".rs", ".swift", ".kt", ".scala",
    ".html", ".css", ".scss", ".less", ".xml", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh", ".bash",
    ".zsh", ".ps1", ".bat", ".cmd", ".sql", ".r", ".m", ".mm",
})

_TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".rst", ".tex", ".org",
})

_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".ico", ".svg", ".heic", ".heif",
})

_AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a",
    ".opus", ".aiff", ".wv", ".ape",
})

_VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".3gp", ".ogv", ".ts",
})

_SPREADSHEET_EXTENSIONS = frozenset({".xlsx", ".xls", ".xlsm", ".xlsb", ".ods"})

_ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst"})


def _get_category(ext: str) -> str:
    if ext in _INSTALLER_EXTENSIONS:
        return "installer"
    if ext in _SYSTEM_EXTENSIONS:
        return "system"
    if ext in _TEMP_EXTENSIONS:
        return "temp"
    if ext in _CODE_EXTENSIONS:
        return "code"
    if ext in _TEXT_EXTENSIONS:
        return "document"
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext in _AUDIO_EXTENSIONS:
        return "audio"
    if ext in _VIDEO_EXTENSIONS:
        return "video"
    if ext in _SPREADSHEET_EXTENSIONS or ext == ".csv":
        return "spreadsheet"
    if ext in _ARCHIVE_EXTENSIONS:
        return "archive"
    if ext == ".pdf":
        return "document"
    if ext in {".docx", ".doc", ".rtf", ".odt", ".pptx", ".ppt"}:
        return "document"
    return "unknown"


NO_RENAME_CATEGORIES = frozenset({"installer", "system", "temp", "code"})


def is_no_rename(extension: str) -> bool:
    """True for server/code/config/system files that must keep their original name."""
    return _get_category(extension) in NO_RENAME_CATEGORIES


def extract_all(file_path: Path) -> FileSignals:
    ext = file_path.suffix.lower()
    category = _get_category(ext)

    if category in ("installer", "system", "temp"):
        return FileSignals(
            file_type=category,
            extension=ext,
            confidence_hint=0.1,
            signals_present=["detected_category"],
        )

    result = FileSignals(
        file_type=category,
        extension=ext,
        signals_present=["detected_category"],
    )

    try:
        if ext == ".pdf":
            _extract_pdf(file_path, result)
        elif ext in {".docx", ".doc"}:
            _extract_docx(file_path, result)
        elif ext in {".pptx", ".ppt"}:
            _extract_pptx(file_path, result)
        elif ext in _TEXT_EXTENSIONS:
            _extract_text(file_path, result)
        elif ext in _CODE_EXTENSIONS:
            _extract_code(file_path, result)
        elif ext in _SPREADSHEET_EXTENSIONS or ext in {".csv",}:
            _extract_spreadsheet(file_path, result)
        elif ext in _IMAGE_EXTENSIONS:
            _extract_image(file_path, result)
        elif ext in _AUDIO_EXTENSIONS:
            _extract_audio(file_path, result)
        elif ext in _VIDEO_EXTENSIONS:
            from .video import _extract_video
            _extract_video(file_path, result)
        elif ext in _ARCHIVE_EXTENSIONS:
            _extract_archive(file_path, result)
        elif ext in {".rtf", ".odt"}:
            _extract_text_fallback(file_path, result)
        else:
            _extract_text_fallback(file_path, result)
    except Exception as exc:
        logger.debug("Content extraction failed for %s: %s", file_path, exc)

    return result
