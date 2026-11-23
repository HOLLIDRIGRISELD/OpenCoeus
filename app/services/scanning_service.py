"""Scanning: discover files, hash them and register them in the database."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import AppConfig
from app.core.constants import STATUS_DISCOVERED, STATUS_UNSUPPORTED
from app.core.exceptions import FileAccessError
from app.core.logging_config import get_logger
from app.core.progress import CancellationToken, ProgressCallback, emit
from app.domain.models import ScannedFile
from app.infrastructure.database import Database
from app.infrastructure.repositories.caches import FileFingerprintRepository
from app.infrastructure.repositories.files import FileRepository
from app.infrastructure.repositories.settings import ScanSessionRepository
from app.processing.hashing import sha256_file
from app.processing.scanner import FileScanner, ScanCancelled, ScanOptions
from app.services.common import ServiceReport
from app.services.profile_service import ProfileService, ScanProfileView
from app.services.settings_service import SettingsService

logger = get_logger(__name__)


@dataclass(slots=True)
class ScanReport(ServiceReport):
    """Outcome of one directory scan."""

    root: Path | None = None
    session_id: int = 0
    discovered: int = 0
    created: int = 0
    updated: int = 0
    hashed: int = 0
    unsupported: int = 0
    cancelled: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)


class ScanningService:
    """Registers files from a directory tree without modifying them."""

    def __init__(
        self,
        config: AppConfig,
        files: FileRepository,
        sessions: ScanSessionRepository,
        settings: SettingsService,
        fingerprints: FileFingerprintRepository | None = None,
        db: Database | None = None,
        profiles: ProfileService | None = None,
    ) -> None:
        self._config = config
        self._files = files
        self._sessions = sessions
        self._settings = settings
        self._fingerprints = fingerprints
        self._db = db
        self._profiles = profiles

    def scan(
        self,
        root: Path,
        *,
        recursive: bool = True,
        include_unsupported: bool = False,
        max_files: int = 0,
        compute_hashes: bool = True,
        progress: ProgressCallback | None = None,
        cancel: CancellationToken | None = None,
        profile: ScanProfileView | None = None,
    ) -> ScanReport:
        root = Path(root).expanduser().resolve()
        started = time.perf_counter()
        report = ScanReport(root=root)

        selected = profile or (self._profiles.active() if self._profiles is not None else None)
        excluded_directories = self._config.excluded_directories
        included_folders: tuple[str, ...] = ()
        custom_patterns: tuple[str, ...] = ()
        if selected is not None:
            excluded_directories = (*excluded_directories, *selected.excluded_folders)
            included_folders = selected.included_folders
            custom_patterns = selected.custom_patterns

        options = ScanOptions(
            recursive=recursive,
            excluded_directory_names=excluded_directories,
            supported_extensions=set(self._config.supported_extensions),
            include_unsupported=include_unsupported,
            max_files=max_files,
            custom_patterns=custom_patterns,
            included_folders=included_folders,
        )
        scanner = FileScanner(options)
        session_id = self._sessions.start(root)
        report.session_id = session_id

        def on_error(path: Path, message: str) -> None:
            report.errors.append((str(path), message))

        pending: list[tuple[ScannedFile, str]] = []
        pending_fingerprints: list[tuple[str, int, int, str]] = []
        batch_size = max(1, self._config.scan_batch_size)
        fingerprint_map = (
            self._fingerprints.all_for_root(str(root)) if self._fingerprints is not None else {}
        )

        def flush_pending() -> None:
            if not pending:
                return
            try:
                if self._db is None:
                    results = self._files.upsert_many(pending)
                    if self._fingerprints is not None:
                        self._fingerprints.set_many(pending_fingerprints)
                else:
                    with self._db.batch():
                        results = self._files.upsert_many(pending)
                        if self._fingerprints is not None:
                            self._fingerprints.set_many(pending_fingerprints)
            except Exception as exc:
                logger.exception("Could not register a batch of files")
                for scanned, _ in pending:
                    report.failed += 1
                    report.errors.append((str(scanned.path), str(exc)))
            else:
                for (_, _), (_, created) in zip(pending, results, strict=True):
                    if created:
                        report.created += 1
                    else:
                        report.updated += 1
            pending.clear()
            pending_fingerprints.clear()

        try:
            try:
                for scanned in scanner.scan(
                    root,
                    cancel_event=cancel.event if cancel else None,
                    progress=(
                        (lambda info: emit(
                            progress,
                            "scan",
                            info.discovered,
                            0,
                            f"Discovering files… {info.discovered} found",
                        ))
                        if progress is not None
                        else None
                    ),
                    errors=on_error,
                ):
                    if cancel is not None and cancel.cancelled:
                        raise ScanCancelled
                    report.discovered += 1
                    if not scanned.supported:
                        report.unsupported += 1

                    if compute_hashes and scanned.supported and scanned.size <= self._config.max_file_size_bytes:
                        mtime_ns = 0
                        try:
                            mtime_ns = scanned.path.stat().st_mtime_ns
                        except OSError as exc:
                            report.errors.append((str(scanned.path), f"Stat failed: {exc}"))
                        cached = fingerprint_map.get(str(scanned.path))
                        if cached is not None and cached[0] == scanned.size and cached[1] == mtime_ns:
                            scanned.sha256 = cached[2]
                        else:
                            try:
                                scanned.sha256 = sha256_file(scanned.path)
                                report.hashed += 1
                                if self._fingerprints is not None and mtime_ns:
                                    pending_fingerprints.append(
                                        (str(scanned.path), scanned.size, mtime_ns, scanned.sha256)
                                    )
                            except (OSError, FileAccessError) as exc:
                                report.errors.append((str(scanned.path), f"Hashing failed: {exc}"))

                    pending.append(
                        (
                            scanned,
                            STATUS_DISCOVERED if scanned.supported else STATUS_UNSUPPORTED,
                        )
                    )
                    if len(pending) >= batch_size:
                        flush_pending()

                    if report.discovered % batch_size == 0:
                        emit(
                            progress,
                            "scan",
                            report.discovered,
                            0,
                            f"{report.discovered} files discovered, {report.created} new",
                            scanned.filename,
                        )
            finally:
                flush_pending()
        except ScanCancelled:
            report.cancelled = True
            self._sessions.finish(
                session_id,
                discovered=report.discovered,
                processed=report.processed,
                failed=report.failed,
                status="cancelled",
            )
        except FileAccessError as exc:
            self._sessions.finish(
                session_id,
                discovered=report.discovered,
                processed=report.created + report.updated,
                failed=report.failed,
                status="failed",
                error=str(exc),
            )
            raise

        report.processed = report.created + report.updated
        report.duration_seconds = round(time.perf_counter() - started, 3)
        report.total = report.discovered

        if report.discovered and not report.cancelled:
            self._settings.set_organisation_root(root)

        self._sessions.finish(
            session_id,
            discovered=report.discovered,
            processed=report.processed,
            failed=report.failed,
            status="cancelled" if report.cancelled else "completed",
        )
        emit(
            progress,
            "scan",
            report.discovered,
            0,
            f"Scan finished: {report.created} new, {report.updated} refreshed",
        )
        return report
