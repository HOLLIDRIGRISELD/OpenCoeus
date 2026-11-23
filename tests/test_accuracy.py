"""Regression tests for accuracy improvements that must not cost latency."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from app.core.constants import STATUS_ANALYSED
from app.domain.models import ClassificationResult, DocumentProfile
from app.intelligence.classifier import (
    HybridClassifier,
    confidence_from_evidence,
    semantic_range,
)
from app.intelligence.embeddings import EmbeddingEngine, HashingEmbeddingBackend, mean_vector
from app.intelligence.llm_policy import should_use_llm
from app.services import analysis_service
from app.services.context import AppContext

INVOICE_TEXT = (
    "INVOICE\n\nInvoice number: INV-2024-0042\n"
    "Bill to: Northwind Systems Ltd\nPurchase order: PO-7781\n"
    "Subtotal: 1,250.00\nVAT: 250.00\nAmount due: 1,500.00\n"
    "Payment terms: 30 days. Please remit to the account below.\n"
)

RECEIPT_TEXT = (
    "SALES RECEIPT\n\nPaid in full at the checkout on 14 March 2024.\n"
    "Cashier: 042\nStore: Northwind Retail Ltd\n"
    "Items: 3 x notebooks, 2 x pens.\n"
    "Total paid: 18.50. This receipt confirms your purchase.\n"
)

LECTURE_TEXT = (
    "Lecture 4 notes: Hybrid classification.\n\n"
    "These class handouts cover today's topic and the key terms from the module.\n"
    "Revision note: review the worked example before the seminar.\n"
)


class CountingBackend:
    """Embedding backend that records how often real encoding is requested."""

    is_semantic = False

    def __init__(self, *, name: str, dimension: int, vector: np.ndarray) -> None:
        self.name = name
        self.dimension = dimension
        self._vector = vector
        self.encode_calls = 0

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        self.encode_calls += len(texts)
        return np.repeat(self._vector[None, :], len(texts), axis=0)


def _result(*, confidence: float, margin: float, needs_review: bool) -> ClassificationResult:
    return ClassificationResult(
        primary_category="Finance",
        secondary_category="Invoices",
        category_path="Finance/Invoices",
        confidence=confidence,
        margin=margin,
        method="hybrid",
        needs_review=needs_review,
    )


def test_confidence_rewards_a_clear_margin() -> None:
    close = confidence_from_evidence(top_score=0.60, margin=0.02, rule_hits=2)
    clear = confidence_from_evidence(top_score=0.60, margin=0.25, rule_hits=2)

    assert clear > close
    assert 0.0 <= close <= clear <= 0.98


def test_mean_vector_averages_and_normalises() -> None:
    averaged = mean_vector([np.array([1.0, 0.0]), np.array([0.0, 1.0])])

    np.testing.assert_allclose(averaged, np.array([2**-0.5, 2**-0.5]), atol=1e-6)


def test_persistent_embedding_cache_survives_a_new_engine(context: AppContext) -> None:
    from app.infrastructure.repositories.embedding_cache import EmbeddingCacheRepository

    repository = EmbeddingCacheRepository(context.db)
    first = EmbeddingEngine("hashing", prefer_transformer=False, cache=repository)
    first_vector = first.encode(["alpha beta"])[0]

    backend = CountingBackend(
        name=first.model_name,
        dimension=first.dimension,
        vector=np.ones(first.dimension, dtype=np.float32),
    )
    second = EmbeddingEngine("hashing", backend=backend, cache=repository)

    np.testing.assert_allclose(second.encode(["alpha beta"])[0], first_vector, atol=1e-6)
    assert backend.encode_calls == 0


def test_embedding_cache_evicts_least_recently_used_text() -> None:
    engine = EmbeddingEngine("hashing", prefer_transformer=False, cache_limit=2)
    engine.encode(["alpha"])
    engine.encode(["beta"])
    engine.encode(["alpha"])
    engine.encode(["gamma"])

    assert "alpha" in engine._cache
    assert "gamma" in engine._cache
    assert "beta" not in engine._cache


def test_classifier_accepts_a_precomputed_document_vector(
    context: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    classifier = HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )
    vector = context.embeddings.encode_one(f"{INVOICE_TEXT}\ninvoice")

    def fail(_text: str) -> np.ndarray:
        raise AssertionError("classifier re-encoded the document instead of reusing chunk vectors")

    monkeypatch.setattr(context.embeddings, "encode_one", fail)
    result = classifier.classify(
        INVOICE_TEXT, filename="invoice_2024.txt", document_vector=vector
    )

    assert result.category_path == "Finance/Invoices"


def test_llm_is_skipped_for_confident_documents() -> None:
    classification = _result(confidence=0.91, margin=0.12, needs_review=False)

    assert (
        should_use_llm(
            classification=classification,
            title_supported=False,
            text_length=2_000,
            available=True,
        )
        is False
    )


def test_llm_is_used_for_uncertain_documents_without_a_verified_title() -> None:
    classification = _result(confidence=0.55, margin=0.03, needs_review=True)

    assert (
        should_use_llm(
            classification=classification,
            title_supported=False,
            text_length=2_000,
            available=True,
        )
        is True
    )


def test_llm_is_skipped_when_the_title_is_already_verified() -> None:
    classification = _result(confidence=0.55, margin=0.03, needs_review=True)

    assert (
        should_use_llm(
            classification=classification,
            title_supported=True,
            text_length=2_000,
            available=True,
        )
        is False
    )


def test_llm_gate_uses_content_title_presence_not_filename_safety(
    context: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def spy(**kwargs: object) -> bool:
        seen.update(kwargs)
        return False

    monkeypatch.setattr(analysis_service, "should_use_llm", spy)
    profile = DocumentProfile(file_id=1, title="fallback", title_supported=False)
    classification = _result(confidence=0.55, margin=0.03, needs_review=True)

    context.analysis._apply_llm(
        profile,
        classification,
        "text",
        content_title_present=True,
    )

    assert seen["title_supported"] is True


def test_llm_availability_is_not_probed_for_confident_documents() -> None:
    classification = _result(confidence=0.91, margin=0.12, needs_review=False)

    def probe() -> bool:
        raise AssertionError("availability probe must not run for confident documents")

    assert (
        should_use_llm(
            classification=classification,
            title_supported=False,
            text_length=2_000,
            available=probe,
        )
        is False
    )


def test_llm_availability_is_probed_only_after_uncertainty_is_established() -> None:
    classification = _result(confidence=0.55, margin=0.03, needs_review=True)
    calls: list[bool] = []

    def probe() -> bool:
        calls.append(True)
        return True

    assert (
        should_use_llm(
            classification=classification,
            title_supported=False,
            text_length=2_000,
            available=probe,
        )
        is True
    )
    assert calls == [True]


def test_receipt_is_not_misclassified_as_invoice(context: AppContext) -> None:
    classifier = HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )

    result = classifier.classify(RECEIPT_TEXT, filename="receipt_march.txt", extension=".txt")

    assert result.category_path == "Finance/Receipts"


def test_lecture_notes_are_not_misclassified_as_assignments(context: AppContext) -> None:
    classifier = HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )

    result = classifier.classify(LECTURE_TEXT, filename="lecture_04.txt", extension=".txt")

    assert result.category_path == "Education/Lecture Notes"


def test_identical_file_reuses_the_first_analysis(
    context: AppContext, sample_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.conftest import write_text

    context.scanning.scan(sample_library)
    first_report = context.analysis.analyse_pending(use_llm=False)
    assert first_report.analysed == 4

    original = sample_library / "Downloads" / "invoice_acme_2024.txt"
    duplicate = sample_library / "Downloads" / "invoice_acme_copy.txt"
    write_text(duplicate, original.read_text(encoding="utf-8"))
    context.scanning.scan(sample_library)

    for path in sample_library.rglob("*"):
        if path.is_file() and ".git" not in path.parts and path != duplicate:
            file_id = context.files.find_by_path(path)
            if file_id is not None:
                context.files.update_status(file_id, STATUS_ANALYSED, analysed=True)

    def no_extraction(*_args: object, **_kwargs: object):
        raise AssertionError("duplicate file was extracted again")

    monkeypatch.setattr(context.analysis, "_extract", no_extraction)
    second_report = context.analysis.analyse_pending(use_llm=False)

    assert second_report.analysed == 1
    assert second_report.failed == 0
    duplicate_id = context.files.find_by_path(duplicate)
    assert duplicate_id is not None
    analysis = context.analyses.latest_analysis(duplicate_id)
    assert analysis is not None
    assert analysis.category_path == "Finance/Invoices"


def test_hashing_backend_uses_corpus_idf() -> None:
    backend = HashingEmbeddingBackend(
        corpus_texts=[
            "common alpha one",
            "common beta two",
            "common gamma three",
            "rare zebra four",
        ]
    )

    assert backend.idf_weight("w:common") < backend.idf_weight("w:rare")


def test_confirmed_feedback_guides_a_future_classification(context: AppContext) -> None:
    ambiguous = "Quarterly planning note with follow-ups for the wider team."
    descriptions = context.analyses.category_descriptions()
    vector = context.embeddings.encode_one(ambiguous)
    plain = HybridClassifier(descriptions, context.embeddings, review_threshold=0.6)
    learned = HybridClassifier(
        descriptions,
        context.embeddings,
        review_threshold=0.6,
        feedback=[("Business/Reports", vector)],
    )

    before = plain.classify(ambiguous, filename="plan.txt", extension=".txt")
    after = learned.classify(ambiguous, filename="plan.txt", extension=".txt")

    assert after.category_path == "Business/Reports"
    assert after.confidence > before.confidence
    assert any("Confirmed review decision" in item for item in after.evidence)


def test_manual_category_override_is_learned(context: AppContext, analysed_library) -> None:
    file_id = context.files.find_by_path(
        analysed_library / "Downloads" / "invoice_acme_2024.txt"
    )
    assert file_id is not None

    context.recommendations.set_category(file_id, "Business/Reports")

    examples = context.feedback.for_model(context.embeddings.model_name)
    assert any(path == "Business/Reports" for path, _ in examples)

    result = context.classifier().classify(
        INVOICE_TEXT, filename="invoice_2024.txt", extension=".txt"
    )
    assert any("Confirmed review decision" in item for item in result.evidence)


def test_transformer_similarity_keeps_original_scale() -> None:
    assert semantic_range(is_semantic=True) == (0.05, 0.95)


def test_hashing_similarity_uses_fallback_scale() -> None:
    assert semantic_range(is_semantic=False) == (0.0, 0.25)


def test_invoice_is_confidently_classified_with_hashing_backend(context: AppContext) -> None:
    classifier = HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )

    result = classifier.classify(INVOICE_TEXT, filename="invoice_2024.txt", extension=".txt")

    assert result.category_path == "Finance/Invoices"
    assert result.confidence >= 0.60
    assert result.needs_review is False


def test_filename_only_document_stays_unclassified_under_hashing_scale(context: AppContext) -> None:
    classifier = HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )

    result = classifier.classify("", filename="0001-bmp-from-web.bmp", extension=".bmp")

    assert result.category_path == "Unclassified"
    assert result.needs_review is True


def test_no_text_image_stays_unclassified(context: AppContext) -> None:
    document_vector = context.embeddings.encode_one("0001 png from web png")

    result = _new_classifier(context).classify(
        "",
        filename="0001-png-from-web.png",
        extension=".png",
        document_vector=document_vector,
    )

    assert result.category_path == "Unclassified"
    assert result.needs_review is True


def test_normal_analysis_skips_pending_review(
    context: AppContext, sample_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.constants import STATUS_PENDING_REVIEW
    from app.services.analysis_service import AnalysisOutcome

    context.scanning.scan(sample_library)
    context.analysis.analyse_pending(use_llm=False)
    file_id = context.files.find_by_path(sample_library / "Downloads" / "invoice_acme_2024.txt")
    assert file_id is not None
    context.files.update_status(file_id, STATUS_PENDING_REVIEW)
    seen: list[int] = []

    def record(file_id: int, **_kwargs: object) -> AnalysisOutcome:
        seen.append(file_id)
        return AnalysisOutcome(file_id, STATUS_PENDING_REVIEW, skipped=True)

    monkeypatch.setattr(context.analysis, "analyse_file", record)

    context.analysis.analyse_pending(use_llm=False)

    assert file_id not in seen


def test_forced_analysis_includes_pending_review(
    context: AppContext, sample_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.constants import STATUS_PENDING_REVIEW
    from app.services.analysis_service import AnalysisOutcome

    context.scanning.scan(sample_library)
    file_id = context.files.find_by_path(sample_library / "Downloads" / "invoice_acme_2024.txt")
    assert file_id is not None
    context.files.update_status(file_id, STATUS_PENDING_REVIEW)
    seen: list[int] = []

    def record(file_id: int, **_kwargs: object) -> AnalysisOutcome:
        seen.append(file_id)
        return AnalysisOutcome(file_id, STATUS_PENDING_REVIEW, skipped=True)

    monkeypatch.setattr(context.analysis, "analyse_file", record)

    context.analysis.analyse_pending(use_llm=False, force=True)

    assert file_id in seen


def test_analysis_uses_current_signature_for_svg(
    context: AppContext, sample_library
) -> None:
    from sqlalchemy import text

    path = sample_library / "Downloads" / "drawing.svg"
    path.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    context.scanning.scan(sample_library)
    file_id = context.files.find_by_path(path)
    assert file_id is not None
    with context.db.engine.begin() as connection:
        connection.execute(
            text("UPDATE files SET detected_format = 'text' WHERE id = :id"),
            {"id": file_id},
        )

    context.analysis.analyse_file(file_id, use_llm=False)

    with context.db.engine.begin() as connection:
        method = connection.execute(
            text("SELECT extraction_method FROM document_contents WHERE file_id = :id"),
            {"id": file_id},
        ).scalar()
    assert method == "vector-metadata"


def test_embedding_corpus_limit_bounds_texts_and_characters() -> None:
    from app.infrastructure.repositories.analysis import limit_embedding_corpus

    texts = ["x" * 1000 for _ in range(10)]

    limited = limit_embedding_corpus(
        texts,
        max_texts=3,
        max_chars_per_text=200,
        max_total_chars=400,
    )

    assert limited == ["x" * 200, "x" * 200]


def _new_classifier(context: AppContext) -> HybridClassifier:
    return HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )


def test_government_report_text_classifies(context: AppContext) -> None:
    text = (
        "West Sussex County Council report on adult social care. The consultation covers "
        "council premises, public services and the official response to the department "
        "for communities."
    )

    result = _new_classifier(context).classify(text, filename="sample.txt", extension=".txt")

    assert result.category_path == "Government/Reports"


def test_expense_data_text_classifies(context: AppContext) -> None:
    text = (
        "Expense claim dataset. Supplier CAPITA BUSINESS SERVICES LTD, cost centre Corporate, "
        "amount 29,379.18, transaction 5100000014, VAT and reimbursement details."
    )

    result = _new_classifier(context).classify(text, filename="sample.csv", extension=".csv")

    assert result.category_path == "Finance/Expenses"


def test_source_code_text_classifies(context: AppContext) -> None:
    text = (
        "function calculate(value) { const result = value + 1; return result; } "
        "export default calculate; import numpy from 'numpy'; #!/usr/bin/env python"
    )

    result = _new_classifier(context).classify(text, filename="sample.js", extension=".js")

    assert result.category_path == "Technical/Source Code"


def test_web_page_text_classifies(context: AppContext) -> None:
    text = (
        "<!DOCTYPE html><html><body><div class='blob-code'>"
        "<span class='octicon'>Home</span></div><a href='/page'>Next</a></body></html>"
    )

    result = _new_classifier(context).classify(text, filename="sample.html", extension=".html")

    assert result.category_path == "Technical/Web Pages"


def test_calendar_text_classifies(context: AppContext) -> None:
    text = (
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:20240301T100000Z\n"
        "SUMMARY:Library Storytime\nLOCATION:Boulder Library\nEND:VEVENT\nEND:VCALENDAR"
    )

    result = _new_classifier(context).classify(text, filename="sample.ics", extension=".ics")

    assert result.category_path == "Personal/Calendar"


def test_embedding_corpus_excludes_vector_images(
    context: AppContext, sample_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.models import ExtractionResult

    natural = sample_library / "Downloads" / "natural.txt"
    vector = sample_library / "Downloads" / "drawing.svg"
    natural.write_text("natural language report content", encoding="utf-8")
    vector.write_text("<svg></svg>", encoding="utf-8")
    context.scanning.scan(sample_library)
    natural_id = context.files.find_by_path(natural)
    vector_id = context.files.find_by_path(vector)
    assert natural_id is not None and vector_id is not None

    context.analyses.save_extraction(
        natural_id, ExtractionResult(text="NATURAL_LANGUAGE_SENTENCE", method="test"), []
    )
    context.analyses.save_extraction(
        vector_id, ExtractionResult(text="VECTOR_HEX_NOISE", method="test"), []
    )

    corpus = context.analyses.embedding_corpus()

    assert any("NATURAL_LANGUAGE_SENTENCE" in text for text in corpus)
    assert not any("VECTOR_HEX_NOISE" in text for text in corpus)


REAL_JS_EXCERPT = """const Sequelize = require('sequelize')

module.exports = {
  up: async (query) => {
    // logic for transforming into the new state
    await query.addColumn(
      'user',
      'login_attempts',
      {
        type: Sequelize.DataTypes.INTEGER,
        defaultValue: 0
      }
    );
  },

  down: async (query) => {
    // logic for reverting the changes
    await query.removeColumn(
      'user',
      'login_attempts'
    );
  }
}"""

REAL_HTML_EXCERPT = """
<!DOCTYPE html>
  <!--[if lt IE 9]><html class="lte-ie8" lang="en"><![endif]-->
  <!--[if gt IE 8]><!--><html lang="en"><!--<![endif]-->
  <head>
    <meta charset="utf-8" />
    <title>Page not found - GOV.UK</title>

    <meta name="csrf-param" content="authenticity_token" />
<meta name="csrf-token" content="MmKT4G9SKHXEuDW39EPsBmM/lMkQToDgZLhiaJD5GhekQ5K1ZDdqPGBuU28oeCduUeILHN/e7PHedQE0Jz54Nw==" />

    <link rel="stylesheet" media="all" href="https://www.gov.uk/assets/static/application-5478f36bceddc980d41d88ac2c62f5e8bd86c4636e8709e82b5977b519eac643.css" />
    <link rel="stylesheet" media="print" href="https://www.gov.uk/assets/static/print-d064efa5655a3fa0079a27eb6214465ee2f1873bd3bad8ab46c3fc1ac05d5239.css" />
    <!--[if lt IE 9]><script src="https://www.gov.uk/assets/static/govuk_publishing_components/ie-a4524544a53d57a7e259b4bb966b9c32557c98c920b77e52d09304642b68401a.js" crossorigin="anonymous" integrity="sha256-pFJFRKU9V6fiWbS7lmucMlV8mMkgt35S0JMEZCtoQBo="></script><![endif]-->
    <link rel="shortcut icon" href="https://www.gov.uk/assets/static/favicon-8d811b8c3badbc0b0e2f6e25d3660a96cc0cca7993e6f32e98785f205fc40907.ico" type="image/x-icon" />
    <link rel="mask-icon" href="https://www.gov.uk/assets/static/govuk-mask-icon-de738c3fcce8ce2a91b67e89787090dc24a5cda0275ab6b75f6226c5b9619d3d.svg" color="#0b0c0c">
"""


def test_real_javascript_file_classifies_as_source_code(context: AppContext) -> None:
    result = _new_classifier(context).classify(
        REAL_JS_EXCERPT, filename="0001-js.js", extension=".js"
    )

    assert result.category_path == "Technical/Source Code"


def test_real_web_page_classifies_as_web_pages(context: AppContext) -> None:
    result = _new_classifier(context).classify(
        REAL_HTML_EXCERPT, filename="0001-html.html", extension=".html"
    )

    assert result.category_path == "Technical/Web Pages"
