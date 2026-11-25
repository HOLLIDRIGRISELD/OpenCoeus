"""Configuration, database bootstrap, FTS index and repository primitives."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import AppConfig
from app.core.exceptions import DatabaseError
from app.infrastructure.database import Database
from app.infrastructure.repositories.settings import (
    RuleRepository,
    ScanSessionRepository,
    SettingsRepository,
)


def test_config_creates_directories_and_derives_paths(tmp_path: Path) -> None:
    data = tmp_path / "data"
    config = AppConfig(data_dir=data, prefer_transformer=False, enable_llm=False)

    assert config.db_url == f"sqlite:///{data / 'opencoeus.db'}"
    assert config.db_path == data / "opencoeus.db"
    assert config.backup_dir == data / "backups"
    assert config.log_dir == data / "logs"

    config.ensure_directories()
    assert data.is_dir()
    assert config.backup_dir.is_dir()
    assert config.log_dir.is_dir()


def test_database_seeds_categories_settings_and_integrity(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()

    assert db.integrity_check() is True

    repo = SettingsRepository(db)
    assert repo.get("app.theme") == "dark"
    assert repo.get_float("search.alpha", 0.0) == pytest.approx(0.4)
    assert repo.get_bool("app.enable_llm", True) is True
    assert repo.get("app.enable_llm") is None

    with db.session() as session:
        from sqlalchemy import func, select

        from app.infrastructure.models import Category, Setting

        categories = session.scalar(select(func.count(Category.id)))
        settings = session.scalar(select(func.count(Setting.key)))

    assert categories == 23
    assert settings >= 4
    db.dispose()


def test_create_schema_makes_current_path_unique_and_quarantines_legacy_duplicates(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'duplicates.db'}")
    db.create_schema()

    with db.engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS ux_files_current_path"))
        for file_id in (7101, 7102):
            connection.execute(
                text(
                    "INSERT INTO files (id, original_name, current_name, original_path, "
                    "current_path, extension, file_size, processing_status, is_available, "
                    "created_record_at, updated_record_at) "
                    "VALUES (:id, 'legacy.txt', 'legacy.txt', '/legacy/legacy.txt', "
                    "'/legacy/legacy.txt', '.txt', 10, 'analysed', 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": file_id},
            )
            connection.execute(
                text(
                    "INSERT INTO document_analyses (file_id, classification_method, "
                    "analysis_status, created_at) "
                    "VALUES (:id, 'test', 'completed', CURRENT_TIMESTAMP)"
                ),
                {"id": file_id},
            )

    db.create_schema()

    with db.engine.connect() as connection:
        indexes = connection.execute(text("PRAGMA index_list('files')")).all()
        kept = connection.execute(
            text("SELECT id FROM files WHERE current_path = '/legacy/legacy.txt'")
        ).scalars().all()
        total = connection.execute(text("SELECT COUNT(*) FROM files")).scalar_one()
        analyses = connection.execute(
            text("SELECT COUNT(*) FROM document_analyses")
        ).scalar_one()
    assert any(name == "ux_files_current_path" and unique == 1 for _, name, unique, *_ in indexes)
    assert list(kept) == [7101]
    assert total == 2
    assert analyses == 2
    db.dispose()


def test_fts_upsert_search_and_delete(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'fts.db'}")
    db.create_schema()
    with db.session() as session:
        from app.infrastructure.models import File

        record = File(
            original_name="invoice.txt",
            current_name="invoice.txt",
            original_path="/tmp/invoice.txt",
            current_path="/tmp/invoice.txt",
            extension=".txt",
            file_size=10,
            processing_status="analysed",
        )
        session.add(record)
        session.flush()
        file_id = record.id

    db.upsert_fts(file_id, "invoice.txt", "Amount due one thousand", "finance invoice")
    with db.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT rowid FROM file_fts WHERE file_fts MATCH 'invoice'")
        ).all()
    assert [row[0] for row in rows] == [file_id]

    db.delete_fts(file_id)
    with db.engine.connect() as connection:
        remaining = connection.execute(text("SELECT count(*) FROM file_fts")).scalar_one()
    assert remaining == 0
    db.dispose()


def test_backup_and_restore_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "live.db"
    db = Database(f"sqlite:///{path}")
    db.create_schema()
    settings = SettingsRepository(db)
    settings.set("app.theme", "light")

    backup = db.backup(tmp_path / "backups" / "copy.db")
    assert backup.is_file()

    settings.set("app.theme", "dark")
    assert settings.get("app.theme") == "dark"

    db.restore(backup)

    reopened = Database(f"sqlite:///{path}")
    assert SettingsRepository(reopened).get("app.theme") == "light"
    reopened.dispose()
    db.dispose()


def test_in_memory_database_cannot_be_backed_up() -> None:
    db = Database("sqlite:///:memory:")
    db.create_schema()
    with pytest.raises(DatabaseError):
        db.backup(Path("/tmp/should-not-exist.db"))
    db.dispose()


def test_settings_repository_typed_accessors(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'typed.db'}")
    db.create_schema()
    repo = SettingsRepository(db)

    repo.set("example.int", "42")
    repo.set("example.bool", "yes")
    repo.set("example.float", "1.5")
    repo.set("example.broken", "not-a-number")

    assert repo.get_int("example.int", 0) == 42
    assert repo.get_bool("example.bool", False) is True
    assert repo.get_float("example.float", 0.0) == pytest.approx(1.5)
    assert repo.get_int("example.broken", 7) == 7
    assert repo.get("missing", "fallback") == "fallback"
    db.dispose()


def test_new_categories_are_seeded(context) -> None:
    descriptions = context.analyses.category_descriptions()

    for path in (
        "Government/Reports",
        "Finance/Expenses",
        "Technical/Source Code",
        "Technical/Web Pages",
        "Personal/Calendar",
    ):
        assert path in descriptions
        assert descriptions[path].strip()


def test_rule_repository_crud(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'rules.db'}")
    db.create_schema()
    rules = RuleRepository(db)

    rule_id = rules.add_rule(
        name="Invoices from Acme",
        match_field="content",
        match_op="contains",
        match_value="Acme",
        target_folder="Finance/Invoices",
    )
    stored = rules.list_rules()
    assert [rule["id"] for rule in stored] == [rule_id]
    assert stored[0]["enabled"] is True

    rules.set_enabled(rule_id, False)
    assert rules.list_rules(enabled_only=True) == []

    rules.delete_rule(rule_id)
    assert rules.list_rules() == []
    db.dispose()


def test_scan_session_repository_records_outcome(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'sessions.db'}")
    db.create_schema()
    sessions = ScanSessionRepository(db)

    session_id = sessions.start(tmp_path)
    sessions.finish(session_id, discovered=3, processed=3, failed=0)
    recent = sessions.recent()

    assert recent[0]["id"] == session_id
    assert recent[0]["status"] == "completed"
    assert recent[0]["discovered"] == 3
    assert recent[0]["finished_at"] is not None
    db.dispose()
