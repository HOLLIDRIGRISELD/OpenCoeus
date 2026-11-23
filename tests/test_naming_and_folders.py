"""Filename generation/validation and folder recommendation."""

from __future__ import annotations

from pathlib import Path

from app.domain.models import ClassificationResult, DocumentProfile
from app.intelligence.entities import clean_title_from_filename, extract_title
from app.intelligence.folder_recommender import FolderRecommender
from app.intelligence.naming_engine import FilenameValidator, NamingEngine


def _classification(path: str = "Finance/Invoices", confidence: float = 0.9) -> ClassificationResult:
    primary, _, secondary = path.partition("/")
    return ClassificationResult(
        primary_category=primary,
        secondary_category=secondary or None,
        category_path=path,
        confidence=confidence,
        method="hybrid(test)",
    )


def _profile(title: str | None, *, supported: bool = True) -> DocumentProfile:
    return DocumentProfile(
        file_id=1,
        title=title,
        document_type="Invoice",
        organisation="Acme Ltd",
        document_date="2024-03-01",
        title_supported=supported,
    )


def test_validator_adds_extension_and_keeps_readable_name() -> None:
    result = FilenameValidator().validate("Quarterly Report", extension=".pdf")
    assert result.valid is True
    assert result.filename == "Quarterly Report.pdf"


def test_validator_sanitises_invalid_characters() -> None:
    result = FilenameValidator().validate('bad/name:here?*<>|".txt')
    assert result.valid is True
    assert not any(character in result.filename for character in '<>:"/\\|?*')
    assert result.warnings


def test_validator_rejects_empty_names() -> None:
    result = FilenameValidator().validate("   ")
    assert result.valid is False
    assert result.filename == ""


def test_validator_adjusts_windows_reserved_names() -> None:
    result = FilenameValidator().validate("con.txt")
    assert result.filename == "con document.txt"
    assert any("reserved" in warning.lower() for warning in result.warnings)


def test_validator_truncates_long_names() -> None:
    result = FilenameValidator(max_length=40).validate("word " * 50 + ".pdf")
    assert result.valid is True
    assert len(result.filename) <= 40
    assert result.filename.endswith(".pdf")


def test_deduplicate_is_case_insensitive() -> None:
    validator = FilenameValidator()
    name, warning = validator.deduplicate("Invoice.PDF", {"invoice.pdf", "invoice_2.pdf"})
    assert name == "Invoice 2.PDF"
    assert warning is not None


def test_naming_engine_renders_template_fields() -> None:
    suggestion = NamingEngine().suggest(
        profile=_profile("Q3 Financial Report"),
        classification=_classification("Finance/Statements"),
        original_name="statement_final.pdf",
        extension=".pdf",
        template="{date}_{organisation}_{title}",
    )

    assert suggestion.suggested_name == "2024 03 01 Acme Ltd Q3 Financial Report.pdf"
    assert suggestion.template == "{date}_{organisation}_{title}"
    assert suggestion.confidence > 0.5
    assert any("Date found" in item for item in suggestion.evidence)
    assert suggestion.changed is True


def test_naming_engine_uses_filename_fallback_and_lowers_confidence() -> None:
    engine = NamingEngine()
    supported = engine.suggest(
        profile=_profile("Lecture Notes", supported=True),
        classification=_classification("Education/Lecture Notes"),
        original_name="notes.txt",
        extension=".txt",
        template="{title}",
    )
    fallback = engine.suggest(
        profile=_profile("Lecture Notes", supported=False),
        classification=_classification("Education/Lecture Notes"),
        original_name="notes.txt",
        extension=".txt",
        template="{title}",
    )

    assert fallback.confidence < supported.confidence
    assert any("original filename" in warning for warning in fallback.warnings)


def test_naming_engine_avoids_existing_names() -> None:
    suggestion = NamingEngine().suggest(
        profile=_profile("Invoice"),
        classification=_classification(),
        original_name="invoice.txt",
        extension=".txt",
        template="{title}",
        existing_names={"Invoice.txt", "Invoice_2.txt"},
    )

    assert suggestion.suggested_name == "Invoice 2.txt"
    assert any("already exists" in warning for warning in suggestion.warnings)


def test_unsupported_title_preserves_meaningful_original_instead_of_type_label() -> None:
    suggestion = NamingEngine().suggest(
        profile=_profile("Contract", supported=False),
        classification=_classification("Business/Contracts"),
        original_name="agreement.docx",
        extension=".docx",
        template="{title}",
    )

    assert suggestion.suggested_name == "agreement.docx"


def test_naming_engine_falls_back_when_template_has_no_known_tokens() -> None:
    suggestion = NamingEngine().suggest(
        profile=_profile("Budget Forecast"),
        classification=_classification("Finance/Statements"),
        original_name="budget.xlsx",
        extension=".xlsx",
        template="{unknown_token}",
    )
    assert suggestion.suggested_name.startswith("Budget Forecast")
    assert suggestion.suggested_name.endswith(".xlsx")


def test_folder_recommender_builds_bounded_relative_path() -> None:
    recommendation = FolderRecommender(max_depth=4).recommend(
        root=Path("/library"),
        classification=_classification("Education/Research/Papers"),
    )
    assert recommendation.relative_destination == Path("Education/Research/Papers")
    assert recommendation.absolute_destination == Path("/library/Education/Research/Papers")
    assert recommendation.is_new is True
    assert recommendation.confidence > 0


def test_folder_recommender_reuses_existing_folder_case_insensitively() -> None:
    recommendation = FolderRecommender().recommend(
        root=Path("/library"),
        classification=_classification("Finance/Invoices"),
        existing_folders={Path("finance/invoices")},
    )
    assert recommendation.relative_destination == Path("finance/invoices")
    assert "Reused" in recommendation.explanation


def test_folder_recommender_respects_max_depth() -> None:
    recommendation = FolderRecommender(max_depth=2).recommend(
        root=Path("/library"),
        classification=_classification("A/B/C/D"),
    )
    assert recommendation.relative_destination == Path("A/B")


def test_extract_title_skips_code_markup_csv_and_property_lines() -> None:
    text = "\n".join(
        [
            "const Sequelize = require('sequelize')",
            '<?xml version="1.0" encoding="UTF-8"?>',
            "BEGIN:VCALENDAR",
            "Department family,Entity,Date,Expense type,Expense area,Supplier,Transaction,Amount",
            "Quarterly Infrastructure Report",
        ]
    )

    assert extract_title(text, "report.txt") == ("Quarterly Infrastructure Report", True)


def test_extract_title_skips_generic_repeated_headings() -> None:
    text = "\n".join(
        [
            "JPG Data Sets",
            "PowerPoint Presentation",
            "Blackpool Library Newsletter",
        ]
    )

    assert extract_title(text, "newsletter.txt") == ("Blackpool Library Newsletter", True)


def test_extract_title_uses_ics_summary_value() -> None:
    text = "BEGIN:VCALENDAR\nSUMMARY: Read and Tea.\nEND:VCALENDAR"

    assert extract_title(text, "calendar.ics") == ("Read and Tea", True)


def test_extract_title_falls_back_when_top_lines_are_generic_labels() -> None:
    text = "\n".join(
        [
            "JPG Data Sets",
            "Description",
            "Creation",
            "Information",
            "Related Data Sets",
            "Provenance",
            "License",
            "Edinburgh Napier University License Agreement",
            "Dataset Contents",
            "This dataset contains five thousand examples of file created in JPG format.",
        ]
    )

    assert extract_title(text, "quality-75-percent.pdf") == ("quality 75 percent", False)


def test_extract_title_uses_html_title_element(tmp_path: Path) -> None:
    from app.processing.extractors import ExtractorRegistry

    path = tmp_path / "page.html"
    path.write_text(
        "<!DOCTYPE html><html><head><title>Winter Travel Advice</title></head>"
        "<body><p>Road closures and diversions.</p></body></html>",
        encoding="utf-8",
    )

    assert ExtractorRegistry().extract(path, "text").title == "Winter Travel Advice"


def test_extract_title_uses_xml_title_element(tmp_path: Path) -> None:
    from app.processing.extractors import ExtractorRegistry

    path = tmp_path / "survey.xml"
    path.write_text(
        '<?xml version="1.0"?>\n<survey><title>Media Literacy Tracker</title></survey>',
        encoding="utf-8",
    )

    assert ExtractorRegistry().extract(path, "text").title == "Media Literacy Tracker"


def test_extract_title_rejects_document_id_and_amount_lines() -> None:
    text = "INVOICE\nInvoice number: INV-2024-0099\nAmount due: 42.00"

    assert extract_title(text, "statement.pdf") == ("statement", False)


def test_extract_title_rejects_licence_boilerplate() -> None:
    text = (
        '<?xml version="1.0"?>\n<!--\n * This file is part of the LibreOffice project.\n'
        " * This Source Code Form is subject to the terms of the Mozilla Public License.\n"
        "-->\n<menu:menupopup/>"
    )

    assert extract_title(text, "0002-xml.xml") == ("0002 xml", False)


def test_extract_title_rejects_licence_continuation_line() -> None:
    text = (
        "<!--\n * License, v. 2.0. If a copy of the MPL was not distributed with this\n"
        " * file, You can obtain one at http://mozilla.org/MPL/2.0/.\n-->\n<menu/>"
    )

    assert extract_title(text, "0002-xml.xml") == ("0002 xml", False)


def test_extract_title_drops_survey_markers_from_xml_title(tmp_path: Path) -> None:
    from app.processing.extractors import ExtractorRegistry

    path = tmp_path / "survey.xml"
    path.write_text(
        '<?xml version="1.0"?>\n<survey><title> &lt;FU&gt;Media Literacy Tracker 2017.'
        "&lt;FU&gt; Table &lt;&amp;IDENT1234567890</title></survey>",
        encoding="utf-8",
    )

    assert ExtractorRegistry().extract(path, "text").title == "Media Literacy Tracker 2017"


def test_extract_title_uses_email_subject() -> None:
    text = (
        "From: Transport for London <info@tfl.gov.uk>\n"
        "Sent: 13 July 2015 11:50\n"
        "Subject: Road closures in August\n\nDear Customer,\n"
    )

    assert extract_title(text, "notice.txt") == ("Road closures in August", True)


def test_extract_title_skips_greeting_lines() -> None:
    text = "Dear Customer,\n\nTravel advice\n\nRoad closures will affect east London."

    assert extract_title(text, "notice.txt") == ("Travel advice", True)


def test_extract_title_rejects_generic_title_with_site_suffix() -> None:
    text = "Page not found - GOV.UK\n\nThe page you are looking for does not exist."

    assert extract_title(text, "0001-html.html") == ("0001 html", False)


def test_clean_title_from_filename_keeps_identifying_number() -> None:
    assert clean_title_from_filename("0033-pptx.pptx") == "0033 pptx"


def test_validator_removes_syntax_characters_from_title() -> None:
    result = FilenameValidator().validate('xml version="1.0" encoding="UTF-8"', extension=".xml")

    assert result.filename == "xml version 1.0 encoding UTF 8.xml"
    assert "=" not in result.filename
    assert '"' not in result.filename


def test_naming_engine_sanitises_code_syntax_inside_supported_title() -> None:
    suggestion = NamingEngine().suggest(
        profile=_profile("const Sequelize = require('sequelize')"),
        classification=_classification("Technical/Source Code"),
        original_name="const_Sequelize_=_require('sequelize.js",
        extension=".js",
        template="{title}",
    )

    assert suggestion.suggested_name == "const Sequelize require sequelize.js"


def test_extractor_first_meaningful_line_ignores_code_and_markup() -> None:
    from app.processing.extractors.base import BaseExtractor

    text = "\n".join(
        [
            "const Sequelize = require('sequelize')",
            "<!DOCTYPE html>",
            "Quarterly Infrastructure Report",
        ]
    )

    assert BaseExtractor._first_meaningful_line(text) == "Quarterly Infrastructure Report"
