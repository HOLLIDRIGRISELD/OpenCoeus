"""Persistent store for confirmed human classification decisions."""

from __future__ import annotations

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.domain.models import utcnow
from app.infrastructure.database import Database
from app.infrastructure.models import ClassificationFeedback


class FeedbackRepository:
    """Stores one corrected category vector per file and embedding model."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(
        self,
        file_id: int,
        category_path: str,
        model_name: str,
        vector: np.ndarray,
    ) -> None:
        now = utcnow()
        statement = insert(ClassificationFeedback).values(
            file_id=file_id,
            category_path=category_path,
            model_name=model_name,
            dimension=int(vector.size),
            vector=[round(float(value), 6) for value in vector],
            created_at=now,
            updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["file_id"],
            set_={
                "category_path": statement.excluded.category_path,
                "model_name": statement.excluded.model_name,
                "dimension": statement.excluded.dimension,
                "vector": statement.excluded.vector,
                "updated_at": now,
            },
        )
        with self._db.session() as session:
            session.execute(statement)

    def has_any(self) -> bool:
        with self._db.session() as session:
            return session.scalar(select(ClassificationFeedback.id).limit(1)) is not None

    def for_model(self, model_name: str) -> list[tuple[str, np.ndarray]]:
        with self._db.session() as session:
            rows = session.execute(
                select(
                    ClassificationFeedback.category_path,
                    ClassificationFeedback.vector,
                    ClassificationFeedback.dimension,
                ).where(ClassificationFeedback.model_name == model_name)
            ).all()
            return [
                (path, np.asarray(vector, dtype=np.float32))
                for path, vector, dimension in rows
                if len(vector) == dimension
            ]
