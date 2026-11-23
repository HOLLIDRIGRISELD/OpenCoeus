"""Hybrid retrieval using Reciprocal Rank Fusion (RRF).

Keyword and semantic scores live on different scales, so fusing their *ranks*
is more robust than adding raw scores. RRF is a standard, easily explained
baseline for the dissertation comparison.
"""

from __future__ import annotations

from app.core.progress import CancellationToken
from app.domain.models import SearchHit
from app.search.keyword import KeywordSearch
from app.search.semantic import SemanticSearch

RRF_K = 60


class HybridSearch:
    """Combines keyword and semantic result lists."""

    def __init__(
        self,
        keyword: KeywordSearch,
        semantic: SemanticSearch,
        *,
        alpha: float = 0.4,
        beta: float = 0.6,
    ) -> None:
        self.keyword = keyword
        self.semantic = semantic
        self.alpha = alpha
        self.beta = beta

    def search(
        self, query: str, *, limit: int = 50, cancel: CancellationToken | None = None
    ) -> list[SearchHit]:
        if cancel is not None:
            cancel.raise_if_cancelled()
        keyword_hits = self.keyword.search(query, limit=limit)
        if cancel is not None:
            cancel.raise_if_cancelled()
        semantic_hits = self.semantic.search(query, limit=limit, cancel=cancel)

        fused: dict[int, dict[str, object]] = {}
        for rank, hit in enumerate(keyword_hits, start=1):
            entry = fused.setdefault(hit.file_id, {"hit": hit, "score": 0.0, "modes": []})
            entry["score"] = float(entry["score"]) + self.alpha * (1.0 / (RRF_K + rank))
            entry["modes"].append("keyword")  # type: ignore[union-attr]
        for rank, hit in enumerate(semantic_hits, start=1):
            entry = fused.setdefault(hit.file_id, {"hit": hit, "score": 0.0, "modes": []})
            entry["score"] = float(entry["score"]) + self.beta * (1.0 / (RRF_K + rank))
            entry["modes"].append("semantic")  # type: ignore[union-attr]
            if len(entry["modes"]) > 1:  # type: ignore[arg-type]
                entry["hit"] = hit

        if not fused:
            return []
        maximum = max(float(entry["score"]) for entry in fused.values())
        results: list[SearchHit] = []
        for entry in sorted(fused.values(), key=lambda item: float(item["score"]), reverse=True):
            hit = entry["hit"]
            assert isinstance(hit, SearchHit)
            modes = entry["modes"]
            assert isinstance(modes, list)
            results.append(
                SearchHit(
                    file_id=hit.file_id,
                    filename=hit.filename,
                    path=hit.path,
                    score=round(float(entry["score"]) / maximum, 4),
                    mode="hybrid",
                    snippet=hit.snippet,
                    explanation="Retrieved by " + " + ".join(modes) + " search.",
                )
            )
            if len(results) >= limit:
                break
        return results
