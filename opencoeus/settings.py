from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import get_data_directory

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    dark_theme: bool = True
    organize_after_scan: bool = True
    confirm_execute: bool = True
    confirm_undo: bool = True

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from disk, falling back to defaults when the file is missing or malformed."""
        path = settings_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring malformed settings file at %s", path)
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in known})

    def save(self) -> None:
        """Persist settings to disk as json."""
        try:
            path = settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(self), indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("Could not save settings to %s", settings_path())


def settings_path() -> Path:
    """Return the path of the settings file inside the per-user data directory."""
    return get_data_directory() / "settings.json"
