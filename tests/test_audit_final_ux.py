"""Regressions for naming and cancellation audit fixes."""

from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from app.domain.models import ClassificationResult, DocumentProfile  # noqa: E402
from app.intelligence.content_naming import resolve_suggestion, suggest_content_name  # noqa: E402
from app.intelligence.entities import extract_date, extract_title  # noqa: E402
from app.intelligence.naming_engine import NamingEngine  # noqa: E402


def test_labelled_entity_beats_acronym() -> None:
    name = suggest_content_name(
        "scan_0042.pdf",
        "Consulting services. Bill to: Meta Platforms, Inc.\nPO 9981 attached.",
        {"document_type": "Invoice"},
        [],
        [],
        [],
    )

    assert name == "MetaPlatformsInvoice.pdf"


def test_us_and_month_name_dates_are_full_iso() -> None:
    assert extract_date("Invoice date: 3/14/2026") == "2026-03-14"
    assert extract_date("Due March 14, 2026") == "2026-03-14"


def test_long_numeric_filename_prefix_is_stripped() -> None:
    title, supported = extract_title("ordinary words with no title", "123825ofsaolkd.pdf")

    assert supported is False
    assert title == "ofsaolkd"


def test_unsupported_title_uses_document_type() -> None:
    suggestion = NamingEngine().suggest(
        profile=DocumentProfile(
            file_id=1,
            title="123825ofsaolkd",
            document_type="Invoice",
            title_supported=False,
        ),
        classification=ClassificationResult(
            primary_category="Finance",
            secondary_category="Invoices",
            category_path="Finance/Invoices",
            confidence=0.9,
            method="test",
        ),
        original_name="123825ofsaolkd.pdf",
        extension=".pdf",
    )

    assert suggestion.suggested_name == "Invoice.pdf"


def _invoice_decision(existing_names: list[str]):
    return resolve_suggestion(
        original_name="scan.pdf",
        text=(
            "INVOICE\nInvoice number: INV-1\nBill to: Meta Platforms, Inc."
            "\nDate: 2026-03-14.\n"
        ),
        profile={
            "organisation": "Meta",
            "document_type": "Invoice",
            "document_date": "2026-03-14",
        },
        keywords=[],
        existing_names=existing_names,
        reserved_names=[],
        relative_parent="Meta/Invoices",
        existing_folders=["Meta/Invoices"],
    )


def test_two_same_date_invoices_get_distinct_grouped_names() -> None:
    first = _invoice_decision([])
    second = _invoice_decision([first.filename])

    assert first.filename == "2026-03-14.pdf"
    assert second.filename == "2026-03-14 2.pdf"


def test_subtype_hint_from_prose_does_not_override_type() -> None:
    decision = resolve_suggestion(
        original_name="scan.pdf",
        text=(
            "INVOICE\nInvoice number: INV-1\nBill to: Meta Platforms, Inc."
            "\nDate: 2026-03-14.\nA receipt will be emailed to you."
        ),
        profile={
            "organisation": "Meta",
            "document_type": "Invoice",
            "document_date": "2026-03-14",
        },
        keywords=[],
        existing_names=[],
        reserved_names=[],
        relative_parent="Meta/Invoices",
        existing_folders=["Meta/Invoices"],
    )

    assert decision.filename == "2026-03-14.pdf"


def test_subtype_hint_requires_label_or_standalone_line() -> None:
    decision = resolve_suggestion(
        original_name="scan.pdf",
        text=(
            "INVOICE\nInvoice number: INV-1\nBill to: Meta Platforms, Inc."
            "\nDate: 2026-03-14.\nReceipt will be emailed to you."
        ),
        profile={
            "organisation": "Meta",
            "document_type": "Invoice",
            "document_date": "2026-03-14",
        },
        keywords=[],
        existing_names=[],
        reserved_names=[],
        relative_parent="Meta/Invoices",
        existing_folders=["Meta/Invoices"],
    )

    assert decision.filename == "2026-03-14.pdf"


def test_grouped_name_prefers_supported_title_over_subtype_and_date() -> None:
    decision = resolve_suggestion(
        original_name="scan.pdf",
        text=(
            "INVOICE\nQuarterly Infrastructure Services\nSubtype: Remittance"
            "\nDate: 2026-03-14.\n"
        ),
        profile={
            "organisation": "Meta",
            "document_type": "Invoice",
            "document_date": "2026-03-14",
            "title": "Quarterly Infrastructure Services",
            "title_supported": True,
        },
        keywords=[],
        existing_names=[],
        reserved_names=[],
        relative_parent="Meta/Invoices",
        existing_folders=["Meta/Invoices"],
    )

    assert decision.filename == "QuarterlyInfrastructureServices.pdf"


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_task_cancel_does_not_block_while_worker_runs(qt_app) -> None:
    from app.ui.workers import Task

    started = threading.Event()
    release = threading.Event()

    def work(_progress, token):
        token.begin()
        started.set()
        release.wait(2)
        token.finish()
        return "done"

    task = Task(work)
    thread = threading.Thread(target=task.run, daemon=True)
    thread.start()
    assert started.wait(2)

    started_at = time.perf_counter()
    task.cancel()
    elapsed = time.perf_counter() - started_at
    release.set()
    thread.join(2)

    assert elapsed < 0.2


def test_task_reports_finished_when_cancelled_after_work_returns(qt_app) -> None:
    from app.ui.workers import Task

    outcomes: list[tuple] = []

    def work(_progress, token):
        token.cancel(wait=False)
        return "done"

    task = Task(work)
    task.signals.finished.connect(lambda result: outcomes.append(("finished", result)))
    task.signals.cancelled.connect(lambda: outcomes.append(("cancelled",)))

    task.run()

    assert outcomes == [("finished", "done")]


def test_semantic_search_stops_when_token_is_cancelled() -> None:
    from app.core.progress import CancellationToken, OperationCancelled
    from app.search.semantic import SemanticSearch

    token = CancellationToken()
    consumed: list[int] = []

    def rows():
        for file_id in range(1, 6):
            consumed.append(file_id)
            if file_id == 2:
                token.cancel(wait=False)
            yield file_id, np.ones(4), f"chunk {file_id}"

    class FakeAnalyses:
        def iter_embeddings(self, model: str):
            return rows()

        def load_embeddings(self, model: str):
            return rows()

    class FakeEmbeddings:
        model_name = "fake"

        def encode_one(self, query: str):
            return np.ones(4)

    search = SemanticSearch(FakeAnalyses(), FakeEmbeddings())  # type: ignore[arg-type]

    with pytest.raises(OperationCancelled):
        search.search("query", cancel=token)

    assert consumed == [1, 2]


def test_search_service_propagates_cancellation() -> None:
    from app.core.progress import CancellationToken, OperationCancelled
    from app.domain.enums import SearchMode
    from app.services.search_service import SearchService

    token = CancellationToken()
    seen: dict[str, object] = {}

    class CancellingSemantic:
        def search(self, query: str, **kwargs: object):
            seen["cancel"] = kwargs.get("cancel")
            raise OperationCancelled

    service = SearchService(
        SimpleNamespace(),
        CancellingSemantic(),  # type: ignore[arg-type]
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    with pytest.raises(OperationCancelled):
        service.search("invoice", mode=SearchMode.SEMANTIC, cancel=token)

    assert seen["cancel"] is token


def test_hybrid_search_forwards_token_to_semantic() -> None:
    from app.core.progress import CancellationToken
    from app.search.hybrid import HybridSearch

    token = CancellationToken()
    seen: dict[str, object] = {}

    class FakeKeyword:
        def search(self, query: str, *, limit: int = 50):
            return []

    class FakeSemantic:
        def search(self, query: str, **kwargs: object):
            seen["cancel"] = kwargs.get("cancel")
            return []

    HybridSearch(FakeKeyword(), FakeSemantic()).search(  # type: ignore[arg-type]
        "invoice", cancel=token
    )

    assert seen["cancel"] is token


def test_search_page_passes_worker_token_to_service(qt_app, monkeypatch) -> None:
    from app.core.progress import CancellationToken
    from app.ui.pages.search import SearchPage

    seen: dict[str, object] = {}

    def fake_search(query: str, **kwargs: object):
        seen["cancel"] = kwargs.get("cancel")
        return SimpleNamespace(hits=[])

    page = SearchPage(SimpleNamespace(search=SimpleNamespace(search=fake_search)))
    captured: dict[str, object] = {}

    def fake_run_task(fn, **kwargs):
        captured["fn"] = fn
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(page, "run_task", fake_run_task)
    try:
        page.query_edit.setText("invoice")
        page.start_search()
        token = CancellationToken()
        token.begin()
        captured["fn"](lambda *_args: None, token)
    finally:
        page.deleteLater()

    assert seen["cancel"] is token
