"""Incremental scan and analysis caches survive a session reset."""

from __future__ import annotations

from pathlib import Path

from app.services import scanning_service
from app.services.context import AppContext
from tests.test_quality_gate import _library, _snapshot


def test_analysis_survives_reset_without_reextracting(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    expected_texts = _library(root)

    original = context.analysis._extract
    calls: list[str] = []

    def counting_extract(path, detected, filename):
        calls.append(filename)
        return original(path, detected, filename)

    context.analysis._extract = counting_extract

    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.failed == 0
    assert report.analysed == len(expected_texts) + 4
    first_calls = len(calls)
    first_snapshot = _snapshot(context, root)

    context.db.purge_session_data()
    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.failed == 0
    assert len(calls) == first_calls
    assert _snapshot(context, root) == first_snapshot


def test_unchanged_files_are_not_rehashed(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _library(root)

    original = scanning_service.sha256_file
    calls: list[Path] = []

    def counting_hash(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(scanning_service, "sha256_file", counting_hash)

    context.scanning.scan(root)
    first = len(calls)
    assert first > 0

    context.db.purge_session_data()
    context.scanning.scan(root)
    assert len(calls) == first
