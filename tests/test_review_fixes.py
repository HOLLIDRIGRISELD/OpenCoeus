"""Regression guards for review findings on mixed storage and extraction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy import text

from app.core.constants import STATUS_ANALYSING, STATUS_PENDING_ANALYSIS
from app.core.exceptions import DatabaseError
from app.domain.enums import PlanStatus
from app.domain.models import ScannedFile
from app.processing.extractors.text import TextExtractor
from app.search.semantic import SemanticSearch
from app.services.context import AppContext
from tests.conftest import write_text


def _analyse(context: AppContext, root: Path, names: list[str]) -> None:
    for name in names:
        write_text(root / name, f"INVOICE {name}\nAmount due: 12.00\nVendor: Acme Ltd\n")
    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.analysed == len(names)


def test_semantic_embeddings_merge_legacy_and_blob_rows(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    _analyse(context, root, ["one.txt", "two.txt"])
    model = context.embeddings.model_name

    with context.db.engine.begin() as connection:
        legacy_id = connection.execute(text("SELECT MIN(id) FROM files")).scalar()
        chunk_id = connection.execute(
            text("SELECT id FROM document_chunks WHERE file_id = :id LIMIT 1"), {"id": legacy_id}
        ).scalar()
        connection.execute(
            text("DELETE FROM embedding_blobs WHERE file_id = :id"), {"id": legacy_id}
        )
        connection.execute(
            text(
                "INSERT INTO embeddings (file_id, chunk_id, model_name, dimension, vector, created_at) "
                "VALUES (:file_id, :chunk_id, :model, 3, :vector, CURRENT_TIMESTAMP)"
            ),
            {
                "file_id": legacy_id,
                "chunk_id": chunk_id,
                "model": model,
                "vector": json.dumps([0.1, 0.2, 0.3]),
            },
        )

    loaded = context.analyses.load_embeddings(model)
    assert {file_id for file_id, _, _ in loaded} == {1, 2}


def test_exact_text_cache_merges_legacy_and_blob_rows(context: AppContext) -> None:
    model = context.embeddings.model_name
    blob_vector = np.linspace(0.0, 1.0, 8, dtype=np.float64)
    legacy_vector = [0.125, 0.25, 0.5, 0.75]
    context.embedding_cache.set_many(model, {"blob-hash": blob_vector})

    with context.db.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO embedding_cache (model_name, text_hash, dimension, vector, created_at) "
                "VALUES (:model, :hash, 4, :vector, CURRENT_TIMESTAMP)"
            ),
            {
                "model": model,
                "hash": "legacy-hash",
                "vector": json.dumps(legacy_vector),
            },
        )

    loaded = context.embedding_cache.get_many(model, ["blob-hash", "legacy-hash"])
    assert set(loaded) == {"blob-hash", "legacy-hash"}
    assert np.allclose(loaded["legacy-hash"], legacy_vector)


def test_text_extractor_replaces_invalid_bytes_after_first_chunk(tmp_path: Path) -> None:
    path = tmp_path / "mixed.txt"
    path.write_bytes(b"a" * 1_048_576 + b"\xff" + b"b" * 16)

    result = TextExtractor().extract(path)

    assert result.success
    assert len(result.text) > 1_048_576
    assert any("replaced" in warning for warning in result.warnings)


def test_text_extractor_keeps_text_after_large_leading_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "spaces.txt"
    path.write_text(" " * 3_000_000 + "INVOICE 123", encoding="utf-8")

    result = TextExtractor().extract(path)

    assert result.text == "INVOICE 123"


def test_purge_survives_vacuum_failure(context: AppContext, tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "library"
    _analyse(context, root, ["one.txt"])
    monkeypatch.setattr(context.db, "vacuum", lambda: (_ for _ in ()).throw(DatabaseError("full disk")))

    context.db.purge_session_data()

    with context.db.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM files")).scalar() == 0


def test_recovery_vacuum_delegates_to_database(context: AppContext, monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(context.db, "vacuum", lambda: calls.append(1))

    context.recovery.vacuum()

    assert calls == [1]


def test_count_helpers_match_filtered_pages(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    _analyse(context, root, ["one.txt", "two.txt"])

    assert context.files.count_summaries(status="analysed") == len(
        context.files.list_summaries(limit=10**9, status="analysed")
    )
    assert context.files.count_summaries(text_filter="one") == len(
        context.files.list_summaries(limit=10**9, text_filter="one")
    )
    assert context.recommendations.pending_count() == len(
        context.recommendations.pending(limit=10**9)
    )


def test_upsert_many_splits_large_scan_batches(context: AppContext) -> None:
    now = datetime.now(UTC)
    items = [
        ScannedFile(
            path=Path(f"/virtual/doc-{index}.txt"),
            relative_path=Path(f"doc-{index}.txt"),
            filename=f"doc-{index}.txt",
            extension=".txt",
            size=1,
            modified_at=now,
            created_at=now,
        )
        for index in range(600)
    ]

    batch = [(scanned, "discovered") for scanned in items]
    created = context.files.upsert_many(batch)

    assert len(created) == 600
    assert all(is_new for _, is_new in created)
    assert context.files.count_summaries() == 600
    assert all(not is_new for _, is_new in context.files.upsert_many(batch))


def test_startup_resets_interrupted_plans_and_files(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    path = write_text(root / "one.txt", "INVOICE\n")
    context.scanning.scan(root)
    file_id = context.files.find_by_path(path)
    assert file_id is not None
    context.files.update_status(file_id, STATUS_ANALYSING)
    plan_id = context.operations.create_plan(root, [])
    context.operations.update_plan_status(plan_id, PlanStatus.EXECUTING)

    restarted = AppContext(context.config, purge=False)
    try:
        plan = restarted.operations.get_plan(plan_id)
        summary = restarted.files.get_summary(file_id)
        assert plan is not None
        assert plan["status"] == PlanStatus.REVALIDATION_REQUIRED.value
        assert summary is not None
        assert summary.status == STATUS_PENDING_ANALYSIS
    finally:
        restarted.close()


def test_semantic_search_loads_embeddings_before_scoring(
    context: AppContext, monkeypatch
) -> None:
    class FakeAnalyses:
        def iter_embeddings(self, model: str):  # type: ignore[no-untyped-def]
            raise AssertionError("streaming embeddings would hold the database lock")

        def load_embeddings(self, model: str):  # type: ignore[no-untyped-def]
            return [(1, np.ones(4), "invoice payment")]

    class FakeEmbeddings:
        model_name = "fake"

        def encode_one(self, query: str):  # type: ignore[no-untyped-def]
            return np.ones(4)

    search = SemanticSearch(FakeAnalyses(), FakeEmbeddings())  # type: ignore[arg-type]
    monkeypatch.setattr(search, "_paths", lambda file_ids: {1: ("one.txt", "one.txt")})

    hits = search.search("payment")

    assert [hit.file_id for hit in hits] == [1]
