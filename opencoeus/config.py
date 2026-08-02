from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# FOLDER-NAME PATTERNS (SINGLE SOURCE OF TRUTH)
# Shared between protected-path rules (safety.py) and folder classification
# (folder_classifier.py) so the two lists cannot drift apart.
VERSION_CONTROL_PATTERNS = [r"^\.git$"]
VIRTUAL_ENVIRONMENT_PATTERNS = [r"^\.?venv$", r"^env$"]
DEPENDENCY_PATTERNS = [r"^node_modules$"]
CACHE_PATTERNS = [r"^__pycache__$", r"^\.pytest_cache$", r"^\.mypy_cache$"]

COMMON_PROTECTED_PATTERNS = [
    r"^\.opencoeus$",
    *VERSION_CONTROL_PATTERNS,
    *VIRTUAL_ENVIRONMENT_PATTERNS,
    *DEPENDENCY_PATTERNS,
    *CACHE_PATTERNS,
]

PLATFORM_PROTECTED_PATTERNS = {
    "Windows": [
        r"^\$RECYCLE\.BIN$",
        r"^System Volume Information$",
        r"^Windows$",
        r"^Program Files(?: \(x86\))?$",
    ],
    "Darwin": [r"^\.Trashes$", r"^\.Spotlight-V100$", r"^\.fseventsd$", r"^System$"],
    "Linux": [r"^proc$", r"^sys$", r"^dev$", r"^run$", r"^lost\+found$"],
}


def default_protected_patterns(operating_system_name: str | None = None) -> list[str]:
    """Combine common rules with rules for the current operating system."""
    detected_operating_system = operating_system_name or platform.system()
    return COMMON_PROTECTED_PATTERNS + PLATFORM_PROTECTED_PATTERNS.get(detected_operating_system, [])


@dataclass(frozen=True)
class ScanSettings:
    root: Path
    protected_patterns: list[str] = field(default_factory=default_protected_patterns)
    chunk_size: int = 1024 * 1024
    extract_documents: bool = True


def default_application_data_directory(operating_system_name: str | None = None) -> Path:
    """Select the native per-user data location for each supported platform."""
    detected_operating_system = operating_system_name or platform.system()
    if detected_operating_system == "Windows":
        return Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "OpenCoeus"
    if detected_operating_system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "OpenCoeus"
    linux_state_directory = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return linux_state_directory / "OpenCoeus"


def get_data_directory() -> Path:
    """Return the per-user data directory, creating it if needed.
    Honors the OPENCOEUS_DATA_DIR override and falls back to a local
    .opencoeus folder when the normal location is not writable."""
    configured_data_directory = os.getenv("OPENCOEUS_DATA_DIR")
    application_data_directory = Path(configured_data_directory) if configured_data_directory else default_application_data_directory()
    logger.debug("Using data directory: %s", application_data_directory)
    try:
        application_data_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        # USES A LOCAL FOLDER WHEN THE NORMAL PER USER DATA DIRECTORY IS READ ONLY
        logger.warning("Falling back to local .opencoeus directory")
        application_data_directory = Path.cwd() / ".opencoeus"
        application_data_directory.mkdir(parents=True, exist_ok=True)
    return application_data_directory


def database_url() -> str:
    return f"sqlite:///{(get_data_directory() / 'opencoeus.sqlite3').as_posix()}"
