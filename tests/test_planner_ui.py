"""Planner page controls and their service calls."""

from __future__ import annotations

import os
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from app.services.context import AppContext  # noqa: E402
from app.ui.pages.planner import PlannerPage  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_preview_limit_drives_preview(
    qt_app,
    context: AppContext,
    analysed_library,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    original = context.organisation.build_preview

    def spy(*, limit: int, accepted_only: bool = False):
        calls.append(limit)
        return original(limit=limit, accepted_only=accepted_only)

    monkeypatch.setattr(context.organisation, "build_preview", spy)
    page = PlannerPage(context)
    try:
        assert page.preview_limit.value() == 500
        page.preview_limit.setValue(7)
        page.refresh()
        assert calls[-1] == 7
    finally:
        page.deleteLater()


def test_switching_plans_clears_stale_items_and_report(qt_app, context, monkeypatch) -> None:
    item = type(
        "Item",
        (),
        {
            "filename": "a.txt",
            "action": "rename",
            "destination_path": "out/a.txt",
            "notes": [],
            "confidence": 0.9,
            "conflict": None,
            "status": "pending",
        },
    )()
    summary = type("Summary", (), {"conflicts": 0})()
    plans = {1: {"status": "completed", "root_path": "root"}}
    monkeypatch.setattr(context.organisation, "plan", lambda plan_id: plans.get(plan_id))
    monkeypatch.setattr(context.organisation, "items", lambda plan_id: [item])
    monkeypatch.setattr(context.organisation, "summary", lambda plan_id, items=None: summary)

    page = PlannerPage(context)
    try:
        page._load_plan(1)
        assert page.plan_items_table.rowCount() == 1
        assert "already been executed" in page.report_browser.toPlainText()

        page._load_plan(2)

        assert page.plan_items_table.rowCount() == 0
        assert "already been executed" not in page.report_browser.toPlainText()

        plans[3] = {"status": "draft", "root_path": "root"}
        page._load_plan(3)

        assert "Plan #3" in page.report_browser.toPlainText()
        assert "already been executed" not in page.report_browser.toPlainText()
    finally:
        page.deleteLater()


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        ("_execute_done", "Execution finished"),
        ("_execute_failed", "Execution failed: boom"),
        ("_execute_cancelled", "Execution cancelled"),
    ],
)
def test_execution_report_survives_plan_reload(
    qt_app, context, monkeypatch, handler, expected
) -> None:
    item = type(
        "Item",
        (),
        {
            "filename": "a.txt",
            "action": "rename",
            "destination_path": "out/a.txt",
            "notes": [],
            "confidence": 0.9,
            "conflict": None,
            "status": "pending",
        },
    )()
    summary = type("Summary", (), {"conflicts": 0})()
    monkeypatch.setattr(context.organisation, "plan", lambda plan_id: {"status": "completed", "root_path": "root"})
    monkeypatch.setattr(context.organisation, "items", lambda plan_id: [item])
    monkeypatch.setattr(context.organisation, "summary", lambda plan_id, items=None: summary)
    monkeypatch.setattr(
        context.organisation,
        "list_plans",
        lambda limit=50: [
            {
                "id": 1,
                "status": "completed",
                "item_count": 1,
                "root_path": "root",
                "created_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "critical", lambda *args, **kwargs: None
    )

    page = PlannerPage(context)
    try:
        page._current_plan_id = 1
        if handler == "_execute_done":
            page._execute_done(
                types.SimpleNamespace(
                    completed=[],
                    failed=[],
                    skipped=[],
                    summary="all good",
                    duration_seconds=1.0,
                )
            )
        elif handler == "_execute_failed":
            page._execute_failed("boom")
        else:
            page._execute_cancelled()

        assert expected in page.report_browser.toPlainText()
    finally:
        page.deleteLater()


def test_save_plan_uses_preview_limit_and_new_plan_returns_to_preview(
    qt_app,
    context: AppContext,
    analysed_library,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    original = context.organisation.create_plan

    def spy(*, limit: int, accepted_only: bool = False) -> int:
        calls.append(limit)
        return original(limit=limit, accepted_only=accepted_only)

    monkeypatch.setattr(context.organisation, "create_plan", spy)
    page = PlannerPage(context)
    try:
        page.preview_limit.setValue(3)
        page._save_plan()
        assert calls == [3]
        assert page.tabs.currentIndex() == 1
        assert page._current_plan_id is not None

        page.new_plan_button.click()

        assert page.tabs.currentIndex() == 0
        assert page._current_plan_id is None
        assert not page.plans_table.selectionModel().hasSelection()
    finally:
        page.deleteLater()
