"""Content-derived filenames and folders must stay short, safe and deterministic."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import fitz

from app.intelligence.content_naming import (
    grouping_relative_folder,
    resolve_suggestion,
    suggest_content_name,
    suggest_grouped_name,
)
from app.services.context import AppContext
from tests.conftest import write_text


def _profile(**overrides: object) -> dict[str, object]:
    profile: dict[str, object] = {
        "organisation": None,
        "document_type": None,
        "document_date": None,
        "keywords": [],
        "title": None,
    }
    profile.update(overrides)
    return profile


def test_manual_gets_entity_type_name() -> None:
    name = suggest_content_name(
        "gferlhlf.pdf",
        "HLF Helicopter flight manual. Operation and maintenance procedures.",
        _profile(document_type="Manual"),
        [],
        [],
        [],
    )

    assert name == "HLFManual.pdf"


def test_invoice_gets_entity_type_name() -> None:
    name = suggest_content_name(
        "123825ofsaolkd.incoive",
        "Meta Invoice. Bill to: Meta Platforms, Inc. Invoice number: 123825.",
        _profile(document_type="Invoice"),
        [],
        [],
        [],
        extension=".PDF",
    )

    assert name == "MetaInvoice.PDF"


def test_grouped_subtype_beats_date() -> None:
    name = suggest_grouped_name("Meta", "Invoice", "Statement", "2026-03-14", ".pdf", 0)

    assert name == "Statement.pdf"


def test_grouped_date_fallback() -> None:
    name = suggest_grouped_name("Meta", "Invoice", None, "2026-03-14", ".pdf", 0)

    assert name == "2026-03-14.pdf"


def test_existing_folder_becomes_entity() -> None:
    name = suggest_content_name(
        "gferlhlf.pdf",
        "Operation and maintenance procedures for the aircraft.",
        _profile(document_type="Manual"),
        [],
        [],
        [],
        relative_parent="HLF/Manuals",
    )

    assert name == "HLFManual.pdf"


def test_existing_parent_folder_preserved_with_date_name() -> None:
    decision = resolve_suggestion(
        original_name="foo.pdf",
        text="INVOICE\nInvoice number: INV-9\nPayment terms: 30 days.",
        profile=_profile(document_type="Invoice", document_date="2026-03-14"),
        keywords=[],
        existing_names=[],
        reserved_names=[],
        relative_parent="Meta/Invoices",
        existing_folders=["Meta/Invoices"],
    )

    assert decision.applied is True
    assert decision.relative_folder == "Meta/Invoices"
    assert decision.filename == "2026-03-14.pdf"


def test_generic_parent_is_ignored() -> None:
    decision = resolve_suggestion(
        original_name="Odd Name.txt",
        text="ordinary text with no company or document type",
        profile=_profile(),
        keywords=[],
        existing_names=[],
        reserved_names=[],
        relative_parent="Downloads",
    )

    assert decision.applied is False
    assert decision.filename == "Odd Name.txt"
    assert "Downloads" not in decision.filename


def test_no_organisation_root_parent_not_entity() -> None:
    decision = resolve_suggestion(
        original_name="manual.txt",
        text="Operation and maintenance procedures.",
        profile=_profile(document_type="Manual"),
        keywords=[],
        existing_names=[],
        reserved_names=[],
        relative_parent=None,
    )

    assert decision.applied is False
    assert decision.filename == "manual.txt"


def test_original_extension_case_preserved() -> None:
    name = suggest_content_name(
        "gferlhlf.PDF",
        "HLF Helicopter flight manual.",
        _profile(document_type="Manual"),
        [],
        [],
        [],
    )

    assert name == "HLFManual.PDF"


def test_low_confidence_keeps_original_suggestion() -> None:
    name = suggest_content_name(
        "Odd Name.txt",
        "qwerty zxcvbn random words",
        _profile(),
        [],
        [],
        [],
    )

    assert name == "Odd Name.txt"


def test_collision_suffix_has_no_doubled_extension() -> None:
    name = suggest_content_name(
        "random.pdf",
        "Meta Invoice for services rendered.",
        _profile(document_type="Invoice"),
        [],
        ["MetaInvoice.pdf"],
        [],
    )

    assert name == "MetaInvoice 2.pdf"


def test_no_hash_amount_or_long_number_in_name() -> None:
    name = suggest_content_name(
        "123825ofsaolkd.pdf",
        "Meta Invoice. Invoice number: INV-2024-0042. Amount due: 1,500.00.",
        _profile(document_type="Invoice"),
        [],
        [],
        [],
    )

    assert name == "MetaInvoice.pdf"
    assert "2024" not in name
    assert "1500" not in name


def test_grouping_folder_matches_existing_case_insensitively() -> None:
    folder = grouping_relative_folder("Meta", "Invoice", ["meta/invoices"])

    assert folder == "meta/invoices"


def test_duplicate_reuse_gets_the_same_content_name(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    text = (
        "HLF Helicopter flight manual.\n"
        "Operation and maintenance procedures for the aircraft.\n"
    )
    write_text(root / "gferlhlf.txt", text)
    write_text(root / "123825ofsaolkd.txt", text)

    scan = context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)

    assert scan.discovered == 2
    assert report.analysed == 2
    for path in root.glob("*.txt"):
        file_id = context.files.find_by_path(path)
        assert file_id is not None
        suggestions = context.analyses.suggestions_for_file(file_id)
        assert suggestions["filename"].suggested_value == "HLFManual.txt"


def test_manual_filename_edit_survives_reanalysis(context: AppContext, analysed_library: Path) -> None:
    file_id = context.files.find_by_path(
        analysed_library / "Downloads" / "invoice_acme_2024.txt"
    )
    assert file_id is not None
    result = context.recommendations.set_filename(file_id, "My Chosen Invoice")
    assert result.ok is True

    report = context.analysis.analyse_pending(use_llm=False, force=True)
    assert report.failed == 0
    report = context.analysis.analyse_pending(use_llm=False, force=True)

    assert report.failed == 0
    suggestions = context.analyses.suggestions_for_file(file_id)
    assert suggestions["filename"].suggested_value == "My Chosen Invoice.txt"


def test_content_naming_decision_is_recorded(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_text(
        root / "gferlhlf.txt",
        "HLF Helicopter flight manual. Operation and maintenance procedures.",
    )

    context.scanning.scan(root)
    context.analysis.analyse_pending(use_llm=False)

    with sqlite3.connect(context.config.db_path) as connection:
        extra = connection.execute(
            "select extra from document_analyses order by id desc limit 1"
        ).fetchone()[0]
    assert json.loads(extra)["rule_decision"] == "content-naming"


def test_integrated_manual_extension_case_is_preserved(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    write_text(
        root / "gferlhlf.PDF",
        "HLF Helicopter flight manual. Operation and maintenance procedures.",
    )

    context.scanning.scan(root)
    context.analysis.analyse_pending(use_llm=False)

    file_id = context.files.find_by_path(root / "gferlhlf.PDF")
    assert file_id is not None
    suggestions = context.analyses.suggestions_for_file(file_id)
    assert suggestions["filename"].suggested_value == "HLFManual.PDF"


def test_integrated_detected_extension_replaces_misspelled_suffix(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((24, 48), "Meta Invoice for services rendered.")
    pdf.save(root / "123825ofsaolkd.incoive")
    pdf.close()

    context.scanning.scan(root)
    context.analysis.analyse_pending(use_llm=False)

    file_id = context.files.find_by_path(root / "123825ofsaolkd.incoive")
    assert file_id is not None
    suggestions = context.analyses.suggestions_for_file(file_id)
    assert suggestions["filename"].suggested_value == "MetaInvoice.PDF"


def test_batch_analysis_does_not_query_suggestions_per_file(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    write_text(root / "a.txt", "Alpha document text.")
    write_text(root / "b.txt", "Beta document text.")
    calls: list[int] = []
    original = context.analyses.suggestions_for_file

    def counting_suggestions(file_id: int):
        calls.append(file_id)
        return original(file_id)

    monkeypatch.setattr(context.analyses, "suggestions_for_file", counting_suggestions)

    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)

    assert report.failed == 0
    assert calls == []
