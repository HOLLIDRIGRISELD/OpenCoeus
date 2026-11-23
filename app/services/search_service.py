"""Search facade used by the CLI and the UI.

The service chooses between keyword, semantic and hybrid retrieval, applies the
current settings to the fusion weights, and enriches hits with their category so
the result list can be explained without a second database round-trip.
"""

from __future__ import annotations

import time

from app.core.logging_config import get_logger
from app.core.progress import CancellationToken, OperationCancelled
from app.domain.enums import SearchMode
from app.domain.models import SearchHit, SearchResponse
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.intelligence.embeddings import EmbeddingEngine
from app.search.hybrid import HybridSearch
from app.search.keyword import KeywordSearch
from app.search.semantic import SemanticSearch
from app.services.settings_service import SettingsService

logger = get_logger(__name__)


class SearchService:
    """Runs one of the three retrieval modes and annotates the results."""

    def __init__(
        self,
        keyword: KeywordSearch,
        semantic: SemanticSearch,
        hybrid: HybridSearch,
        analyses: AnalysisRepository,
        embeddings: EmbeddingEngine,
        settings: SettingsService,
    ) -> None:
        self._keyword = keyword
        self._semantic = semantic
        self._hybrid = hybrid
        self._analyses = analyses
        self._embeddings = embeddings
        self._settings = settings

    def search(
        self,
        query: str,
        *,
        mode: str | SearchMode = SearchMode.HYBRID,
        limit: int = 50,
        min_similarity: float = 0.02,
        cancel: CancellationToken | None = None,
    ) -> SearchResponse:
        """Search the local index.

        Args:
            query: Natural-language or keyword query.
            mode: ``keyword``, ``semantic`` or ``hybrid``.
            limit: Maximum number of results.
            min_similarity: Semantic floor; lower values return more noise.
            cancel: Optional worker token checked by semantic retrieval.
        """

        selected = mode.value if isinstance(mode, SearchMode) else str(mode).lower()
        if selected not in {item.value for item in SearchMode}:
            selected = SearchMode.HYBRID.value
        started = time.perf_counter()
        response = SearchResponse(query=query, mode=selected)

        if not query.strip():
            response.notes.append("Enter a query to search the indexed documents.")
            return response

        if cancel is not None:
            cancel.raise_if_cancelled()
        try:
            if selected == SearchMode.KEYWORD.value:
                hits = self._keyword.search(query, limit=limit)
            elif selected == SearchMode.SEMANTIC.value:
                hits = self._semantic.search(
                    query, limit=limit, min_similarity=min_similarity, cancel=cancel
                )
                if not self._embeddings.is_semantic:
                    response.notes.append(
                        "Semantic search is using the deterministic hashing fallback; "
                        "install sentence-transformers for a trained embedding model."
                    )
            else:
                self._hybrid.alpha = self._settings.search_alpha
                self._hybrid.beta = self._settings.search_beta
                hits = self._hybrid.search(query, limit=limit, cancel=cancel)
                response.notes.append(
                    f"Reciprocal Rank Fusion with keyword weight "
                    f"{self._hybrid.alpha:.2f} and semantic weight {self._hybrid.beta:.2f}."
                )
        except OperationCancelled:
            raise
        except Exception as exc:
            logger.exception("Search failed for %r", query)
            response.notes.append(f"Search failed: {exc}")
            hits = []

        response.hits = self._annotate(hits)
        response.took_ms = round((time.perf_counter() - started) * 1000, 1)
        if not response.hits:
            response.notes.append(
                "No documents matched. Try fewer words, a broader phrase, or another mode."
            )
        return response

    def _annotate(self, hits: list[SearchHit]) -> list[SearchHit]:
        if not hits:
            return []
        categories = self._analyses.categories_for_files([hit.file_id for hit in hits])
        for hit in hits:
            hit.category = categories.get(hit.file_id)
        return hits


__all__ = ["SearchService"]
