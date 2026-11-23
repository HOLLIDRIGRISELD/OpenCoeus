"""Regressions for the analysis-engine audit fixes."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.constants import STATUS_PENDING_REVIEW
from app.domain.models import ClassificationResult
from app.infrastructure.models import DocumentAnalysis, File
from app.intelligence.llm import LocalLLMResult
from app.services.context import AppContext
from tests.conftest import write_text


def _uncertain_result() -> ClassificationResult:
    return ClassificationResult(
        primary_category="Finance",
        secondary_category="Invoices",
        category_path="Finance/Invoices",
        confidence=0.42,
        method="test-low-confidence",
        margin=0.01,
        needs_review=True,
    )


def test_duplicate_reuse_preserves_needs_review(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    write_text(root / "first.txt", "INVOICE\nAmount due: 10.00\n")
    write_text(root / "second.txt", "INVOICE\nAmount due: 10.00\n")

    monkeypatch.setattr(
        context.analysis, "_classify", lambda *args, **kwargs: _uncertain_result()
    )
    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)

    assert report.analysed == 2
    source_id = context.files.find_by_path(root / "first.txt")
    target_id = context.files.find_by_path(root / "second.txt")
    assert source_id is not None and target_id is not None
    assert context.files.get_record(source_id)["status"] == "pending_review"
    assert context.files.get_record(target_id)["status"] == "pending_review"

    source = context.analyses.latest_analysis(source_id)
    target = context.analyses.latest_analysis(target_id)
    assert source is not None and target is not None
    assert source.needs_review is True
    assert target.needs_review is True


def test_legacy_duplicate_clone_infers_needs_review_from_source_status(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "legacy"
    first = write_text(root / "first.txt", "same content")
    second = write_text(root / "second.txt", "same content")
    context.scanning.scan(root)
    source_id = context.files.find_by_path(first)
    target_id = context.files.find_by_path(second)
    assert source_id is not None and target_id is not None

    with context.db.session() as session:
        session.add(
            DocumentAnalysis(
                file_id=source_id,
                classification_method="legacy",
                extra={},
            )
        )
        session.flush()
        source = session.get(File, source_id)
        assert source is not None
        source.processing_status = STATUS_PENDING_REVIEW

    assert context.analyses.clone_analysis(source_id, target_id) is True

    target = context.analyses.latest_analysis(target_id)
    assert target is not None and target.needs_review is True


def test_quality_gate_rejects_opaque_filenames_when_content_exists() -> None:
    from tests.test_quality_gate import assert_semantic_filename

    assert_semantic_filename("AcmeInvoice.pdf", "scan_001.pdf", "INVOICE\nAmount due: 10.00")
    assert_semantic_filename("invoice.txt", "invoice.txt", "")
    for opaque in ("9f8a7b6c4d2e.txt", "123825ofsaolkd.txt"):
        with pytest.raises(AssertionError):
            assert_semantic_filename(opaque, opaque, "INVOICE\nAmount due: 10.00")


class _OfflineLLM:
    enabled = True
    model = "stub-model"
    base_url = "http://127.0.0.1:11434"

    def __init__(self) -> None:
        self.health_calls = 0
        self.analysis_calls = 0

    def health(self) -> tuple[bool, str]:
        self.health_calls += 1
        return False, "offline"

    def analyze_document(self, text: str, categories: list[str]) -> LocalLLMResult:
        self.analysis_calls += 1
        raise AssertionError("offline model must not be called")


def test_failed_llm_probe_is_backed_off_during_batch(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    assert context.settings.update({"app.enable_llm": True}) == []
    root = tmp_path / "library"
    for index in range(3):
        write_text(
            root / f"narrative_{index}.txt",
            "Narrative prose about quarterly activities and planned work. " * 4,
        )

    monkeypatch.setattr(
        context.analysis,
        "_classify",
        lambda *args, **kwargs: ClassificationResult(
            primary_category="Unclassified",
            secondary_category=None,
            category_path="Unclassified",
            confidence=0.41,
            method="test-low-confidence",
            margin=0.01,
            needs_review=True,
        ),
    )
    monkeypatch.setattr(
        "app.services.analysis_service.extract_title", lambda *args: (None, False)
    )
    client = _OfflineLLM()
    context.analysis._llm = client
    context.scanning.scan(root)

    report = context.analysis.analyse_pending(use_llm=True)

    assert report.analysed == 3
    assert client.health_calls == 1
    assert client.analysis_calls == 0


class _StubLLM:
    enabled = True
    model = "stub-model"
    base_url = "http://127.0.0.1:11434"

    def health(self) -> tuple[bool, str]:
        return True, "stub online"

    def analyze_document(self, text: str, categories: list[str]) -> LocalLLMResult:
        return LocalLLMResult(
            title="Verified Annual Report",
            organisation="Acme Systems Ltd",
            document_date="2024-05-01",
            confidence=0.91,
            evidence=["The document text supports these fields."],
        )


def test_llm_naming_fields_are_applied_before_suggestions(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    assert context.settings.update({"app.enable_llm": True}) == []
    root = tmp_path / "library"
    target = root / "9f8a7b6c.txt"
    write_text(target, "Narrative prose about quarterly activities and planned work. " * 4)

    monkeypatch.setattr(
        context.analysis,
        "_classify",
        lambda *args, **kwargs: ClassificationResult(
            primary_category="Unclassified",
            secondary_category=None,
            category_path="Unclassified",
            confidence=0.41,
            method="test-low-confidence",
            margin=0.01,
            needs_review=True,
        ),
    )
    monkeypatch.setattr(
        "app.services.analysis_service.extract_title", lambda *args: (None, False)
    )
    context.analysis._llm = _StubLLM()
    context.scanning.scan(root)
    file_id = context.files.find_by_path(target)
    assert file_id is not None

    context.analysis.analyse_file(file_id, use_llm=True)

    suggestions = context.analyses.suggestions_for_file(file_id)
    filename = suggestions["filename"].suggested_value
    assert "9f8a7b6c" not in filename

    with context.db.session() as session:
        row = session.scalar(
            select(DocumentAnalysis)
            .where(DocumentAnalysis.file_id == file_id)
            .order_by(DocumentAnalysis.id.desc())
        )
    assert row is not None
    assert row.document_title == "Verified Annual Report"
    assert row.organisation == "Acme Systems Ltd"
    assert row.document_date == "2024-05-01"
