"""Concurrency safety for the in-memory embedding cache."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from app.intelligence import embeddings as embeddings_module
from app.intelligence.embeddings import EmbeddingEngine


def test_concurrent_encode_initialises_one_backend_and_keeps_cache_consistent(
    monkeypatch,
) -> None:
    inits: list[object] = []

    class SlowBackend:
        name = "fake"
        dimension = 2
        is_semantic = False

        def __init__(self, model_name: str) -> None:
            inits.append(self)
            time.sleep(0.02)

        def encode(self, texts):
            return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1))

    monkeypatch.setattr(embeddings_module, "SentenceTransformerBackend", SlowBackend)
    engine = EmbeddingEngine("fake", prefer_transformer=True, cache_limit=1)
    barrier = threading.Barrier(2)
    results: dict[str, np.ndarray] = {}
    errors: list[Exception] = []

    def worker(key: str, text: str) -> None:
        try:
            barrier.wait()
            results[key] = engine.encode([text])
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("first", "alpha")),
        threading.Thread(target=worker, args=("second", "beta")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert errors == []
    assert len(inits) == 1
    np.testing.assert_allclose(results["first"], [[1.0, 0.0]])
    np.testing.assert_allclose(results["second"], [[1.0, 0.0]])


def test_hashing_backend_reuses_feature_digests(monkeypatch) -> None:
    from app.intelligence.embeddings import HashingEmbeddingBackend

    original = embeddings_module.hashlib.blake2b
    hashed: list[bytes] = []

    def counting_blake2b(data: bytes, **kwargs: object):
        hashed.append(data)
        return original(data, **kwargs)

    monkeypatch.setattr(embeddings_module.hashlib, "blake2b", counting_blake2b)
    backend = HashingEmbeddingBackend(["alpha beta gamma", "beta gamma delta"])
    text = "alpha beta gamma delta"
    first = backend.encode([text])
    after_first = len(hashed)

    second = backend.encode([text])

    assert after_first > 0
    assert len(hashed) == after_first
    np.testing.assert_array_equal(first, second)


def test_corpus_change_invalidates_vector_reuse() -> None:
    uses: list[str] = []

    class RecordingCache:
        def get_many(self, model_name, text_hashes):
            uses.append(f"get:{model_name}")
            return {}

        def set_many(self, model_name, vectors):
            uses.append(f"set:{model_name}")

    cache = RecordingCache()
    first = EmbeddingEngine(
        "hash",
        prefer_transformer=False,
        cache=cache,
        corpus_provider=lambda: ["alpha beta document"],
    )
    base_name = first.model_name
    first_vector = first.encode(["alpha beta document"])[0]

    second = EmbeddingEngine(
        "hash",
        prefer_transformer=False,
        cache=cache,
        corpus_provider=lambda: ["gamma delta document"],
    )

    assert base_name.startswith("opencoeus-hash-ngram-384-v2-idf-")
    assert second.model_name != base_name
    second_vector = second.encode(["alpha beta document"])[0]
    assert not np.allclose(first_vector, second_vector)
    assert f"set:{base_name}" in uses
    assert f"set:{second.model_name}" in uses


def test_corpus_baseline_survives_engine_reconstruction() -> None:
    storage: dict[tuple[str, str], np.ndarray] = {}

    class DictCache:
        def get_many(self, model_name, text_hashes):
            return {
                key: storage[(model_name, key)]
                for key in text_hashes
                if (model_name, key) in storage
            }

        def set_many(self, model_name, vectors):
            for key, vector in vectors.items():
                storage[(model_name, key)] = vector

    first = EmbeddingEngine(
        "hash",
        prefer_transformer=False,
        cache=DictCache(),
        corpus_provider=lambda: ["alpha beta document"],
    )
    first_name = first.model_name
    first.encode(["alpha beta document"])

    second = EmbeddingEngine(
        "hash",
        prefer_transformer=False,
        cache=DictCache(),
        corpus_provider=lambda: ["gamma delta document"],
    )

    assert second.model_name != first_name


def test_embedding_corpus_order_is_stable(tmp_path: Path) -> None:
    from app.infrastructure.database import Database
    from app.infrastructure.models import DocumentContent, File
    from app.infrastructure.repositories.analysis import AnalysisRepository

    db = Database(f"sqlite:///{tmp_path / 'corpus.db'}")
    db.create_schema()
    with db.session() as session:
        first = File(
            original_name="a.txt",
            current_name="a.txt",
            original_path="/tmp/a.txt",
            current_path="/tmp/a.txt",
            extension=".txt",
            file_size=20,
            processing_status="analysed",
        )
        second = File(
            original_name="b.txt",
            current_name="b.txt",
            original_path="/tmp/b.txt",
            current_path="/tmp/b.txt",
            extension=".txt",
            file_size=20,
            processing_status="analysed",
        )
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                DocumentContent(file_id=second.id, text="bravo corpus text"),
                DocumentContent(file_id=first.id, text="alpha corpus text"),
            ]
        )

    corpus = AnalysisRepository(db).embedding_corpus()
    assert corpus[-2:] == ["alpha corpus text", "bravo corpus text"]
    db.dispose()


def test_feature_cache_is_bounded() -> None:
    from app.intelligence.embeddings import _CACHE_LIMIT, HashingEmbeddingBackend

    backend = HashingEmbeddingBackend()
    for index in range(_CACHE_LIMIT + 50):
        backend._cached_feature(f"feature-{index}")

    assert len(backend._feature_cache) <= _CACHE_LIMIT


def test_encode_releases_lock_before_persistent_cache_db_calls() -> None:
    db_lock = threading.RLock()
    cache_entered = threading.Event()
    db_held = threading.Event()

    class SlowDbCache:
        def get_many(self, model_name, text_hashes):
            cache_entered.set()
            db_held.wait(timeout=5)
            if db_lock.acquire(timeout=2):
                db_lock.release()
            return {}

        def set_many(self, model_name, vectors):
            if db_lock.acquire(timeout=2):
                db_lock.release()

    class Backend:
        name = "fake"
        dimension = 2
        is_semantic = False

        def encode(self, texts):
            return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1))

    engine = EmbeddingEngine("fake", backend=Backend(), cache=SlowDbCache())
    engine._cache["alpha"] = np.array([1.0, 0.0], dtype=np.float32)
    results: dict[str, np.ndarray] = {}
    errors: list[Exception] = []

    def analysis_side() -> None:
        try:
            with db_lock:
                db_held.set()
                results["alpha"] = engine.encode(["alpha"])
        except Exception as exc:
            errors.append(exc)

    def search_side() -> None:
        try:
            results["beta"] = engine.encode(["beta"])
        except Exception as exc:
            errors.append(exc)

    search = threading.Thread(target=search_side)
    search.start()
    assert cache_entered.wait(timeout=5)
    analysis = threading.Thread(target=analysis_side)
    analysis.start()
    try:
        analysis.join(timeout=1)
        search.join(timeout=1)
        assert not analysis.is_alive() and not search.is_alive(), "encode lock inversion"
    finally:
        analysis.join(timeout=5)
        search.join(timeout=5)

    assert errors == []
    np.testing.assert_allclose(results["alpha"], [[1.0, 0.0]])
    np.testing.assert_allclose(results["beta"], [[1.0, 0.0]])
