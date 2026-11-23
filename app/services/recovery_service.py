"""Recovery, backup and maintenance operations exposed to the UI/CLI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import AppConfig
from app.domain.models import OperationResult, OperationView
from app.infrastructure.database import Database
from app.infrastructure.repositories.operations import OperationRepository
from app.organisation.recovery import RecoveryManager
from app.search.indexer import SearchIndexer


@dataclass(slots=True)
class BackupInfo:
    path: Path
    size: int
    created_at: datetime


class RecoveryService:
    """Undo, backup, restore and integrity checks.

    Undo delegates to :class:`RecoveryManager`, which refuses to overwrite an
    occupied destination or restore a file that changed after it was organised.
    """

    def __init__(
        self,
        config: AppConfig,
        db: Database,
        operations: OperationRepository,
        recovery: RecoveryManager,
        indexer: SearchIndexer,
    ) -> None:
        self._config = config
        self._db = db
        self._operations = operations
        self._recovery = recovery
        self._indexer = indexer

    def undo(self, operation_id: int) -> OperationResult:
        return self._recovery.undo(operation_id)

    def undoable(self, limit: int = 100) -> list[OperationView]:
        return self._recovery.undoable(limit=limit)

    def history(self, *, limit: int = 200, status: str | None = None) -> list[OperationView]:
        return self._operations.list_operations(limit=limit, status=status)

    def operation(self, operation_id: int) -> dict[str, object] | None:
        return self._operations.get_operation(operation_id)

    def backup(self, destination: Path | None = None) -> Path:
        """Create a timestamped SQLite backup (or copy to ``destination``)."""

        if destination is None:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            destination = self._config.backup_dir / f"opencoeus-{stamp}.db"
        destination = Path(destination).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._db.backup(destination)

    def list_backups(self) -> list[BackupInfo]:
        if not self._config.backup_dir.is_dir():
            return []
        backups: list[BackupInfo] = []
        for path in sorted(self._config.backup_dir.glob("*.db"), reverse=True):
            try:
                stat = path.stat()
            except OSError:
                continue
            backups.append(
                BackupInfo(
                    path=path,
                    size=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )
        return backups

    def restore(self, backup_file: Path) -> None:
        """Replace the live database; the caller must restart the application."""

        self._db.restore(Path(backup_file))

    def integrity_check(self) -> bool:
        return self._db.integrity_check()

    def rebuild_search_index(self) -> int:
        return self._indexer.rebuild()

    def vacuum(self) -> None:
        """Reclaim space after large deletions."""

        self._db.vacuum()


__all__ = ["BackupInfo", "RecoveryService"]
