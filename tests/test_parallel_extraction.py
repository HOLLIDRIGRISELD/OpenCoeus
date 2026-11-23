"""Parallel pure-stage extraction with ordered, serial database writes."""

from __future__ import annotations

import threading
from pathlib import Path

from app.services.context import AppContext
from tests.conftest import write_text


def _library(root: Path, count: int) -> None:
    for index in range(count):
        write_text(
            root / f"invoice_{index:02d}.txt",
            f"INVOICE\nInvoice number: INV-{index}\nAmount due: {index}.00\n",
        )


def test_extractions_overlap_and_writes_stay_ordered(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _library(root, 4)

    original = context.analysis._extract
    barrier = threading.Barrier(2, timeout=5)

    def overlapping_extract(path, detected, filename):
        barrier.wait()
        return original(path, detected, filename)

    monkeypatch.setattr(context.analysis, "_extract", overlapping_extract)

    saved: list[int] = []
    original_save = context.analyses.save_analysis

    def recording_save(file_id, profile, classification, *, rule_decision=None, accepted_name=None):
        saved.append(file_id)
        return original_save(
            file_id,
            profile,
            classification,
            rule_decision=rule_decision,
            accepted_name=accepted_name,
        )

    monkeypatch.setattr(context.analyses, "save_analysis", recording_save)

    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)

    assert report.failed == 0
    assert report.analysed == 4
    assert saved == sorted(saved)


def test_extractor_registry_is_safe_for_concurrent_calls(
    context: AppContext, tmp_path: Path
) -> None:
    path = write_text(
        tmp_path / "invoice.txt",
        "INVOICE\nInvoice number: INV-2024-0042\nAmount due: 1,500.00\n",
    )
    expected = context.extractors.extract(path, "text")

    results: list[object] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(4, timeout=5)

    def run() -> None:
        try:
            barrier.wait()
            results.append(context.extractors.extract(path, "text"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(results) == 4
    assert all(result == expected for result in results)
