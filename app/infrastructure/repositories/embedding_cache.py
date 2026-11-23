"""Persistent cache for exact-text embedding vectors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert

from app.infrastructure.database import Database
from app.infrastructure.models import EmbeddingCacheBlob, EmbeddingCacheEntry


class EmbeddingCacheRepository:
    """Stores vectors keyed by ``(model_name, sha256(text))``.

    The schema is created by ``Base.metadata.create_all`` like every other
    table; no column is added to an existing table, so older databases upgrade
    safely on the next start.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def get_many(
        self, model_name: str, text_hashes: Sequence[str]
    ) -> dict[str, np.ndarray]:
        if not text_hashes:
            return {}
        requested = list(dict.fromkeys(text_hashes))
        with self._db.session() as session:
            rows = session.scalars(
                select(EmbeddingCacheBlob).where(
                    EmbeddingCacheBlob.model_name == model_name,
                    EmbeddingCacheBlob.text_hash.in_(requested),
                )
            ).all()
            result = {
                row.text_hash: np.frombuffer(row.vector, dtype="<f8")
                for row in rows
                if len(row.vector) == row.dimension * 8
            }
            legacy = session.scalars(
                select(EmbeddingCacheEntry).where(
                    EmbeddingCacheEntry.model_name == model_name,
                    EmbeddingCacheEntry.text_hash.in_(requested),
                )
            ).all()
            result.update(
                {
                    row.text_hash: np.asarray(row.vector, dtype=np.float32)
                    for row in legacy
                    if row.text_hash not in result and len(row.vector) == row.dimension
                }
            )
            return result

    def set_many(self, model_name: str, vectors: Mapping[str, np.ndarray]) -> None:
        if not vectors:
            return
        payload = [
            {
                "model_name": model_name,
                "text_hash": text_hash,
                "dimension": int(vector.size),
                "vector": np.asarray(vector, dtype="<f8").tobytes(),
            }
            for text_hash, vector in vectors.items()
        ]
        statement = insert(EmbeddingCacheBlob).values(payload)
        statement = statement.on_conflict_do_update(
            index_elements=["model_name", "text_hash"],
            set_={
                "dimension": statement.excluded.dimension,
                "vector": statement.excluded.vector,
            },
        )
        with self._db.session() as session:
            session.execute(statement)

    def prune(self, max_entries: int = 10_000) -> int:
        limit = max(1, max_entries)
        with self._db.session() as session:
            total = session.scalar(select(func.count()).select_from(EmbeddingCacheBlob)) or 0
            if total <= limit:
                return 0
            cutoff = session.scalar(
                select(EmbeddingCacheBlob.created_at)
                .order_by(EmbeddingCacheBlob.created_at.desc())
                .offset(limit)
                .limit(1)
            )
            deleted = session.execute(
                delete(EmbeddingCacheBlob).where(EmbeddingCacheBlob.created_at <= cutoff)
            ).rowcount
            legacy = session.execute(
                delete(EmbeddingCacheEntry).where(EmbeddingCacheEntry.created_at <= cutoff)
            ).rowcount
            return int(deleted or 0) + int(legacy or 0)
