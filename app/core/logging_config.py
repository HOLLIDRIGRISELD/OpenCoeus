"""Structured, rotating file logging plus concise console output."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


class _SensitivePathFilter(logging.Filter):
    """Redact the user's home directory prefix from log messages.

    Logs are useful for diagnosis, but they should not become a plaintext index
    of everything the user keeps on their machine.
    """

    def __init__(self, home: str) -> None:
        super().__init__()
        self._home = home

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and self._home and self._home in record.msg:
            record.msg = record.msg.replace(self._home, "~")
        if record.args:
            record.args = tuple(
                arg.replace(self._home, "~") if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    """Configure root logging once per process.

    Args:
        log_dir: Directory for ``opencoeus.log``.
        level: Logging level name (e.g. ``INFO``).
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(_FORMAT)

    file_handler = RotatingFileHandler(
        log_dir / "opencoeus.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_SensitivePathFilter(str(Path.home())))
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.WARNING)
    root.addHandler(console)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""

    return logging.getLogger(name)
