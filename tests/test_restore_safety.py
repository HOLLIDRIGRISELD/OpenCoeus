"""Restore must validate its input and preserve a way back."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest

from app.cli import cmd_restore, cmd_root
from app.core.exceptions import DatabaseError
from app.infrastructure.database import Database
from app.infrastructure.repositories.settings import SettingsRepository


def _live_db(tmp_path: Path) -> tuple[Database, Path]:
    path = tmp_path / "live.db"
    db = Database(f"sqlite:///{path}")
    db.create_schema()
    return db, path


def test_restore_rejects_invalid_file_without_touching_live_db(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    SettingsRepository(db).set("app.theme", "light")
    before = path.read_bytes()
    bad = tmp_path / "not-a-backup.db"
    bad.write_text("this is not a database", encoding="utf-8")

    with pytest.raises(DatabaseError, match="(?i)backup"):
        db.restore(bad)

    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.pre-restore-*.db")) == []
    db.dispose()


def test_restore_rejects_backup_missing_core_tables(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    before = path.read_bytes()
    partial = tmp_path / "partial.db"
    with sqlite3.connect(partial) as connection:
        connection.execute("CREATE TABLE files (id INTEGER PRIMARY KEY)")

    with pytest.raises(DatabaseError, match="tables"):
        db.restore(partial)

    assert path.read_bytes() == before
    db.dispose()


def test_restore_rejects_backup_missing_required_column(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    before = path.read_bytes()
    partial = db.backup(tmp_path / "missing-column.db")
    with sqlite3.connect(partial) as connection:
        connection.execute("DROP TABLE files")
        connection.execute("CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT)")

    with pytest.raises(DatabaseError, match="column"):
        db.restore(partial)

    assert path.read_bytes() == before
    db.dispose()


def test_restore_rejects_backup_with_only_legacy_core_tables(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    before = path.read_bytes()
    legacy = tmp_path / "legacy.db"
    legacy_tables = (
        "files",
        "document_analyses",
        "organisation_plans",
        "operations",
        "settings",
    )
    with sqlite3.connect(legacy) as connection:
        for table in legacy_tables:
            connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")

    with pytest.raises(DatabaseError, match="tables"):
        db.restore(legacy)

    assert path.read_bytes() == before
    db.dispose()


def test_restore_with_active_reader_and_pending_wal_write_is_safe(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    SettingsRepository(db).set("app.theme", "light")
    backup = db.backup(tmp_path / "copy.db")
    db.dispose()

    writer = sqlite3.connect(path)
    writer.execute("UPDATE settings SET value = 'dark' WHERE key = 'app.theme'")
    writer.commit()
    reader = sqlite3.connect(path)
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM settings").fetchone()
    try:
        try:
            db.restore(backup)
        except DatabaseError:
            live = sqlite3.connect(path)
            try:
                theme = live.execute(
                    "SELECT value FROM settings WHERE key = 'app.theme'"
                ).fetchone()[0]
            finally:
                live.close()
            assert theme == "dark"
            assert list(tmp_path.glob("*.pre-restore-*.db")) == []
        else:
            copies = sorted(tmp_path.glob("*.pre-restore-*.db"))
            assert copies
            check = sqlite3.connect(copies[0])
            try:
                theme = check.execute(
                    "SELECT value FROM settings WHERE key = 'app.theme'"
                ).fetchone()[0]
            finally:
                check.close()
            assert theme == "dark"
    finally:
        reader.rollback()
        reader.close()
        writer.close()
        db.dispose()


def test_restore_replaces_live_db_and_keeps_pre_restore_copy(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    settings = SettingsRepository(db)
    settings.set("app.theme", "light")
    backup = db.backup(tmp_path / "copy.db")
    settings.set("app.theme", "dark")

    db.restore(backup)

    copies = sorted(tmp_path.glob("*.pre-restore-*.db"))
    assert len(copies) == 1
    previous = Database(f"sqlite:///{copies[0]}")
    assert SettingsRepository(previous).get("app.theme") == "dark"
    previous.dispose()
    reopened = Database(f"sqlite:///{path}")
    assert SettingsRepository(reopened).get("app.theme") == "light"
    reopened.dispose()
    db.dispose()


def test_backup_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    db, _path = _live_db(tmp_path)
    existing = tmp_path / "backup.db"
    existing.write_bytes(b"keep this backup")

    with pytest.raises(DatabaseError, match="(?i)already exists|exists"):
        db.backup(existing)

    assert existing.read_bytes() == b"keep this backup"
    db.dispose()


def test_cli_restore_reports_validation_failure_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backup = tmp_path / "bad.db"
    backup.write_bytes(b"not a database")

    class FailingRecovery:
        def restore(self, _path: Path) -> None:
            raise DatabaseError("Backup file is not a valid SQLite database: file is not a database")

    class FakeContext:
        recovery = FailingRecovery()

    args = argparse.Namespace(backup=str(backup), yes=True)

    assert cmd_restore(args, FakeContext()) == 1  # type: ignore[arg-type]
    assert "Restore failed" in capsys.readouterr().err


def test_restore_reports_checkpoint_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, path = _live_db(tmp_path)
    backup = db.backup(tmp_path / "copy.db")
    original_connect = sqlite3.connect

    def failing_connect(database: str, *args: object, **kwargs: object):
        if str(path) in str(database) and "mode=ro" not in str(database):
            raise sqlite3.OperationalError("database is locked")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr("app.infrastructure.database.sqlite3.connect", failing_connect)

    with pytest.raises(DatabaseError, match="checkpoint"):
        db.restore(backup)
    db.dispose()


def test_restore_with_stale_wal_and_shm_leaves_a_readable_database(tmp_path: Path) -> None:
    db, path = _live_db(tmp_path)
    SettingsRepository(db).set("app.theme", "light")
    backup = db.backup(tmp_path / "copy.db")
    SettingsRepository(db).set("app.theme", "dark")
    db.dispose()
    Path(f"{path}-wal").write_bytes(b"")
    Path(f"{path}-shm").write_bytes(b"")

    db.restore(backup)

    reopened = Database(f"sqlite:///{path}")
    assert SettingsRepository(reopened).get("app.theme") == "light"
    reopened.dispose()
    db.dispose()


def test_cli_root_reports_validation_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "library"
    root.mkdir()

    class FakeContext:
        def set_organisation_root(self, _root: Path) -> list[str]:
            return ["organisation.root must be an existing absolute directory."]

    args = argparse.Namespace(path=str(root))

    assert cmd_root(args, FakeContext()) == 1  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert "organisation.root" in captured.err
    assert "Organisation root set" not in captured.out
