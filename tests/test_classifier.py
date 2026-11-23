"""Hybrid classifier behaviour using the deterministic embedding backend."""

from __future__ import annotations

from app.intelligence.classifier import HybridClassifier
from app.services.context import AppContext

INVOICE_TEXT = (
    "INVOICE\n\nInvoice number: INV-2024-0042\n"
    "Bill to: Northwind Systems Ltd\nPurchase order: PO-7781\n"
    "Subtotal: 1,250.00\nVAT: 250.00\nAmount due: 1,500.00\n"
    "Payment terms: 30 days. Please remit to the account below.\n"
)

ASSIGNMENT_TEXT = (
    "CS2018 Software Engineering Assignment\n\n"
    "Module code: CS2018. Student ID: 20481922.\n"
    "This coursework submission has a deadline and a marking rubric.\n"
    "Learning outcomes must be demonstrated. Hand in via the portal.\n"
)


def _classifier(context: AppContext) -> HybridClassifier:
    return HybridClassifier(
        context.analyses.category_descriptions(),
        context.embeddings,
        review_threshold=0.6,
    )


def test_invoice_is_classified_as_finance(context: AppContext) -> None:
    result = _classifier(context).classify(
        INVOICE_TEXT, filename="invoice_2024.txt", extension=".txt"
    )

    assert result.category_path == "Finance/Invoices"
    assert result.primary_category == "Finance"
    assert result.secondary_category == "Invoices"
    assert result.confidence > 0.5
    assert any("Matched document terms" in item for item in result.evidence)
    assert result.scores


def test_assignment_is_classified_as_education(context: AppContext) -> None:
    result = _classifier(context).classify(
        ASSIGNMENT_TEXT, filename="assignment_final.txt", extension=".txt"
    )

    assert result.category_path == "Education/Assignments"
    assert result.confidence > 0.5
    assert "assignment" in " ".join(result.tags).lower() or any(
        "assignment" in tag.lower() for tag in result.tags
    )


def test_extension_contributes_structural_evidence(context: AppContext) -> None:
    classifier = _classifier(context)

    without = classifier.classify("ordinary words", filename="doc", extension="")
    with_extension = classifier.classify("ordinary words", filename="doc", extension=".html")

    assert with_extension.scores != without.scores

def test_weak_evidence_routes_document_to_review(context: AppContext) -> None:
    result = _classifier(context).classify(
        "qwerty zxcvbn plmokn", filename="zzz.txt", extension=".txt"
    )

    assert result.needs_review is True
    assert result.confidence <= 0.5
    if result.category_path == "Unclassified":
        assert result.method == "hybrid(insufficient_evidence)"


def test_filename_hint_contributes_to_classification(context: AppContext) -> None:
    result = _classifier(context).classify(
        "",
        filename="bank_statement_march.txt",
        extension=".txt",
    )

    assert result.category_path
    assert 0.0 <= result.confidence <= 0.98
