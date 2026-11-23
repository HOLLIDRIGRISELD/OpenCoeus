"""Database hot paths must use bounded statement counts and identical projections."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from multiprocessing import get_context
from pathlib import Path

import pytest
from sqlalchemy import event, text

from app.core.constants import DEFAULT_CATEGORIES, UNCLASSIFIED
from app.core.exceptions import DatabaseError
from app.services.context import AppContext
from tests.conftest import write_text


@contextmanager
def statements(engine) -> Iterator[list[int]]:
    count: list[int] = [0]

    def before_cursor_execute(
        _conn, _cursor, _statement, _parameters, _context, _executemany
    ) -> None:
        count[0] += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield count
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def _seed_library(context: AppContext, root: Path, size: int) -> None:
    for index in range(size):
        write_text(
            root / f"doc_{index:03d}.txt",
            f"INVOICE\nVendor: Acme Ltd {index}\nAmount due: 10.00\n",
        )
    context.scanning.scan(root)
    context.analysis.analyse_pending(use_llm=False)


def test_file_mutations_reject_missing_rows(context: AppContext) -> None:
    missing = 10**9

    with pytest.raises(DatabaseError):
        context.files.update_status(missing, "analysed")
    with pytest.raises(DatabaseError):
        context.files.mark_missing(missing)
    with pytest.raises(DatabaseError):
        context.files.update_location(missing, Path("elsewhere.txt"))
    with pytest.raises(DatabaseError):
        context.files.set_hash(missing, "0" * 64)

    assert context.files.get_summary(missing) is None
    assert context.files.get_record(missing) is None


def test_analysis_mutations_reject_missing_rows(context: AppContext) -> None:
    missing = 10**9

    with pytest.raises(DatabaseError):
        context.analyses.override_category(missing, "Finance", note="review")
    with pytest.raises(DatabaseError):
        context.analyses.set_tags(missing, ["invoice"])
    with pytest.raises(DatabaseError):
        context.analyses.delete_tags(missing)
    with pytest.raises(DatabaseError):
        context.analyses.delete_embeddings(missing)
    with pytest.raises(DatabaseError):
        context.analyses.set_suggestion_status(missing, "accepted")

    assert context.analyses.latest_analysis(missing) is None
    assert context.analyses.suggestion_status(missing) is None


def test_list_summaries_uses_bounded_statements(
    context: AppContext, tmp_path: Path
) -> None:
    _seed_library(context, tmp_path / "library", 200)

    with statements(context.db.engine) as count:
        rows = context.files.list_summaries(limit=200)

    assert len(rows) == 200
    assert count[0] <= 10


def test_fingerprint_set_many_uses_one_statement(context: AppContext) -> None:
    items = [(f"library/path_{index}", 10, index, f"hash-{index}") for index in range(50)]

    with statements(context.db.engine) as count:
        context.file_fingerprints.set_many(items)

    assert count[0] == 1
    cached = context.file_fingerprints.all_for_root("library/")
    assert len(cached) == 50
    assert cached["library/path_7"] == (10, 7, "hash-7")


def test_performance_indexes_exist(context: AppContext) -> None:
    with context.db.engine.connect() as connection:
        names = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index'")
            ).scalars()
        )
    assert {
        "ix_da_file_id_id",
        "ix_files_status_path",
        "ix_plan_items_file_latest",
    } <= names


def test_fts_rebuild_preserves_raw_columns(
    context: AppContext, analysed_library: Path
) -> None:
    def rows() -> list[tuple[object, ...]]:
        with context.db.engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT rowid, filename, content, tags FROM file_fts ORDER BY rowid")
                )
            )

    before = rows()
    assert before
    context.indexer.rebuild()
    assert rows() == before


def _bootstrap_worker(path: Path, ready, start, errors) -> None:  # type: ignore[no-untyped-def]
    from app.infrastructure.database import Database

    try:
        db = Database(f"sqlite:///{path}")
        ready.set()
        if not start.wait(30):
            return
        db.create_schema()
        db.dispose()
    except Exception as exc:  # pragma: no cover - reported through the queue
        errors.put(f"{type(exc).__name__}: {exc}")


def test_concurrent_bootstrap_seeds_once_without_partial_schema(tmp_path: Path) -> None:
    path = tmp_path / "shared.db"
    mp = get_context("spawn")
    ready = mp.Event()
    start = mp.Event()
    errors = mp.Queue()
    workers = [
        mp.Process(target=_bootstrap_worker, args=(path, ready, start, errors))
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        assert all(ready.wait(30) for worker in workers)
        start.set()
        for worker in workers:
            worker.join(30)
            assert worker.exitcode == 0
        assert errors.empty(), errors.get(timeout=1)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(5)

    with sqlite3.connect(path) as connection:
        categories = connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        settings = connection.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        duplicates = connection.execute(
            "SELECT name FROM categories GROUP BY name, parent_id HAVING COUNT(*) > 1"
        ).fetchall()
        unclassified = connection.execute(
            "SELECT COUNT(*) FROM categories WHERE name = ? AND parent_id IS NULL",
            (UNCLASSIFIED,),
        ).fetchone()[0]

    expected = len({entry[0] for entry in DEFAULT_CATEGORIES}) + len(DEFAULT_CATEGORIES) + 1
    assert categories == expected, (categories, expected)
    assert settings == 4
    assert {"settings", "categories", "files", "file_fts", "batch_executions"} <= tables
    assert duplicates == []
    assert unclassified == 1
