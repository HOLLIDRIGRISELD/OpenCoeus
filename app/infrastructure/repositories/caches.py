"""Persistent caches that survive a session reset."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.infrastructure.database import Database
from app.infrastructure.models import AnalysisCacheEntry, FileFingerprint


class FileFingerprintRepository:
    """Remembers ``(size, mtime_ns, sha256)`` for unchanged paths."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def all_for_root(self, root: str) -> dict[str, tuple[int, int, str]]:
        with self._db.session() as session:
            rows = session.scalars(
                select(FileFingerprint).where(FileFingerprint.path.startswith(root))
            ).all()
            return {
                row.path: (row.size, row.mtime_ns, row.sha256)
                for row in rows
            }

    def set_many(self, items: Sequence[tuple[str, int, int, str]]) -> None:
        if not items:
            return
        values = [
            {"path": path, "size": size, "mtime_ns": mtime_ns, "sha256": sha256}
            for path, size, mtime_ns, sha256 in items
        ]
        statement = sqlite_insert(FileFingerprint).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=["path"],
            set_={
                "size": statement.excluded.size,
                "mtime_ns": statement.excluded.mtime_ns,
                "sha256": statement.excluded.sha256,
            },
        )
        with self._db.session() as session:
            session.execute(statement)


class AnalysisCacheRepository:
    """Stores derived analysis results keyed by content and pipeline versions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def all_keys(self) -> set[str]:
        with self._db.engine.connect() as connection:
            return set(connection.execute(select(AnalysisCacheEntry.key)).scalars())

    def get(self, key: str) -> tuple[dict[str, Any], list[np.ndarray]] | None:
        with self._db.session() as session:
            row = session.get(AnalysisCacheEntry, key)
            if row is None:
                return None
            payload = json.loads(row.payload)
            matrix = np.load(io.BytesIO(row.vectors), allow_pickle=False)
            vectors = [np.asarray(matrix[index], dtype=np.float32) for index in range(len(matrix))]
            return payload, vectors

    def set(
        self,
        key: str,
        payload: Mapping[str, Any],
        vectors: Sequence[np.ndarray],
    ) -> None:
        matrix = (
            np.vstack([np.asarray(vector, dtype=np.float32) for vector in vectors])
            if vectors
            else np.zeros((0, 0), dtype=np.float32)
        )
        buffer = io.BytesIO()
        np.save(buffer, matrix, allow_pickle=False)
        encoded = json.dumps(payload, sort_keys=True)
        with self._db.session() as session:
            row = session.get(AnalysisCacheEntry, key)
            if row is None:
                session.add(AnalysisCacheEntry(key=key, payload=encoded, vectors=buffer.getvalue()))
                return
            row.payload = encoded
            row.vectors = buffer.getvalue()
