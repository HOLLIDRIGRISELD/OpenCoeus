"""Text embeddings with an explicit, deterministic fallback.

Two backends are provided:

* ``SentenceTransformerBackend`` — the preferred semantic model, used when
  ``sentence-transformers`` and a compatible model are installed.
* ``HashingEmbeddingBackend`` — a dependency-free hashed n-gram vectoriser.

The fallback is not a substitute for a trained language model, but it is a real
feature-hashing technique: it keeps classification, clustering and semantic
search functional on machines that cannot run a transformer, and the model name
stored with every vector ensures the two representations are never mixed.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Protocol, runtime_checkable

import numpy as np

from app.core.logging_config import get_logger
from app.processing.hashing import sha256_text

logger = get_logger(__name__)

_WORD = re.compile(r"[a-z0-9][a-z0-9'’\-]*", re.IGNORECASE)
_CACHE_LIMIT = 4096


def _corpus_fingerprint(texts: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


@runtime_checkable
class EmbeddingCache(Protocol):
    """Persistent cache for vectors keyed by model and exact text hash."""

    def get_many(
        self, model_name: str, text_hashes: Sequence[str]
    ) -> Mapping[str, np.ndarray]:
        """Return cached vectors for the requested hashes that exist."""

    def set_many(self, model_name: str, vectors: Mapping[str, np.ndarray]) -> None:
        """Store vectors under their text hashes."""

    def prune(self, max_entries: int = 10_000) -> int:
        """Drop oldest rows above the cap; non-persistent caches may no-op."""
        return 0


def mean_vector(vectors: Sequence[np.ndarray]) -> np.ndarray:
    """Return the L2-normalised mean of already-computed vectors.

    An empty sequence yields a zero vector with dimension 1; callers treat it
    as "no semantic evidence" and fall back to their own encoding path.
    """

    if not vectors:
        return np.zeros(1, dtype=np.float32)
    stacked = np.vstack([np.asarray(vector, dtype=np.float32) for vector in vectors])
    averaged = stacked.mean(axis=0, dtype=np.float32)
    norm = float(np.linalg.norm(averaged))
    if norm > 0:
        averaged /= norm
    return averaged


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Minimal interface implemented by every embedding backend."""

    name: str
    dimension: int
    is_semantic: bool

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return a ``(len(texts), dimension)`` float32 matrix, L2-normalised."""


class HashingEmbeddingBackend:
    """Deterministic feature hashing with corpus-derived IDF weights.

    The document frequency of every word, bigram and character n-gram is learned
    once from the supplied corpus. Rare features therefore contribute more than
    boilerplate terms without a larger model or any per-document inference cost.
    """

    name = "opencoeus-hash-ngram-384-v2-idf"
    dimension = 384
    is_semantic = False

    def __init__(self, corpus_texts: Sequence[str] | None = None) -> None:
        documents = [set(self._features(text)) for text in corpus_texts or ()]
        total = max(1, len(documents))
        counts: dict[str, int] = {}
        for features in documents:
            for feature in features:
                counts[feature] = counts.get(feature, 0) + 1
        self._idf = {
            feature: 1.0 + float(np.log((1.0 + total) / (1.0 + count)))
            for feature, count in counts.items()
        }
        self._unseen_weight = 1.0 + float(np.log(1.0 + total))
        self._feature_cache: OrderedDict[str, tuple[int, float]] = OrderedDict()

    def _cached_feature(self, feature: str) -> tuple[int, float]:
        cached = self._feature_cache.get(feature)
        if cached is not None:
            self._feature_cache.move_to_end(feature)
            return cached
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % self.dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        cached = (bucket, sign * self.idf_weight(feature))
        self._feature_cache[feature] = cached
        if len(self._feature_cache) > _CACHE_LIMIT:
            self._feature_cache.popitem(last=False)
        return cached

    def idf_weight(self, feature: str) -> float:
        """Return the corpus IDF weight for a hashed feature."""

        return self._idf.get(feature, self._unseen_weight)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            vector = matrix[row]
            for feature in self._features(text):
                bucket, weight = self._cached_feature(feature)
                vector[bucket] += weight
            norm = float(np.linalg.norm(vector))
            if norm > 0:
                vector /= norm
        return matrix

    @staticmethod
    def _features(text: str) -> Iterable[str]:
        words = [match.group(0).lower() for match in _WORD.finditer(text)]
        if not words:
            yield "__empty__"
            return
        for word in words:
            yield f"w:{word}"
        for first, second in zip(words, words[1:], strict=False):
            yield f"b:{first}_{second}"
        for word in words:
            if len(word) >= 5:
                for index in range(len(word) - 3):
                    yield f"c:{word[index:index + 4]}"


class SentenceTransformerBackend:
    """Wrapper around ``sentence-transformers``."""

    is_semantic = True

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self._model = SentenceTransformer(model_name)
        self.name = model_name
        self.dimension = int(self._model.get_sentence_embedding_dimension() or 384)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = self._model.encode(
            list(texts),
            batch_size=16,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class EmbeddingEngine:
    """Facade that selects a backend and caches per-text vectors.

    Args:
        model_name: Requested Sentence-Transformers model.
        prefer_transformer: Attempt to load the transformer backend. Tests and
            low-resource machines can disable it to force the hashing backend.
        cache: Optional persistent cache shared across engine instances.
        cache_limit: Maximum number of texts kept in the in-memory LRU cache.
        backend: Optional pre-built backend, primarily for dependency injection.
        corpus_provider: Optional source of texts for hashing-backend IDF weights.
            Called lazily once, only when the fallback backend is selected.
    """

    def __init__(
        self,
        model_name: str,
        *,
        prefer_transformer: bool = True,
        cache: EmbeddingCache | None = None,
        cache_limit: int = _CACHE_LIMIT,
        backend: EmbeddingBackend | None = None,
        corpus_provider: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        self.requested_model = model_name
        self._prefer_transformer = prefer_transformer
        self._corpus_provider = corpus_provider
        self._backend = backend
        self._persistent_cache = cache
        self._cache_limit = max(1, cache_limit)
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.RLock()
        self._backend_lock = threading.Lock()

    def _ensure_backend(self) -> EmbeddingBackend:
        if self._backend is not None:
            return self._backend
        with self._backend_lock:
            if self._backend is not None:
                return self._backend
            if self._prefer_transformer:
                try:
                    self._backend = SentenceTransformerBackend(self.requested_model)
                    logger.info("Loaded embedding model %s", self.requested_model)
                except Exception as exc:
                    logger.warning(
                        "Sentence-Transformers unavailable (%s); using deterministic hashing embeddings.",
                        exc,
                    )
                    self._backend = self._hashing_backend()
            else:
                self._backend = self._hashing_backend()
            return self._backend

    def _hashing_backend(self) -> HashingEmbeddingBackend:
        texts = self._corpus_texts()
        fingerprint = _corpus_fingerprint(texts)
        backend = HashingEmbeddingBackend(texts)
        backend.corpus_fingerprint = fingerprint
        backend.name = f"{backend.name}-{fingerprint[:8]}"
        return backend

    def _corpus_texts(self) -> Sequence[str]:
        if self._corpus_provider is None:
            return ()
        try:
            return [text for text in self._corpus_provider() if text]
        except Exception as exc:
            logger.warning("Could not build hashing IDF corpus: %s", exc)
            return ()

    @property
    def backend(self) -> EmbeddingBackend:
        return self._ensure_backend()

    @property
    def corpus_fingerprint(self) -> str:
        return str(getattr(self.backend, "corpus_fingerprint", ""))

    @property
    def model_name(self) -> str:
        return self.backend.name

    @property
    def dimension(self) -> int:
        return self.backend.dimension

    @property
    def is_semantic(self) -> bool:
        return self.backend.is_semantic

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        unique_texts = list(dict.fromkeys(texts))
        with self._lock:
            missing: list[str] = []
            for text in unique_texts:
                if text in self._cache:
                    self._cache.move_to_end(text)
                else:
                    missing.append(text)

        if missing:
            self._load_persistent(missing)

        with self._lock:
            still_missing = [text for text in missing if text not in self._cache]
            vectors_by_text = {text: self._cache[text] for text in unique_texts if text in self._cache}

        if still_missing:
            vectors = self.backend.encode(still_missing)
            with self._lock:
                self._store(still_missing, vectors)
                vectors_by_text.update({text: self._cache[text] for text in still_missing})
            if self._persistent_cache is not None:
                self._persistent_cache.set_many(
                    self.model_name,
                    {sha256_text(text): vector for text, vector in zip(still_missing, vectors, strict=True)},
                )

        return np.vstack([vectors_by_text[text] for text in texts]).astype(np.float32)

    def _load_persistent(self, texts: Sequence[str]) -> None:
        if self._persistent_cache is None:
            return
        hashes = {sha256_text(text): text for text in texts}
        cached = self._persistent_cache.get_many(self.model_name, list(hashes))
        with self._lock:
            for text_hash, vector in cached.items():
                text = hashes.get(text_hash)
                if text is None or vector.shape != (self.dimension,):
                    continue
                self._store([text], [vector])

    def _store(self, texts: Sequence[str], vectors: Sequence[np.ndarray]) -> None:
        for text, vector in zip(texts, vectors, strict=True):
            self._cache[text] = np.asarray(vector, dtype=np.float32)
            self._cache.move_to_end(text)
            while len(self._cache) > self._cache_limit:
                self._cache.popitem(last=False)

    def prune_cache(self, max_entries: int = 10_000) -> int:
        if self._persistent_cache is None:
            return 0
        return self._persistent_cache.prune(max_entries)

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]
