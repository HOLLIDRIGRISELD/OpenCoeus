"""Regressions for the search/performance/UI audit slice."""

from __future__ import annotations

import os
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from app.services.context import AppContext  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _listen_for_sql(engine, needle: str, statements: list[str]):
    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if needle in lowered:
            statements.append(lowered)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    return before_cursor_execute


def test_load_embeddings_uses_bounded_query(context: AppContext, analysed_library: Path) -> None:
    statements: list[str] = []
    engine = context.db.engine
    listener = _listen_for_sql(engine, "embedding_blobs", statements)

    rows = context.analyses.load_embeddings(context.embeddings.model_name)

    event.remove(engine, "before_cursor_execute", listener)
    assert statements
    assert any("limit" in statement for statement in statements)
    assert rows


def test_embedding_corpus_bounds_text_loaded_from_database(
    context: AppContext, analysed_library: Path
) -> None:
    statements: list[str] = []
    engine = context.db.engine
    listener = _listen_for_sql(engine, "document_contents", statements)

    corpus = context.analyses.embedding_corpus()

    event.remove(engine, "before_cursor_execute", listener)
    assert statements
    assert any("limit" in statement for statement in statements)
    assert any("substr" in statement for statement in statements)
    assert corpus


def test_cold_scan_reuses_stored_hash_size_and_mtime(
    config, tmp_path: Path, monkeypatch
) -> None:
    from app.services import scanning_service

    root = tmp_path / "library"
    root.mkdir()
    (root / "a.txt").write_text("invoice alpha", encoding="utf-8")
    (root / "b.txt").write_text("invoice beta", encoding="utf-8")

    original = scanning_service.sha256_file
    calls: list[Path] = []

    def counting_hash(path: Path) -> str:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(scanning_service, "sha256_file", counting_hash)

    first = AppContext(config)
    first.scanning.scan(root)
    first.close()
    assert len(calls) == 2

    second = AppContext(config)
    report = second.scanning.scan(root)
    second.close()

    assert len(calls) == 2
    assert report.hashed == 0


def test_cancel_waits_for_registered_worker_to_finish() -> None:
    from app.core.progress import CancellationToken

    token = CancellationToken()
    assert hasattr(token, "begin") and hasattr(token, "finish")

    started = threading.Event()
    release = threading.Event()
    finished: list[str] = []

    def worker() -> None:
        token.begin()
        started.set()
        assert token.event.wait(2)
        release.wait(2)
        token.finish()
        finished.append("done")

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(2)

    cancel_returned = threading.Event()

    def cancel() -> None:
        token.cancel()
        cancel_returned.set()

    canceller = threading.Thread(target=cancel)
    canceller.start()
    assert not cancel_returned.wait(0.2), "cancel returned before worker finished"

    release.set()
    assert cancel_returned.wait(2)
    thread.join(2)
    canceller.join(2)
    assert finished == ["done"]


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def test_docx_extract_rejects_archives_with_too_many_entries(
    tmp_path: Path, monkeypatch
) -> None:
    from app.core.exceptions import ExtractionError
    from app.processing.extractors import archive as archive_module
    from app.processing.extractors.docx import DocxExtractor

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_ENTRIES", 5)
    path = tmp_path / "many.docx"
    _write_zip(path, {f"word/item{i}.xml": b"x" for i in range(6)})

    with pytest.raises(ExtractionError, match="entries"):
        DocxExtractor().extract(path)


def test_xlsx_extract_rejects_archives_with_excess_uncompressed_size(
    tmp_path: Path, monkeypatch
) -> None:
    from app.core.exceptions import ExtractionError
    from app.processing.extractors import archive as archive_module
    from app.processing.extractors.xlsx import XlsxExtractor

    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 512)
    path = tmp_path / "bomb.xlsx"
    _write_zip(path, {"xl/worksheets/sheet1.xml": b"0" * 2048})

    with pytest.raises(ExtractionError, match="uncompressed"):
        XlsxExtractor().extract(path)


def test_dashboard_counts_exclude_unavailable_files(qt_app, context, sample_library: Path) -> None:
    from app.services.context import AppContext as Context
    from app.ui.pages.dashboard import DashboardPage

    assert isinstance(context, Context)
    context.scanning.scan(sample_library)
    file_id = context.files.find_by_path(sample_library / "Downloads" / "invoice_acme_2024.txt")
    assert file_id is not None
    context.files.mark_missing(file_id)

    page = DashboardPage(context)
    try:
        assert page.cards["total"].value_label.text() == "3"
    finally:
        page.deleteLater()


def test_search_cancel_button_delegates_to_running_task(qt_app, context, monkeypatch) -> None:
    from app.ui.pages.search import SearchPage

    page = SearchPage(context)
    calls: list[str] = []
    captured: dict[str, object] = {}
    fake_task = SimpleNamespace(cancel=lambda: calls.append("cancel"))

    def fake_run_task(_fn, **kwargs):
        captured.update(kwargs)
        return fake_task

    monkeypatch.setattr(page, "run_task", fake_run_task)
    try:
        page.query_edit.setText("invoice")
        page.start_search()

        assert page.cancel_button.isEnabled()
        assert page._pending

        page.cancel_button.click()

        assert calls == ["cancel"]
        assert page._pending
        assert "on_cancelled" in captured

        captured["on_cancelled"]()
        assert not page._pending
        assert not page.cancel_button.isEnabled()
    finally:
        page.deleteLater()
