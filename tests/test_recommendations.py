"""Human-in-the-loop recommendation review and duplicate detection."""

from __future__ import annotations

from pathlib import Path

from app.domain.models import FolderSuggestion, NamingSuggestion
from app.services.context import AppContext
from tests.conftest import file_id_for


def test_pending_suggestions_include_filename_folder_and_evidence(
    context: AppContext, analysed_library: Path
) -> None:
    suggestions = context.recommendations.pending()

    assert len(suggestions) == 4
    assert all(suggestion.suggested_value for suggestion in suggestions)
    assert all(suggestion.destination for suggestion in suggestions)
    assert all(suggestion.category for suggestion in suggestions)

    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")
    detail = context.recommendations.detail(invoice_id)

    assert detail is not None
    assert detail.category == "Finance/Invoices"
    assert detail.suggested_name
    assert detail.suggested_folder == "Finance/Invoices"
    assert detail.naming_explanation
    assert detail.folder_explanation
    assert detail.evidence
    assert detail.confidence is not None and detail.confidence > 0


def test_accept_reject_and_reset_change_review_state(
    context: AppContext, analysed_library: Path
) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    context.recommendations.accept(invoice_id)
    accepted = next(item for item in context.recommendations.pending() if item.file_id == invoice_id)
    assert accepted.status == "accepted"

    context.recommendations.reject(invoice_id, reason="not an invoice in this context")
    pending_ids = {item.file_id for item in context.recommendations.pending()}
    assert invoice_id not in pending_ids

    context.recommendations.reset(invoice_id)
    restored = next(item for item in context.recommendations.pending() if item.file_id == invoice_id)
    assert restored.status == "pending"


def test_reanalysis_supersedes_accepted_suggestions(
    context: AppContext, analysed_library: Path
) -> None:
    """Re-analysing a file must not leave two active filename suggestions."""

    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")
    context.recommendations.accept(invoice_id)
    assert len([item for item in context.recommendations.pending() if item.file_id == invoice_id]) == 1

    from sqlalchemy import select

    from app.infrastructure.models import Suggestion

    old_ids = context.analyses.suggestion_ids_for_file(invoice_id)
    old_filename_id = old_ids["filename"]

    context.analyses.save_suggestions(
        invoice_id,
        NamingSuggestion(
            original_name="invoice_acme_2024.txt",
            suggested_name="Renamed_Invoice.txt",
            confidence=0.9,
            explanation="Re-analysed",
            template="test",
        ),
        FolderSuggestion(
            relative_destination=Path("Finance/Invoices"),
            absolute_destination=analysed_library / "Finance" / "Invoices",
            confidence=0.9,
            explanation="Re-analysed",
        ),
        category_path="Finance/Invoices",
    )

    active = [item for item in context.recommendations.pending() if item.file_id == invoice_id]
    assert len(active) == 1
    assert active[0].suggested_value == "Renamed_Invoice.txt"

    with context.db.session() as session:
        old = session.scalar(select(Suggestion).where(Suggestion.id == old_filename_id))
        assert old is not None and old.status == "superseded"


def test_manual_filename_edits_are_validated_and_accepted(
    context: AppContext, analysed_library: Path
) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    invalid = context.recommendations.set_filename(invoice_id, "   ")
    assert invalid.ok is False
    assert invalid.problems

    valid = context.recommendations.set_filename(invoice_id, "Acme Invoice 2024")
    assert valid.ok is True
    assert valid.value == "Acme Invoice 2024.txt"

    detail = context.recommendations.detail(invoice_id)
    assert detail is not None
    assert detail.suggested_name == "Acme Invoice 2024.txt"
    bundle = context.analyses.get_suggestion_bundle(invoice_id)
    assert bundle["filename_suggestion"]["confidence"] == 1.0
    assert bundle["filename_suggestion"]["explanation"].startswith("The filename was edited")


def test_manual_folder_edits_reject_escapes(context: AppContext, analysed_library: Path) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    absolute = context.recommendations.set_folder(invoice_id, "/etc")
    assert absolute.ok is False

    traversal = context.recommendations.set_folder(invoice_id, "../outside")
    assert traversal.ok is False

    valid = context.recommendations.set_folder(invoice_id, "Finance/Archive")
    assert valid.ok is True
    assert valid.value == "Finance/Archive"
    assert context.recommendations.detail(invoice_id).suggested_folder == "Finance/Archive"


def test_manual_category_override_updates_analysis_and_destination(
    context: AppContext, analysed_library: Path
) -> None:
    invoice_id = file_id_for(context, analysed_library / "Downloads" / "invoice_acme_2024.txt")

    context.recommendations.set_category(invoice_id, "Business/Reports")

    detail = context.recommendations.detail(invoice_id)
    assert detail.category == "Business/Reports"
    assert detail.method == "manual"
    assert detail.confidence == 1.0
    assert detail.suggested_folder == "Business/Reports"
    assert any("manually changed" in item.lower() for item in detail.evidence)


def test_duplicates_are_detected_by_content_hash(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "dupes"
    root.mkdir()
    content = "INVOICE\nInvoice number: INV-1\nAmount due: 10.00\n"
    (root / "invoice_a.txt").write_text(content, encoding="utf-8")
    (root / "invoice_b.txt").write_text(content, encoding="utf-8")
    (root / "other.txt").write_text("Something else entirely.", encoding="utf-8")

    context.scanning.scan(root)
    groups = context.recommendations.duplicates()

    assert len(groups) == 1
    assert groups[0].count == 2
    assert groups[0].wasted_bytes > 0
    assert {item["name"] for item in groups[0].files} == {"invoice_a.txt", "invoice_b.txt"}
    assert context.stats().duplicates == 1
