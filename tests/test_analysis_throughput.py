"""Analysis hot paths must reuse in-memory data and bound per-file statements."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import numpy as np
from sqlalchemy import event

from app.domain.models import DocumentChunk, ExtractionResult
from app.services import analysis_service
from app.services.context import AppContext
from tests.conftest import file_id_for, write_text


def _capture(engine) -> tuple[list[str], object]:
    statements: list[str] = []

    def before(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    return statements, before


def _stop(engine, listener) -> None:
    event.remove(engine, "before_cursor_execute", listener)


def _bulk_library(root: Path, size: int) -> None:
    for index in range(size):
        write_text(
            root / f"invoice_{index:03d}.txt",
            f"INVOICE\nInvoice number: INV-{index}\nBill to: Acme Systems Ltd\n"
            f"Subtotal: 10.00\nAmount due: 10.00\nPayment terms: 30 days.\n",
        )


def test_extracted_text_reused_for_fts(
    context: AppContext, sample_library: Path, monkeypatch
) -> None:
    calls: list[tuple[int, str]] = []
    original = context.indexer.index_file

    def spy(file_id: int, *, text: str | None = None) -> None:
        calls.append((file_id, text or ""))
        original(file_id, text=text)

    monkeypatch.setattr(context.indexer, "index_file", spy)

    context.scanning.scan(sample_library)
    context.analysis.analyse_pending(use_llm=False)

    assert len(calls) == 4
    assert all(text for _, text in calls)
    for file_id, text in calls:
        assert context.analyses.content_for(file_id) == text


def test_known_duplicate_is_not_extracted_twice(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    text = "INVOICE\nInvoice number: INV-1\nBill to: Acme Systems Ltd\nAmount due: 10.00\n"
    write_text(root / "first.txt", text)
    write_text(root / "second.txt", text)
    context.scanning.scan(root)

    calls: list[str] = []
    original_extract = context.analysis._extract

    def counting_extract(path: Path, detected: str, filename: str):
        calls.append(filename)
        return original_extract(path, detected, filename)

    monkeypatch.setattr(context.analysis, "_extract", counting_extract)

    report = context.analysis.analyse_pending(use_llm=False)

    assert report.analysed == 2
    assert calls == ["first.txt"]


def test_stale_duplicate_hash_still_extracts_changed_bytes(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    text = "INVOICE\nInvoice number: INV-1\nBill to: Acme Systems Ltd\nAmount due: 10.00\n"
    write_text(root / "first.txt", text)
    second = write_text(root / "second.txt", text)
    context.scanning.scan(root)

    changed = text.replace("INV-1", "INV-2")
    assert len(changed) == len(text)
    second.write_text(changed, encoding="utf-8")
    stat = second.stat()
    os.utime(second, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    calls: list[str] = []
    original_extract = context.analysis._extract

    def counting_extract(path: Path, detected: str, filename: str):
        calls.append(filename)
        return original_extract(path, detected, filename)

    monkeypatch.setattr(context.analysis, "_extract", counting_extract)

    report = context.analysis.analyse_pending(use_llm=False)

    assert report.analysed == 2
    assert sorted(calls) == ["first.txt", "second.txt"]
    assert "INV-2" in context.analyses.content_for(file_id_for(context, second))


def test_settings_read_once_per_batch(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _bulk_library(root, 20)
    context.scanning.scan(root)

    counts: Counter[str] = Counter()
    original = context.settings._repository.get

    def counting_get(key: str, default: str | None = None) -> str | None:
        counts[key] += 1
        return original(key, default)

    monkeypatch.setattr(context.settings._repository, "get", counting_get)
    context.analysis.analyse_pending(use_llm=False)

    for key in (
        "app.naming_template",
        "naming.use_conventions",
        "organisation.root",
        "app.low_confidence",
        "app.high_confidence",
        "embeddings.model",
    ):
        assert counts[key] <= 2, (key, counts[key])


def test_chunk_and_blob_writes_are_batched(context: AppContext, sample_library: Path) -> None:
    context.scanning.scan(sample_library)
    file_id = file_id_for(context, sample_library / "Downloads" / "invoice_acme_2024.txt")
    chunks = [
        DocumentChunk(index=index, text=f"chunk number {index} with content")
        for index in range(12)
    ]
    result = ExtractionResult(text="body", method="txt", success=True)
    vectors = [np.arange(8, dtype=float) for _ in chunks]

    statements, listener = _capture(context.db.engine)
    try:
        context.analyses.save_extraction(file_id, result, chunks)
        context.analyses.save_embeddings(file_id, context.embeddings.model_name, vectors)
    finally:
        _stop(context.db.engine, listener)

    inserts = [statement for statement in statements if "INSERT INTO" in statement.upper()]
    assert len([s for s in inserts if "document_chunks" in s]) == 1
    assert len([s for s in inserts if "embedding_blobs" in s]) == 1

    restored = context.analyses.chunks_for(file_id)
    assert [chunk.index for chunk in restored] == list(range(12))
    assert [chunk.text for chunk in restored] == [chunk.text for chunk in chunks]


def test_batch_reads_records_with_one_projection(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _bulk_library(root, 12)
    context.scanning.scan(root)

    calls: list[int] = []
    original = context.files.get_record

    def counting_get_record(file_id: int) -> dict[str, object] | None:
        calls.append(file_id)
        return original(file_id)

    monkeypatch.setattr(context.files, "get_record", counting_get_record)
    report = context.analysis.analyse_pending(use_llm=False)

    assert report.analysed == 12
    assert calls == []


def test_analysis_hashes_every_file_it_processes(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _bulk_library(root, 3)
    context.scanning.scan(root)

    calls: list[Path] = []
    original = analysis_service.sha256_file

    def counting_hash(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(analysis_service, "sha256_file", counting_hash)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.analysed == 3
    assert set(calls) == {root / f"invoice_{index:03d}.txt" for index in range(3)}

    calls.clear()
    changed = root / "invoice_000.txt"
    changed.write_text("INVOICE\nAmount due: 99999.00\n", encoding="utf-8")
    context.analysis.analyse_pending(use_llm=False, force=True)
    assert changed in calls
    assert set(calls) == {root / f"invoice_{index:03d}.txt" for index in range(3)}


def test_metadata_recheck_still_runs(
    context: AppContext, sample_library: Path, monkeypatch
) -> None:
    context.scanning.scan(sample_library)
    target = sample_library / "Documents" / "bank_statement_march.txt"
    file_id = file_id_for(context, target)

    original = context.analysis._prepare_extraction

    def prepare_then_delete(path: Path, detected: str, filename: str, record):
        prepared = original(path, detected, filename, record)
        if Path(path) == target:
            Path(path).unlink()
        return prepared

    monkeypatch.setattr(context.analysis, "_prepare_extraction", prepare_then_delete)
    report = context.analysis.analyse_pending(use_llm=False)

    assert context.files.get_record(file_id)["status"] == "unavailable"
    assert any("no longer exists" in error for _, error in report.errors)


def test_destination_names_read_once_per_folder(
    context: AppContext, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    _bulk_library(root, 20)
    context.scanning.scan(root)

    real_is_dir = Path.is_dir
    calls: list[Path] = []

    def counting_is_dir(folder: Path) -> bool:
        calls.append(folder)
        return real_is_dir(folder)

    monkeypatch.setattr(Path, "is_dir", counting_is_dir)
    context.analysis.analyse_pending(use_llm=False)

    folder_calls = [path for path in calls if not path.suffix]
    assert folder_calls
    assert len(folder_calls) < 20
