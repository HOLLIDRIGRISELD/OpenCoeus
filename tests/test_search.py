"""Keyword, semantic and hybrid retrieval."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sqlalchemy import text

from app.search.keyword import build_match_expression
from app.services.context import AppContext
from tests.conftest import file_id_for


def test_keyword_query_builder_quotes_tokens_and_drops_stopwords() -> None:
    parsed = build_match_expression("Find me the invoice about payment")
    assert parsed.terms == ["invoice", "payment"]
    assert parsed.match_expression == '"invoice" OR "payment"'


def test_keyword_query_builder_handles_punctuation_only() -> None:
    parsed = build_match_expression("!!! ???")
    assert parsed.match_expression == ""
    assert parsed.terms == []


def test_keyword_search_finds_invoice(context: AppContext, analysed_library: Path) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    response = context.search.search("invoice", mode="keyword", limit=10)

    assert response.mode == "keyword"
    assert response.hits
    assert invoice_id in [hit.file_id for hit in response.hits]
    top = next(hit for hit in response.hits if hit.file_id == invoice_id)
    assert top.category == "Finance/Invoices"
    assert top.snippet


def test_load_embeddings_returns_the_same_rows_as_stored_vectors(
    context: AppContext, analysed_library: Path
) -> None:
    model = context.embeddings.model_name
    loaded = context.analyses.load_embeddings(model)

    with context.db.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT b.file_id, b.vector, c.text FROM embedding_blobs AS b "
                "JOIN document_chunks AS c ON c.id = b.chunk_id "
                "WHERE b.model_name = :model ORDER BY b.file_id, b.chunk_id"
            ),
            {"model": model},
        ).all()
    expected = [(file_id, np.frombuffer(vector, dtype="<f8"), chunk or "") for file_id, vector, chunk in rows]

    assert len(loaded) == len(expected)
    for (file_id, vector, chunk), (expected_id, expected_vector, expected_chunk) in zip(
        loaded, expected, strict=True
    ):
        assert file_id == expected_id
        assert chunk == expected_chunk
        np.testing.assert_array_equal(vector, expected_vector)


def test_semantic_search_finds_related_content(context: AppContext, analysed_library: Path) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    response = context.search.search("amount due payment terms", mode="semantic", limit=10)

    assert response.mode == "semantic"
    assert response.hits
    assert invoice_id in [hit.file_id for hit in response.hits]
    assert response.hits[0].explanation and "similarity" in response.hits[0].explanation.lower()


def test_hybrid_search_combines_retrievers(context: AppContext, analysed_library: Path) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    response = context.search.search("invoice amount due", mode="hybrid", limit=10)

    assert response.hits
    assert invoice_id in [hit.file_id for hit in response.hits[:3]]
    assert response.hits[0].mode == "hybrid"
    assert "Retrieved by" in (response.hits[0].explanation or "")
    assert any("Reciprocal Rank Fusion" in note for note in response.notes)


def test_search_uses_configured_fusion_weights(context: AppContext, analysed_library: Path) -> None:
    context.apply_settings({"search.alpha": 0.7, "search.beta": 0.3})
    context.search.search("invoice", mode="hybrid")

    assert context.search._hybrid.alpha == 0.7
    assert context.search._hybrid.beta == 0.3


def test_search_handles_empty_and_unknown_queries(context: AppContext, analysed_library: Path) -> None:
    empty = context.search.search("   ", mode="hybrid")
    assert empty.hits == []
    assert empty.notes

    missing = context.search.search("zzzznotpresent", mode="keyword")
    assert missing.hits == []
    assert any("No documents matched" in note for note in missing.notes)


def test_invalid_search_mode_falls_back_to_hybrid(context: AppContext, analysed_library: Path) -> None:
    response = context.search.search("invoice", mode="nonsense", limit=5)
    assert response.mode == "hybrid"
    assert response.hits
