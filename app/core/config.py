"""Application configuration and filesystem locations.

Configuration is layered:

1. Built-in defaults (this module).
2. Optional JSON file in the user's data directory (``config.json``).
3. Values persisted in the ``settings`` database table (edited in the UI).

The database-backed settings are read through :class:`SettingsService`; this
module only provides the process-level configuration (paths, defaults).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from app.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_loopback_url(value: str) -> str | None:
    """Return a problem string unless ``value`` is an HTTP(S) loopback URL."""

    text = str(value).strip()
    if not text:
        return "llm.base_url must not be empty."
    try:
        parts = urlsplit(text)
        _ = parts.port
        host = parts.hostname
    except ValueError as exc:
        return f"llm.base_url is not a valid URL: {exc}"
    if parts.scheme not in {"http", "https"}:
        return "llm.base_url must use http or https."
    if parts.username or parts.password:
        return "llm.base_url must not contain credentials."
    if host is None or host.lower() not in LOOPBACK_HOSTS:
        return "llm.base_url must point to this computer (127.0.0.1, localhost or ::1)."
    return None


LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"})
STRING_KEYS = frozenset(
    {"log_level", "embedding_model", "llm_model", "llm_base_url", "naming_template"}
)
BOOL_KEYS = frozenset({"prefer_transformer", "enable_llm"})
INT_KEYS = frozenset({"max_file_size_mb", "scan_batch_size", "max_folder_depth"})
FLOAT_KEYS = frozenset({"high_confidence", "low_confidence"})
LIST_KEYS = frozenset({"excluded_directories", "supported_extensions"})


def _validate_value(key: str, value: object) -> object:
    """Check one hand-edited config.json value and return its usable form."""

    prefix = f"config.json: {key}"
    if key == "data_dir":
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ConfigurationError(f"{prefix} must be a directory path.")
        return Path(value).expanduser()
    if key == "db_url":
        if not isinstance(value, str) or not value.strip(" \t\r\n").startswith("sqlite:"):
            raise ConfigurationError(f"{prefix} must be a SQLite URL.")
        return value
    if key in STRING_KEYS:
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"{prefix} must be a non-empty string.")
        if key == "log_level" and value.strip().upper() not in LOG_LEVELS:
            raise ConfigurationError(f"{prefix} is not a valid logging level.")
        return value
    if key in BOOL_KEYS:
        if not isinstance(value, bool):
            raise ConfigurationError(f"{prefix} must be true or false.")
        return value
    if key in INT_KEYS:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConfigurationError(f"{prefix} must be a positive integer.")
        return value
    if key in FLOAT_KEYS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigurationError(f"{prefix} must be a number.")
        if not 0 < value < 1:
            raise ConfigurationError(f"{prefix} must be between 0 and 1.")
        return float(value)
    if key in LIST_KEYS:
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ConfigurationError(f"{prefix} must be a list of non-empty strings.")
        return tuple(value)
    return value


def default_data_dir() -> Path:
    """Return the per-user application data directory for the current OS."""

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "OpenCoeus"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenCoeus"
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "OpenCoeus"


@dataclass(slots=True)
class AppConfig:
    """Process-level configuration.

    Args:
        data_dir: Directory holding the database, logs and backups.
        db_url: SQLAlchemy URL. Defaults to SQLite inside ``data_dir``.
        log_level: Logging verbosity.
        max_file_size_mb: Files larger than this are skipped for extraction.
        scan_batch_size: Number of files processed between progress callbacks.
        embedding_model: Sentence-Transformers model name, if installed.
        prefer_transformer: Try the transformer embedding backend before
            falling back to deterministic hashing vectors.
        llm_model: Local LLM name used through the Ollama-compatible runtime.
        enable_llm: Whether to attempt local LLM assistance at all.
        naming_template: Default filename template.
        max_folder_depth: Maximum generated hierarchy depth below the root.
        high_confidence: Threshold for "strong suggestion".
        low_confidence: Below this, a file is routed to manual review.
    """

    data_dir: Path = field(default_factory=default_data_dir)
    db_url: str | None = None
    log_level: str = "INFO"
    max_file_size_mb: int = 200
    scan_batch_size: int = 25
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    prefer_transformer: bool = True
    llm_model: str = "qwen2.5:3b-instruct"
    llm_base_url: str = "http://127.0.0.1:11434"
    enable_llm: bool = True
    naming_template: str = "{title}"
    max_folder_depth: int = 4
    high_confidence: float = 0.85
    low_confidence: float = 0.60
    excluded_directories: tuple[str, ...] = (
        ".git",
        ".venv",
        "node_modules",
        "__pycache__",
        ".cache",
        "$RECYCLE.BIN",
        "System Volume Information",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "venv",
        "env",
        "site-packages",
    )
    supported_extensions: tuple[str, ...] = (
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".txt",
        ".md",
        ".csv",
        ".jpg",
        ".jpeg",
        ".png",
    )

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser()
        if self.db_url is None:
            self.db_url = f"sqlite:///{self.data_dir / 'opencoeus.db'}"

    @property
    def db_path(self) -> Path:
        """Filesystem path of the SQLite database."""

        if not self.db_url or not self.db_url.startswith("sqlite:"):
            raise ConfigurationError("Only SQLite databases have a filesystem path.")
        raw = self.db_url.split("sqlite:///", 1)[-1]
        return Path(raw)

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create the data, backup and log directories if missing."""

        for directory in (self.data_dir, self.backup_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write_probe"
            probe.touch()
            probe.unlink()

    @staticmethod
    def _base_dir(data_dir: Path | None) -> Path:
        if data_dir is not None:
            return Path(data_dir).expanduser()
        env_dir = os.environ.get("OPENCOEUS_DATA_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        return default_data_dir()

    @classmethod
    def _load_from(cls, directory: Path, *, fixed_dir: bool = False) -> AppConfig:
        base = cls(data_dir=directory)
        config_file = base.data_dir / "config.json"
        if not config_file.is_file():
            base.ensure_directories()
            return base

        try:
            raw = json.loads(config_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Cannot read {config_file}: {exc}") from exc

        allowed = set(cls.__dataclass_fields__)
        if fixed_dir:
            allowed.discard("data_dir")
        payload = {
            key: _validate_value(key, value) for key, value in raw.items() if key in allowed
        }

        values = {
            "data_dir": base.data_dir,
            "db_url": base.db_url,
            "log_level": base.log_level,
            "max_file_size_mb": base.max_file_size_mb,
            "scan_batch_size": base.scan_batch_size,
            "embedding_model": base.embedding_model,
            "prefer_transformer": base.prefer_transformer,
            "llm_model": base.llm_model,
            "llm_base_url": base.llm_base_url,
            "enable_llm": base.enable_llm,
            "naming_template": base.naming_template,
            "max_folder_depth": base.max_folder_depth,
            "high_confidence": base.high_confidence,
            "low_confidence": base.low_confidence,
            "excluded_directories": base.excluded_directories,
            "supported_extensions": base.supported_extensions,
        }
        values.update(payload)
        if "db_url" not in payload:
            values.pop("db_url", None)
        merged = cls(**values)
        problem = validate_loopback_url(str(merged.llm_base_url))
        if problem:
            raise ConfigurationError(f"config.json: {problem}")
        if merged.low_confidence >= merged.high_confidence:
            raise ConfigurationError("config.json: low_confidence must be less than high_confidence.")
        merged.ensure_directories()
        return merged

    @classmethod
    def load(cls, data_dir: Path | None = None) -> AppConfig:
        """Load configuration, merging an optional ``config.json`` file.

        Unknown keys are ignored so that older configs keep working. An
        unwritable data directory falls back to the per-user default.
        """

        chosen = cls._base_dir(data_dir)
        fixed_dir = data_dir is not None or bool(os.environ.get("OPENCOEUS_DATA_DIR"))
        try:
            return cls._load_from(chosen, fixed_dir=fixed_dir)
        except OSError as exc:
            fallback = default_data_dir()
            if fallback == chosen:
                raise ConfigurationError(f"Data directory {chosen} is not writable: {exc}") from exc
            logger.warning("Data directory %s is not writable; using %s", chosen, fallback)
            try:
                return cls._load_from(fallback)
            except OSError as nested:
                raise ConfigurationError(f"Data directory {fallback} is not writable: {nested}") from nested
