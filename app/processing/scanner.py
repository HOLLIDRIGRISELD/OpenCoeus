"""Recursive, cancellable directory scanner.

The scanner never modifies the filesystem. It yields :class:`ScannedFile`
objects as it discovers them, which lets the UI update incrementally and lets
the caller cancel a long traversal.
"""

from __future__ import annotations

import fnmatch
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.core.exceptions import FileAccessError
from app.core.logging_config import get_logger
from app.domain.models import ScannedFile
from app.processing.metadata import describe_file

logger = get_logger(__name__)

_EXCLUDED_FILE_EXTENSIONS = frozenset(
    {
        ".exe", ".msi", ".apk", ".app", ".deb", ".rpm", ".dmg",
        ".gz", ".bz2", ".xz", ".zlib", ".zip", ".7z", ".rar", ".tar",
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
        ".rand", ".dwg", ".pyc", ".dll", ".so", ".bin", ".iso", ".img",
    }
)
_EXCLUDED_FILE_NAMES = frozenset(
    {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
        "cargo.lock", "composer.lock", "gemfile.lock",
        "thumbs.db", "desktop.ini", ".ds_store",
    }
)
_EXCLUDED_NAME_SUFFIXES = (".min.js", ".min.css", ".map")
_EXCLUDED_FILE_PREFIXES = ("._",)


@dataclass(slots=True)
class ScanOptions:
    """Controls traversal behaviour.

    Args:
        recursive: Descend into subdirectories.
        follow_symlinks: Follow symbolic links (disabled by default to avoid loops).
        excluded_directory_names: Directory names skipped anywhere in the tree.
        excluded_paths: Absolute paths skipped.
        supported_extensions: Extensions treated as processable.
        include_unsupported: Yield unsupported files as well.
        max_files: Safety limit; ``0`` means unlimited.
        custom_patterns: Basename patterns excluded anywhere in the tree.
        included_folders: When non-empty, only these directory names are descended.
    """

    recursive: bool = True
    follow_symlinks: bool = False
    excluded_directory_names: tuple[str, ...] = (
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
    excluded_paths: set[Path] = field(default_factory=set)
    supported_extensions: set[str] = field(default_factory=set)
    include_unsupported: bool = True
    max_files: int = 0
    custom_patterns: tuple[str, ...] = ()
    included_folders: tuple[str, ...] = ()


@dataclass(slots=True)
class ScanProgress:
    """Progress information emitted during a scan."""

    discovered: int
    current_directory: str
    skipped: int = 0


class ScanCancelled(Exception):
    """Raised internally when the caller requests cancellation."""


class FileScanner:
    """Discovers files beneath a root directory."""

    def __init__(self, options: ScanOptions | None = None) -> None:
        self.options = options or ScanOptions()
        self._excluded_directories = {
            name.lower() for name in self.options.excluded_directory_names
        }
        self._custom_patterns = tuple(
            pattern.lower() for pattern in self.options.custom_patterns
        )
        self._included_folders = {name.lower() for name in self.options.included_folders}

    @staticmethod
    def _matches_pattern(name: str, patterns: tuple[str, ...]) -> bool:
        lowered = name.lower()
        return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in patterns)

    def _excluded_file(self, path: Path) -> bool:
        name = path.name.lower()
        return (
            name in _EXCLUDED_FILE_NAMES
            or name.startswith(_EXCLUDED_FILE_PREFIXES)
            or name.endswith(_EXCLUDED_NAME_SUFFIXES)
            or path.suffix.lower() in _EXCLUDED_FILE_EXTENSIONS
        )

    def scan(
        self,
        root: Path,
        *,
        cancel_event: threading.Event | None = None,
        progress: Callable[[ScanProgress], None] | None = None,
        errors: Callable[[Path, str], None] | None = None,
    ) -> Iterator[ScannedFile]:
        """Yield discovered files.

        Args:
            root: Directory to scan.
            cancel_event: When set, traversal stops and ``ScanCancelled`` propagates.
            progress: Optional callback invoked as files are found.
            errors: Optional callback invoked for unreadable entries.

        Raises:
            FileAccessError: If ``root`` is not a readable directory.
        """

        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            raise FileAccessError(f"Not a directory: {root}")

        discovered = 0
        skipped = 0
        visited_dirs: set[tuple[int, int]] = set()

        def walk(directory: Path) -> Iterator[ScannedFile]:
            nonlocal discovered, skipped
            if cancel_event is not None and cancel_event.is_set():
                raise ScanCancelled
            try:
                stat = directory.stat()
                identity = (stat.st_dev, stat.st_ino)
                if identity in visited_dirs:
                    return
                visited_dirs.add(identity)
                entries = os.scandir(directory)
            except OSError as exc:
                skipped += 1
                if errors:
                    errors(directory, str(exc))
                logger.warning("Cannot read directory %s: %s", directory, exc)
                return

            with entries:
                for entry in entries:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ScanCancelled
                    path = Path(entry.path)
                    try:
                        is_symlink = entry.is_symlink()
                        if is_symlink and not self.options.follow_symlinks:
                            skipped += 1
                            continue
                        if entry.is_dir(follow_symlinks=self.options.follow_symlinks):
                            if entry.name.lower() in self._excluded_directories:
                                skipped += 1
                                continue
                            if self._matches_pattern(entry.name, self._custom_patterns):
                                skipped += 1
                                continue
                            if self._included_folders and entry.name.lower() not in self._included_folders:
                                skipped += 1
                                continue
                            if path.resolve() in self.options.excluded_paths:
                                skipped += 1
                                continue
                            if self.options.recursive:
                                yield from walk(path)
                            continue
                        if not entry.is_file(follow_symlinks=self.options.follow_symlinks):
                            continue

                        if path in self.options.excluded_paths:
                            skipped += 1
                            continue
                        if self._matches_pattern(path.name, self._custom_patterns):
                            skipped += 1
                            continue
                        if not self.options.include_unsupported and self._excluded_file(path):
                            skipped += 1
                            continue

                        scanned = describe_file(
                            path,
                            root=root,
                            supported_extensions=self.options.supported_extensions,
                        )
                        if not scanned.supported and not self.options.include_unsupported:
                            skipped += 1
                            continue
                        discovered += 1
                        if progress:
                            progress(ScanProgress(discovered, str(directory), skipped))
                        yield scanned
                        if self.options.max_files and discovered >= self.options.max_files:
                            return
                    except OSError as exc:
                        skipped += 1
                        if errors:
                            errors(path, str(exc))
                        logger.warning("Skipping inaccessible entry %s: %s", path, exc)

        yield from walk(root)

    def count(self, root: Path) -> int:
        """Count discoverable files without reading contents."""

        return sum(1 for _ in self.scan(root))
