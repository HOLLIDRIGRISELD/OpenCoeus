"""Naming conventions stay opt-in and outside the analysis cache key."""

from __future__ import annotations

from pathlib import Path

from app.domain.models import NamingSuggestion
from app.services.context import AppContext


def test_detect_convention_from_existing_names() -> None:
    from app.intelligence.conventions import apply_convention, detect_convention

    convention = detect_convention(["2026-Report-01", "2026-Report-02", "2026-Report-03"])

    assert convention is not None
    assert convention.separator == "-"
    assert convention.numeric_suffix == 2
    assert convention.next_sequence == 4
    assert apply_convention("Report-01.txt", convention) == "2026-Report-04.txt"


def test_default_off_keeps_golden(context: AppContext, sample_library: Path) -> None:
    context.scanning.scan(sample_library)
    context.analysis.analyse_pending(use_llm=False)

    assert context.settings.snapshot()["naming.use_conventions"] is False


def test_opt_on_rewrites_name_and_records_evidence(context: AppContext) -> None:
    suggestion = NamingSuggestion(
        original_name="report.txt",
        suggested_name="Report-01.txt",
        confidence=0.7,
        explanation="template",
        template="{title}",
    )
    assert context.analysis._apply_naming_conventions(suggestion, []) is suggestion

    assert context.settings.update({"naming.use_conventions": True}) == []
    rewritten = context.analysis._apply_naming_conventions(
        suggestion, ["2026-Report-01", "2026-Report-02"]
    )

    assert "convention" in " ".join(rewritten.evidence).lower()
    assert rewritten.suggested_name == "2026 Report 03.txt"


def test_convention_rewrite_never_collides(context: AppContext) -> None:
    suggestion = NamingSuggestion(
        original_name="report.txt",
        suggested_name="Report-03.txt",
        confidence=0.7,
        explanation="template",
        template="{title}",
    )
    names = ["2026-Report-01", "2026-Report-02", "2026-Report-03", "Report-03.txt"]
    assert context.settings.update({"naming.use_conventions": True}) == []

    rewritten = context.analysis._apply_naming_conventions(suggestion, names)

    assert rewritten.suggested_name not in names


def test_convention_setting_does_not_change_cache_prefix(context: AppContext) -> None:
    before = context.analysis._cache_signature(use_llm=False)

    assert context.settings.update({"naming.use_conventions": True}) == []

    assert context.analysis._cache_signature(use_llm=False) == before
