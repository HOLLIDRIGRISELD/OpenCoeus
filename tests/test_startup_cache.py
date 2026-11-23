"""Startup behaviour: each launch starts from a clean library."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import AppConfig
from app.infrastructure.models import (
    Category,
    DocumentAnalysis,
    EmbeddingCacheEntry,
    File,
    Operation,
    OrganisationPlan,
    PlanItem,
    Setting,
    Suggestion,
)
from app.services.context import AppContext
from tests.conftest import file_id_for, write_text


def test_starting_the_app_forgets_the_previous_session(
    config: AppConfig, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    path = write_text(
        root / "notice.txt",
        "INVOICE\n\nInvoice number: INV-2024-0042\nAmount due: 1,500.00\n",
    )

    first = AppContext(config)
    try:
        first.scanning.scan(root)
        report = first.analysis.analyse_pending(use_llm=False)
        assert report.analysed == 1
        file_id = file_id_for(first, path)
        with first.db.session() as session:
            plan = OrganisationPlan(root_path=str(root), status="draft")
            session.add(plan)
            session.flush()
            session.add(
                PlanItem(
                    plan_id=plan.id,
                    file_id=file_id,
                    action="move",
                    source_path=str(path),
                    destination_path=str(root / "Finance" / "invoice.txt"),
                    original_name=path.name,
                    new_name="invoice.txt",
                )
            )
            session.add(
                Operation(
                    file_id=file_id,
                    operation_type="move",
                    source_path=str(path),
                    destination_path=str(root / "Finance" / "invoice.txt"),
                    status="completed",
                )
            )
    finally:
        first.close()

    second = AppContext(config)
    try:
        assert second.files.list_summaries(limit=10) == []
        assert second.stats().total_files == 0
        assert second.stats().recent_operations == []
        with second.db.session() as session:
            for model in (
                File,
                DocumentAnalysis,
                Suggestion,
                OrganisationPlan,
                PlanItem,
                Operation,
                EmbeddingCacheEntry,
            ):
                assert session.query(model).count() == 0, model.__name__
            assert session.execute(text("select count(*) from file_fts")).scalar() == 0
            assert session.query(Category).count() > 0
            assert session.query(Setting).count() > 0
    finally:
        second.close()


def test_cli_commands_keep_the_session(config: AppConfig, tmp_path: Path) -> None:
    from app.cli import main

    root = tmp_path / "library"
    write_text(root / "note.txt", "Invoice INV-1")
    first = AppContext(config)
    try:
        first.scanning.scan(root)
    finally:
        first.close()

    assert main(["--data-dir", str(config.data_dir), "stats", "--json"]) == 0

    with sqlite3.connect(config.data_dir / "opencoeus.db") as con:
        assert con.execute("select count(*) from files").fetchone()[0] >= 1


def test_gui_launch_keeps_the_previous_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.ui.app as gui

    calls: list[dict[str, object]] = []

    class FakeSettings:
        enable_llm = False

    class FakeContext:
        settings = FakeSettings()

        def close(self) -> None:
            return None

    class FakeQApplication:
        @staticmethod
        def setHighDpiScaleFactorRoundingPolicy(*_args: object) -> None:
            return None

        def __init__(self, _argv: object) -> None:
            return None

        def setApplicationName(self, _name: str) -> None:
            return None

        def setApplicationDisplayName(self, _name: str) -> None:
            return None

        def setApplicationVersion(self, _version: str) -> None:
            return None

        def setOrganizationName(self, _name: str) -> None:
            return None

        def setStyle(self, _name: str) -> None:
            return None

        def setStyleSheet(self, _stylesheet: str) -> None:
            return None

        def exec(self) -> int:
            return 0

    class FakeWindow:
        def __init__(self, _context: object) -> None:
            return None

        def show(self) -> None:
            return None

    monkeypatch.setattr(gui, "QApplication", FakeQApplication)
    monkeypatch.setattr(gui, "MainWindow", FakeWindow)
    monkeypatch.setattr(gui.AppContext, "create", lambda *_args, **kwargs: calls.append(kwargs) or FakeContext())

    assert gui.run([]) == 0
    assert calls == [{"purge": False}]
