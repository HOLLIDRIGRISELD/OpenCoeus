"""SQLite database lifecycle, schema bootstrap, FTS5 index and backups."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.constants import DEFAULT_CATEGORIES, UNCLASSIFIED
from app.core.exceptions import DatabaseError
from app.core.logging_config import get_logger
from app.infrastructure.models import Base, Category, Setting

logger = get_logger(__name__)

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS file_fts USING fts5(
    filename,
    content,
    tags,
    tokenize = 'porter unicode61'
);
"""

CORE_TABLES = frozenset(set(Base.metadata.tables) | {"file_fts"})

REQUIRED_COLUMNS = {
    name: frozenset(column.name for column in table.columns)
    for name, table in Base.metadata.tables.items()
}
REQUIRED_COLUMNS["file_fts"] = frozenset({"filename", "content", "tags"})

ROOT_CATEGORY_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_category_root_name "
    "ON categories(name) WHERE parent_id IS NULL"
)

PERFORMANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_da_file_id_id "
    "ON document_analyses(file_id, id DESC)",
    "CREATE INDEX IF NOT EXISTS ix_files_status_path "
    "ON files(processing_status, current_path)",
    "CREATE INDEX IF NOT EXISTS ix_plan_items_file_latest "
    "ON plan_items(file_id, plan_id DESC, id DESC)",
)


class Database:
    """Owns the SQLAlchemy engine and session factory.

    Args:
        url: SQLAlchemy URL, e.g. ``sqlite:////home/user/.local/share/OpenCoeus/opencoeus.db``.
        echo: Log SQL statements (development only).
    """

    _lock = threading.RLock()

    def __init__(self, url: str, echo: bool = False) -> None:
        self.url = url
        self._is_memory = ":memory:" in url
        connect_args: dict[str, object] = {"check_same_thread": False, "timeout": 15}
        kwargs: dict[str, object] = {"echo": echo, "future": True}
        if self._is_memory:
            kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, connect_args=connect_args, **kwargs)
        self._session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, autoflush=False, future=True
        )
        self._batch: ContextVar[Session | None] = ContextVar("opencoeus_batch", default=None)
        self._install_sqlite_pragmas()

    def _install_sqlite_pragmas(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _on_connect(dbapi_connection: sqlite3.Connection, _record: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=15000")
            if not self._is_memory:
                # Switching journal mode needs an exclusive lock that ignores busy_timeout.
                for attempt in range(30):
                    try:
                        cursor.execute("PRAGMA journal_mode=WAL")
                        break
                    except sqlite3.OperationalError:
                        if attempt == 29:
                            raise
                        time.sleep(0.05)
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size = -65536")
            cursor.execute("PRAGMA temp_store = MEMORY")
            cursor.execute("PRAGMA wal_autocheckpoint = 8192")
            cursor.close()

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Provide a transactional session scope.

        Commits on success, rolls back on failure, always closes.
        """

        with self._lock:
            shared = self._batch.get()
            if shared is not None:
                if shared.in_nested_transaction():
                    yield shared
                    return
                with shared.begin_nested():
                    yield shared
                return
            session = self._session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    @contextmanager
    def batch(self) -> Iterator[Session]:
        """Share one transaction across every repository call in a scope."""

        with self._lock:
            shared = self._batch.get()
            if shared is not None:
                yield shared
                return
            session = self._session_factory()
            token = self._batch.set(session)
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
                self._batch.reset(token)

    def create_schema(self) -> None:
        """Create all tables, the FTS index and seed default data atomically."""

        with self._lock:
            try:
                # BEGIN IMMEDIATE serialises bootstrap across processes, not just threads.
                with self.engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as connection:
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    try:
                        Base.metadata.create_all(connection)
                        connection.execute(text(FTS_SCHEMA))
                        connection.execute(text(ROOT_CATEGORY_INDEX))
                        for statement in PERFORMANCE_INDEXES:
                            connection.execute(text(statement))
                        self.seed_defaults(connection)
                        connection.exec_driver_sql("COMMIT")
                    except Exception:
                        connection.exec_driver_sql("ROLLBACK")
                        raise
            except Exception as exc:  # pragma: no cover - defensive
                raise DatabaseError(f"Could not initialise database: {exc}") from exc

    def ensure_performance_indexes(self) -> None:
        with self.engine.begin() as connection:
            for statement in PERFORMANCE_INDEXES:
                connection.execute(text(statement))

    def purge_session_data(self) -> int:
        """Forget the previous session; keep settings, categories and rules.

        Files on disk are never touched. Removing the file index also removes its
        analyses, suggestions, tags and vectors. Plans and operation history go
        too, because their targets are no longer part of this session.
        """

        tables = (
            "batch_execution_items",
            "batch_executions",
            "operation_events",
            "operations",
            "plan_items",
            "organisation_plans",
            "suggestions",
            "document_analyses",
            "embedding_blobs",
            "embeddings",
            "document_chunks",
            "document_contents",
            "file_metadata",
            "file_tags",
            "tags",
            "classification_feedback",
            "embedding_cache_blobs",
            "embedding_cache",
            "scan_sessions",
            "files",
            "file_fts",
        )
        with self._lock:
            deleted = 0
            try:
                with self.engine.begin() as connection:
                    for table in tables:
                        deleted += connection.execute(text(f"DELETE FROM {table}")).rowcount
            except Exception as exc:
                raise DatabaseError(f"Could not reset the previous session: {exc}") from exc
            if deleted:
                try:
                    self.vacuum()
                except DatabaseError as exc:
                    logger.warning("Session reset completed but VACUUM failed: %s", exc)
            return deleted

    def vacuum(self) -> None:
        with self._lock:
            try:
                with self.engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as connection:
                    connection.exec_driver_sql("VACUUM")
            except Exception as exc:
                raise DatabaseError(f"VACUUM failed: {exc}") from exc

    def seed_defaults(self, connection: Connection) -> None:
        """Insert default categories and settings if they are missing."""

        for parent_name in sorted({entry[0] for entry in DEFAULT_CATEGORIES}):
            connection.execute(
                sqlite_insert(Category)
                .values(name=parent_name, description=f"{parent_name} documents", is_system=True)
                .on_conflict_do_nothing()
            )
        connection.execute(
            sqlite_insert(Category)
            .values(
                name=UNCLASSIFIED,
                description="Documents awaiting human review",
                is_system=True,
            )
            .on_conflict_do_nothing()
        )
        roots = dict(
            connection.execute(
                text("SELECT name, id FROM categories WHERE parent_id IS NULL")
            ).all()
        )

        for parent_name, child_name, description in DEFAULT_CATEGORIES:
            parent_id = roots[parent_name]
            connection.execute(
                sqlite_insert(Category)
                .values(
                    name=child_name,
                    parent_id=parent_id,
                    description=description,
                    is_system=True,
                )
                .on_conflict_do_nothing()
            )
            connection.execute(
                text(
                    "UPDATE categories SET description = :description "
                    "WHERE name = :name AND parent_id = :parent_id AND is_system = 1"
                ),
                {
                    "description": description,
                    "name": child_name,
                    "parent_id": parent_id,
                },
            )

        defaults = {
            "app.theme": "dark",
            "app.naming_template": "{title}",
            "search.alpha": "0.4",
            "search.beta": "0.6",
        }
        for key, value in defaults.items():
            connection.execute(
                sqlite_insert(Setting).values(key=key, value=value).on_conflict_do_nothing()
            )

    def upsert_fts(self, file_id: int, filename: str, content: str, tags: str) -> None:
        """Insert or replace the FTS row for a file."""

        with self._lock:
            shared = self._batch.get()
            if shared is not None:
                shared.execute(text("DELETE FROM file_fts WHERE rowid = :rowid"), {"rowid": file_id})
                shared.execute(
                    text(
                        "INSERT INTO file_fts(rowid, filename, content, tags) "
                        "VALUES (:rowid, :filename, :content, :tags)"
                    ),
                    {"rowid": file_id, "filename": filename, "content": content, "tags": tags},
                )
                return
            with self.engine.begin() as connection:
                connection.execute(text("DELETE FROM file_fts WHERE rowid = :rowid"), {"rowid": file_id})
                connection.execute(
                    text(
                        "INSERT INTO file_fts(rowid, filename, content, tags) "
                        "VALUES (:rowid, :filename, :content, :tags)"
                    ),
                    {"rowid": file_id, "filename": filename, "content": content, "tags": tags},
                )

    def upsert_fts_many(self, rows: Sequence[tuple[int, str, str, str]]) -> None:
        """Insert or replace FTS rows in one batched write."""

        with self._lock:
            if not rows:
                return
            delete = text("DELETE FROM file_fts WHERE rowid = :rowid")
            insert = text(
                "INSERT INTO file_fts(rowid, filename, content, tags) "
                "VALUES (:rowid, :filename, :content, :tags)"
            )
            params = [
                {
                    "rowid": file_id,
                    "filename": filename,
                    "content": content,
                    "tags": tags,
                }
                for file_id, filename, content, tags in rows
            ]
            shared = self._batch.get()
            if shared is not None:
                shared.execute(delete, params)
                shared.execute(insert, params)
                return
            with self.engine.begin() as connection:
                connection.execute(delete, params)
                connection.execute(insert, params)

    def delete_fts(self, file_id: int) -> None:
        with self._lock:
            shared = self._batch.get()
            if shared is not None:
                shared.execute(text("DELETE FROM file_fts WHERE rowid = :rowid"), {"rowid": file_id})
                return
            with self.engine.begin() as connection:
                connection.execute(text("DELETE FROM file_fts WHERE rowid = :rowid"), {"rowid": file_id})

    @staticmethod
    def _validate_backup(backup_file: Path) -> None:
        if not backup_file.is_file():
            raise DatabaseError(f"Backup file not found: {backup_file}")
        try:
            connection = sqlite3.connect(
                f"{backup_file.resolve().as_uri()}?mode=ro", uri=True
            )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Backup file is not readable: {exc}") from exc
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                detail = result[0] if result else "no result"
                raise DatabaseError(f"Backup file failed SQLite quick_check: {detail}")
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing = CORE_TABLES - names
            if missing:
                raise DatabaseError(
                    f"Backup file is missing core tables: {', '.join(sorted(missing))}"
                )
            for table, required in REQUIRED_COLUMNS.items():
                actual = {
                    row[1] for row in connection.execute(f"PRAGMA table_info({table})")
                }
                missing_columns = required - actual
                if missing_columns:
                    raise DatabaseError(
                        f"Backup file is missing required columns in {table}: "
                        f"{', '.join(sorted(missing_columns))}"
                    )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Backup file is not a valid SQLite database: {exc}") from exc
        finally:
            connection.close()

    def backup(self, destination: Path) -> Path:
        """Create a consistent SQLite backup using the online backup API.

        Returns:
            Path of the backup file.
        """

        with self._lock:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if self._is_memory:
                raise DatabaseError("In-memory databases cannot be backed up.")
            try:
                destination.open("xb").close()
            except FileExistsError as exc:
                raise DatabaseError(f"Backup already exists: {destination}") from exc

            source = sqlite3.connect(self.url.split("sqlite:///", 1)[-1])
            try:
                target = sqlite3.connect(str(destination))
                try:
                    source.backup(target)
                finally:
                    target.close()
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            finally:
                source.close()
            return destination

    def restore(self, backup_file: Path) -> None:
        """Replace the live database with a validated backup copy.

        The application must be restarted after restoring; callers should warn
        the user accordingly.
        """

        with self._lock:
            self._validate_backup(backup_file)
            if self._is_memory:
                raise DatabaseError("In-memory databases cannot be restored.")
            path = Path(self.url.split("sqlite:///", 1)[-1])
            self.engine.dispose()

            try:
                checkpoint = sqlite3.connect(path)
                try:
                    result = checkpoint.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                finally:
                    checkpoint.close()
            except (OSError, sqlite3.Error) as exc:
                raise DatabaseError(f"Could not checkpoint database before restore: {exc}") from exc
            if result is None or result[0] != 0:
                raise DatabaseError(
                    "Could not checkpoint database before restore: the database is in use"
                )

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            safety = path.with_name(f"{path.name}.pre-restore-{stamp}.db")
            try:
                source = sqlite3.connect(path)
                target = sqlite3.connect(safety)
                try:
                    source.backup(target)
                finally:
                    target.close()
                    source.close()

                source = sqlite3.connect(f"{backup_file.resolve().as_uri()}?mode=ro", uri=True)
                target = sqlite3.connect(path)
                try:
                    source.backup(target)
                finally:
                    target.close()
                    source.close()
            except (OSError, sqlite3.Error) as exc:
                raise DatabaseError(f"Could not restore database: {exc}") from exc
            self.engine.dispose()

    def integrity_check(self) -> bool:
        """Run SQLite's ``PRAGMA integrity_check``."""

        with self.engine.connect() as connection:
            result = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        return result == "ok"

    def dispose(self) -> None:
        self.engine.dispose()
