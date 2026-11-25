"""Vector retrieval over locally generated embeddings.

Vectors are stored per chunk and aggregated per file using the best-matching
chunk. That keeps long documents from being penalised by unrelated sections.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from app.core.progress import CancellationToken
from app.domain.models import SearchHit
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.intelligence.embeddings import EmbeddingEngine


class SemanticSearch:
    """Cosine-similarity search over chunk embeddings."""

    def __init__(self, analyses: AnalysisRepository, embeddings: EmbeddingEngine) -> None:
        self._analyses = analyses
        self._embeddings = embeddings

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        min_similarity: float = 0.02,
        cancel: CancellationToken | None = None,
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        if cancel is not None:
            cancel.raise_if_cancelled()
        query_vector = self._embeddings.encode_one(query)
        best: dict[int, tuple[float, str]] = {}
        for file_id, vector, chunk_text in self._analyses.load_embeddings(
            self._embeddings.model_name
        ):
            if cancel is not None:
                cancel.raise_if_cancelled()
            if vector.shape != query_vector.shape:
                continue
            similarity = float(np.dot(query_vector, vector))
            current = best.get(file_id)
            if current is None or similarity > current[0]:
                best[file_id] = (similarity, chunk_text)

        ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
        top = ranked[: max(limit * 2, limit)]
        similarities = [value[0] for _, value in top if value[0] >= min_similarity]
        if not similarities:
            return []
        low, high = min(similarities), max(similarities)
        span = max(high - low, 1e-6)

        hits: list[SearchHit] = []
        paths = self._paths([file_id for file_id, _ in top])
        for file_id, (similarity, chunk_text) in top:
            if similarity < min_similarity:
                continue
            normalised = (similarity - low) / span if high > low else 1.0
            filename, path = paths.get(file_id, (f"File {file_id}", ""))
            hits.append(
                SearchHit(
                    file_id=file_id,
                    filename=filename,
                    path=path,
                    score=round(0.35 + 0.65 * normalised, 4),
                    mode="semantic",
                    snippet=_snippet(chunk_text, query),
                    explanation=f"Semantic similarity {similarity:.2f} using {self._embeddings.model_name}.",
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def _paths(self, file_ids: Sequence[int]) -> dict[int, tuple[str, str]]:
        from sqlalchemy import select

        from app.infrastructure.models import File

        if not file_ids:
            return {}
        with self._analyses._db.session() as session:  # noqa: SLF001 - repository boundary inside search
            rows = session.execute(
                select(File.id, File.current_name, File.current_path).where(File.id.in_(list(file_ids)))
            ).all()
            return {file_id: (name, path) for file_id, name, path in rows}


def _snippet(text: str, query: str, length: int = 220) -> str | None:
    if not text.strip():
        return None
    lowered = text.lower()
    best_position = -1
    for token in query.lower().split():
        position = lowered.find(token)
        if position >= 0:
            best_position = position if best_position < 0 else min(best_position, position)
    start = 0 if best_position < 0 else max(0, best_position - length // 3)
    snippet = " ".join(text[start : start + length].split())
    return ("… " if start > 0 else "") + snippet + (" …" if start + length < len(text) else "")
