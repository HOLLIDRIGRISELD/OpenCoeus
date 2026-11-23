"""Float64 BLOB embedding storage and post-purge compaction."""

from __future__ import annotations

import json

import numpy as np
from sqlalchemy import text

from app.services.context import AppContext
from tests.conftest import write_text


def _analyse_one(context: AppContext, tmp_path):
    root = tmp_path / "library"
    path = write_text(
        root / "invoice.txt",
        "INVOICE\nInvoice number: INV-1\nAmount due: 9.00\nVendor: Acme Ltd\n",
    )
    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.analysed == 1
    return path


def test_embeddings_are_stored_bit_identically_as_float64_blobs(
    context: AppContext, tmp_path
) -> None:
    _analyse_one(context, tmp_path)

    with context.db.engine.connect() as connection:
        rows = connection.execute(text("SELECT dimension, vector FROM embedding_blobs")).all()
        json_count = connection.execute(text("SELECT COUNT(*) FROM embeddings")).scalar()
    assert rows
    assert json_count == 0

    dimension, blob = rows[0]
    assert len(blob) == dimension * 8
    stored = np.frombuffer(blob, dtype="<f8")
    assert np.all(np.isfinite(stored))

    loaded = context.analyses.load_embeddings(context.embeddings.model_name)
    assert np.array_equal(stored, np.asarray(loaded[0][1], dtype=np.float64))


def test_legacy_json_embeddings_remain_readable(context: AppContext, tmp_path) -> None:
    _analyse_one(context, tmp_path)
    model = context.embeddings.model_name

    with context.db.engine.begin() as connection:
        file_id, chunk_id = connection.execute(
            text("SELECT file_id, chunk_id FROM embedding_blobs LIMIT 1")
        ).one()
        connection.execute(text("DELETE FROM embedding_blobs"))
        connection.execute(
            text(
                "INSERT INTO embeddings (file_id, chunk_id, model_name, dimension, vector, created_at) "
                "VALUES (:file_id, :chunk_id, :model, 3, :vector, CURRENT_TIMESTAMP)"
            ),
            {
                "file_id": file_id,
                "chunk_id": chunk_id,
                "model": model,
                "vector": json.dumps([0.125, 0.5, 0.75]),
            },
        )

    loaded = context.analyses.load_embeddings(model)
    assert loaded
    assert np.allclose(loaded[0][1], [0.125, 0.5, 0.75])
    assert context.analyses.mean_document_vector(file_id, model) is not None


def test_exact_text_cache_uses_float64_blobs(context: AppContext) -> None:
    import numpy as np

    vector = np.linspace(-1.0, 1.0, 8, dtype=np.float64)
    model = context.embeddings.model_name
    context.embedding_cache.set_many(model, {"hash-1": vector})

    with context.db.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT dimension, vector FROM embedding_cache_blobs")
        ).all()
        legacy = connection.execute(text("SELECT COUNT(*) FROM embedding_cache")).scalar()
    assert rows
    assert legacy == 0
    dimension, blob = rows[0]
    assert len(blob) == dimension * 8
    assert np.array_equal(np.frombuffer(blob, dtype="<f8"), vector)

    loaded = context.embedding_cache.get_many(model, ["hash-1"])
    assert np.array_equal(loaded["hash-1"].astype(np.float64), vector)


def test_purge_compacts_the_database(
    context: AppContext, monkeypatch, tmp_path
) -> None:
    path = write_text(tmp_path / "indexed.txt", "indexed content")
    context.scanning.scan(path.parent)
    calls: list[int] = []
    original = context.db.vacuum
    monkeypatch.setattr(context.db, "vacuum", lambda: calls.append(1) or original())

    assert context.db.purge_session_data() > 0
    assert len(calls) == 1


def test_empty_purge_skips_vacuum(context: AppContext, monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(context.db, "vacuum", lambda: calls.append(1))

    assert context.db.purge_session_data() == 0
    assert calls == []


def test_embedding_cache_prune_keeps_newest(context: AppContext) -> None:
    model = context.embeddings.model_name
    vectors = {
        f"hash-{index}": np.full(8, index, dtype=np.float64) for index in range(5)
    }
    context.embedding_cache.set_many(model, vectors)

    with context.db.engine.begin() as connection:
        for index in range(5):
            connection.execute(
                text(
                    "UPDATE embedding_cache_blobs SET created_at = :stamp "
                    "WHERE text_hash = :text_hash"
                ),
                {"stamp": f"2026-01-01 00:00:0{index}", "text_hash": f"hash-{index}"},
            )

    assert context.embedding_cache.prune(max_entries=2) == 3
    remaining = context.embedding_cache.get_many(model, list(vectors))
    assert set(remaining) == {"hash-3", "hash-4"}


def test_analysis_triggers_cache_prune(
    context: AppContext, monkeypatch, tmp_path
) -> None:
    calls: list[int] = []
    original = context.embeddings.prune_cache
    monkeypatch.setattr(
        context.embeddings, "prune_cache", lambda: calls.append(1) or original()
    )

    _analyse_one(context, tmp_path)

    assert calls == [1]
