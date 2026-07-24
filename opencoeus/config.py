from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


COMMON_PROTECTED_PATTERNS = [
    r"^\.opencoeus$",
    r"^\.git$",
    r"^node_modules$",
    r"^\.?venv$",
    r"^env$",
    r"^__pycache__$",
    r"^\.pytest_cache$",
    r"^\.mypy_cache$",
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
    # COMBINES COMMON RULES WITH RULES FOR THE CURRENT OPERATING SYSTEM.
    detected_operating_system = operating_system_name or platform.system()
    return COMMON_PROTECTED_PATTERNS + PLATFORM_PROTECTED_PATTERNS.get(detected_operating_system, [])


@dataclass(frozen=True)
class ScanSettings:
    root: Path
    protected_patterns: list[str] = field(default_factory=default_protected_patterns)
    chunk_size: int = 1024 * 1024
    extract_documents: bool = True


def default_application_data_directory(operating_system_name: str | None = None) -> Path:
    # SELECTS THE NATIVE PER-USER DATA LOCATION FOR EACH SUPPORTED PLATFORM.
    detected_operating_system = operating_system_name or platform.system()
    if detected_operating_system == "Windows":
        return Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "OpenCoeus"
    if detected_operating_system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "OpenCoeus"
    linux_state_directory = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return linux_state_directory / "OpenCoeus"


def database_url() -> str:
    configured_data_directory = os.getenv("OPENCOEUS_DATA_DIR")
    application_data_directory = Path(configured_data_directory) if configured_data_directory else default_application_data_directory()
    logger.debug("Using data directory: %s", application_data_directory)
    try:
        application_data_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        # USES A LOCAL FOLDER WHEN THE NORMAL PER-USER DATA DIRECTORY IS READ-ONLY.
        logger.warning("Falling back to local .opencoeus directory")
        application_data_directory = Path.cwd() / ".opencoeus"
        application_data_directory.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(application_data_directory / 'opencoeus.sqlite3').as_posix()}"
