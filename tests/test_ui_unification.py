"""Regression tests for the unified desktop UI."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qt_app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_theme_roles_and_rich_text_rules() -> None:
    from app.ui.theme import STYLESHEET

    assert "QTextBrowser {" in STYLESHEET
    assert "QTextBrowser a {" in STYLESHEET
    assert 'QLabel[role="detail"]' in STYLESHEET
    assert 'QLabel[role="surface"]' in STYLESHEET
    assert 'QLabel[role="code"]' in STYLESHEET
    assert 'QLabel[role="field"]' in STYLESHEET


def test_shared_widgets_have_no_inline_hex() -> None:
    source = Path("app/ui/widgets.py").read_text(encoding="utf-8")
    assert "#1a2742" not in source
    assert 'setStyleSheet(f"color:' not in source


def test_add_actions_inserts_right_aligned_row(qt_app) -> None:
    from app.ui.widgets import add_actions

    layout = QtWidgets.QVBoxLayout()
    button = QtWidgets.QPushButton("Go")
    row = add_actions(layout, button)

    assert isinstance(row, QtWidgets.QHBoxLayout)
    assert layout.itemAt(0) is row
    assert row.itemAt(0).spacerItem() is not None
    assert row.itemAt(1).widget() is button


PAGE_MODULES = (
    "dashboard",
    "files",
    "history",
    "planner",
    "recommendations",
    "search",
    "settings",
)


def test_pages_have_no_inline_hex_colours() -> None:
    for name in PAGE_MODULES:
        source = Path(f"app/ui/pages/{name}.py").read_text(encoding="utf-8")
        assert re.search(r"#[0-9a-fA-F]{3,8}\b", source) is None, name


def test_pages_have_no_local_richtext_stylesheet() -> None:
    for name in PAGE_MODULES:
        source = Path(f"app/ui/pages/{name}.py").read_text(encoding="utf-8")
        assert "QTextBrowser { background: transparent" not in source, name


def test_rich_text_uses_tokens_and_escapes(qt_app, context) -> None:
    from app.ui.pages.dashboard import DashboardPage
    from app.ui.theme import RED

    page = DashboardPage(context)
    try:
        assert page.capability_label.property("role") == "surface"
        assert page.empty_hint.property("role") == "surface"
        assert page.empty_hint.styleSheet() == ""

        capability = type(
            "Capability",
            (),
            {
                "label": "<b>&",
                "detail": "x<y",
                "available": False,
                "required": True,
            },
        )()
        page.ctx = type(
            "Ctx",
            (),
            {"capabilities": staticmethod(lambda probe=False: [capability])},
        )()
        page._refresh_capabilities()
        text = page.capability_label.text()

        assert "&lt;b&gt;&amp;" in text
        assert "x&lt;y" in text
        assert "#c7d5ec" not in text
        assert RED in text
    finally:
        page.deleteLater()


def test_shared_widgets_are_used_by_pages() -> None:
    sources = {
        name: Path(f"app/ui/pages/{name}.py").read_text(encoding="utf-8")
        for name in PAGE_MODULES
    }

    assert "Badge(" in sources["dashboard"]
    for name in ("files", "history", "planner", "recommendations", "search"):
        assert "EmptyState(" in sources[name], name
    for name in ("dashboard", "files", "history", "recommendations", "settings"):
        assert "add_actions(" in sources[name], name
    for name in ("files", "recommendations", "search", "planner"):
        assert "separator()" in sources[name], name


def test_empty_state_widget_exposes_heading_and_detail(qt_app) -> None:
    from app.ui.widgets import EmptyState

    state = EmptyState("Nothing here", "Open Scan & analyse.")
    labels = state.findChildren(QtWidgets.QLabel)

    assert labels[0].text() == "Nothing here"
    assert labels[1].text() == "Open Scan & analyse."


def test_primary_action_per_page(qt_app, context) -> None:
    from app.ui.pages.files import FilesPage
    from app.ui.pages.scanner import ScannerPage
    from app.ui.pages.search import SearchPage
    from app.ui.pages.settings import SettingsPage

    expected = {
        ScannerPage: "Start scan",
        FilesPage: "Analyse",
        SearchPage: "Search",
        SettingsPage: "Save settings",
    }
    for factory, label in expected.items():
        page = factory(context)
        try:
            primaries = [
                button
                for button in page.findChildren(QtWidgets.QPushButton)
                if button.property("primary") is True
            ]
            assert len(primaries) == 1, factory.__name__
            assert primaries[0].text() == label, factory.__name__
        finally:
            page.deleteLater()


def test_scanner_primary_follows_library_state(qt_app, context, analysed_library) -> None:
    from app.ui.pages.scanner import ScannerPage

    page = ScannerPage(context)
    try:
        report = type("Report", (), {"summary": lambda self: "Scan finished."})()
        page._scan_done(report)
        primaries = [
            button.text()
            for button in page.findChildren(QtWidgets.QPushButton)
            if button.property("primary") is True
        ]
        assert primaries == ["Analyse pending files"]
    finally:
        page.deleteLater()


def test_page_spacing_uses_scrollable_defaults() -> None:
    settings = Path("app/ui/pages/settings.py").read_text(encoding="utf-8")
    planner = Path("app/ui/pages/planner.py").read_text(encoding="utf-8")

    assert "scrollable_page(self, spacing=14)" not in settings
    assert "margin=(24, 20, 24, 24)" not in planner


def test_empty_states_name_next_action(qt_app, context) -> None:
    from app.ui.pages.files import FilesPage
    from app.ui.pages.history import HistoryPage
    from app.ui.pages.planner import PlannerPage
    from app.ui.pages.recommendations import RecommendationsPage
    from app.ui.pages.search import SearchPage

    for factory in (FilesPage, SearchPage, HistoryPage, PlannerPage, RecommendationsPage):
        page = factory(context)
        try:
            labels = page.empty_state.findChildren(QtWidgets.QLabel)
            assert len(labels) >= 2, factory.__name__
            assert labels[0].text().strip(), factory.__name__
            assert re.search(r"\b(Open|Scan|Run|Try|Review|Select)\b", labels[1].text()), (
                factory.__name__,
                labels[1].text(),
            )
        finally:
            page.deleteLater()


def test_busy_controls_disabled_while_task_runs(qt_app, context) -> None:
    from app.ui.pages.history import HistoryPage
    from app.ui.pages.planner import PlannerPage

    planner = PlannerPage(context)
    history = HistoryPage(context)
    try:
        for page, button in (
            (planner, planner.rebuild_button),
            (history, history.rebuild_index_button),
        ):
            assert button.isEnabled() is True
            page._set_busy(True)
            assert button.isEnabled() is False
            page._set_busy(False)
            assert button.isEnabled() is True
    finally:
        planner.deleteLater()
        history.deleteLater()


def test_busy_controls_disabled_by_running_task(qt_app, context) -> None:
    from app.ui.pages.planner import PlannerPage

    page = PlannerPage(context)
    try:
        running = object()
        page._tasks.add(running)
        page._set_busy(False)
        assert page.rebuild_button.isEnabled() is False

        page._tasks.discard(running)
        page._set_busy(False)
        assert page.rebuild_button.isEnabled() is True
    finally:
        page.deleteLater()


def test_search_empty_state_hidden_before_first_query(qt_app, context) -> None:
    from app.ui.pages.search import SearchPage

    page = SearchPage(context)
    try:
        assert page.empty_state.isHidden() is True
    finally:
        page.deleteLater()


def test_empty_state_shown_when_load_fails(qt_app, context, monkeypatch) -> None:
    from app.ui.pages.files import FilesPage
    from app.ui.pages.history import HistoryPage
    from app.ui.pages.recommendations import RecommendationsPage

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("offline")

    monkeypatch.setattr(context.files, "list_summaries", boom)
    monkeypatch.setattr(context.recovery, "history", boom)
    monkeypatch.setattr(context.recommendations, "pending", boom)

    for factory in (FilesPage, HistoryPage, RecommendationsPage):
        page = factory(context)
        try:
            assert page.empty_state.isHidden() is False, factory.__name__
        finally:
            page.deleteLater()


def test_history_busy_guard_covers_background_actions(qt_app, context, monkeypatch) -> None:
    from app.ui.pages.history import HistoryPage

    page = HistoryPage(context)
    calls: list[tuple[dict, object]] = []

    def fake_run_task(fn, **kwargs):  # type: ignore[no-untyped-def]
        running = object()
        page._tasks.add(running)
        calls.append((kwargs, running))
        return running

    monkeypatch.setattr(page, "run_task", fake_run_task)
    try:
        for trigger in (page._create_backup, page._rebuild_index):
            for outcome in ("on_done", "on_failed"):
                page._set_busy(False)
                assert page.rebuild_index_button.isEnabled() is True
                trigger()
                assert page.rebuild_index_button.isEnabled() is False
                kwargs, running = calls[-1]
                page._tasks.discard(running)
                kwargs[outcome](None if outcome == "on_done" else "boom")
                assert page.rebuild_index_button.isEnabled() is True
    finally:
        page.deleteLater()


def test_history_undo_guard_releases_after_each_outcome(qt_app, context, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages.history import HistoryPage
    from app.ui.widgets import set_cell

    page = HistoryPage(context)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: QMessageBox.StandardButton.Ok)
    calls: list[tuple[dict, object]] = []

    def fake_run_task(fn, **kwargs):  # type: ignore[no-untyped-def]
        running = object()
        page._tasks.add(running)
        calls.append((kwargs, running))
        return running

    monkeypatch.setattr(page, "run_task", fake_run_task)
    operation = type(
        "Operation",
        (),
        {
            "id": 1,
            "filename": "a.txt",
            "source_path": "src",
            "destination_path": "dst",
            "undoable": True,
        },
    )()
    try:
        for outcome in ("on_done", "on_failed", "on_cancelled"):
            page._set_busy(False)
            page._operations = {1: operation}
            page.operation_table.setRowCount(1)
            set_cell(page.operation_table, 0, 0, "1", data=1)
            page.operation_table.selectRow(0)

            page._undo_selected()
            assert page.rebuild_index_button.isEnabled() is False, outcome

            kwargs, running = calls[-1]
            page._tasks.discard(running)
            callback = kwargs[outcome]
            if outcome == "on_cancelled":
                callback()
            else:
                callback(object() if outcome == "on_done" else "boom")
            assert page.rebuild_index_button.isEnabled() is True, outcome
    finally:
        page.deleteLater()


def test_planner_busy_guard_covers_execution(qt_app, context, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages.planner import PlannerPage

    page = PlannerPage(context)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        context.organisation,
        "plan",
        lambda plan_id: {"root_path": "root", "status": "approved"},
    )
    summary = type("Summary", (), {"total": 0, "conflicts": 0})()
    monkeypatch.setattr(context.organisation, "summary", lambda plan_id: summary)
    calls: list[tuple[dict, object]] = []

    def fake_run_task(fn, **kwargs):  # type: ignore[no-untyped-def]
        running = object()
        page._tasks.add(running)
        calls.append((kwargs, running))
        return running

    monkeypatch.setattr(page, "run_task", fake_run_task)
    try:
        page._current_plan_id = 1
        page._execute_plan()
        assert page.rebuild_button.isEnabled() is False

        kwargs, running = calls[-1]
        page._tasks.discard(running)
        kwargs["on_done"](type("Report", (), {})())
        assert page.rebuild_button.isEnabled() is True
    finally:
        page.deleteLater()


def _ui_stamp():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def test_load_failure_clears_stale_rows_and_controls(qt_app, context, monkeypatch) -> None:
    from app.ui.pages.files import FilesPage
    from app.ui.pages.history import HistoryPage
    from app.ui.pages.recommendations import RecommendationsPage

    stamp = _ui_stamp()
    summary = type(
        "Summary",
        (),
        {
            "id": 1,
            "name": "a.txt",
            "path": "a.txt",
            "title": "A",
            "category": None,
            "status": "analysed",
            "size": 3,
            "modified_at": stamp,
            "tags": (),
        },
    )()
    operation = type(
        "Operation",
        (),
        {
            "id": 1,
            "filename": "a.txt",
            "operation_type": "rename",
            "status": "completed",
            "error_message": None,
            "undoable": True,
            "completed_at": stamp,
            "created_at": stamp,
        },
    )()
    suggestion = type(
        "Suggestion",
        (),
        {
            "file_id": 1,
            "filename": "a.txt",
            "suggested_value": "b.txt",
            "category": None,
            "confidence": 0.9,
            "status": "pending",
        },
    )()

    scenarios = (
        (FilesPage, context.files, "list_summaries", [summary], "table", "analyse_button"),
        (HistoryPage, context.recovery, "history", [operation], "operation_table", "undo_button"),
        (
            RecommendationsPage,
            context.recommendations,
            "pending",
            [suggestion],
            "suggestion_table",
            "accept_all_button",
        ),
    )
    for factory, service, method, rows, table_name, button_name in scenarios:
        page = factory(context)
        try:
            monkeypatch.setattr(service, method, lambda *a, _rows=rows, **k: _rows)
            page.refresh()
            table = getattr(page, table_name)
            button = getattr(page, button_name)
            if factory is HistoryPage:
                table.selectRow(0)
                page._selection_changed()
            assert table.rowCount() == 1, factory.__name__
            assert button.isEnabled() is True, factory.__name__

            def boom(*args, _method=method, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("offline")

            monkeypatch.setattr(service, method, boom)
            page.refresh()

            assert table.rowCount() == 0, factory.__name__
            assert button.isEnabled() is False, factory.__name__
            assert page.empty_state.isHidden() is False, factory.__name__
        finally:
            page.deleteLater()


def test_history_undo_disabled_while_backup_runs(qt_app, context, monkeypatch) -> None:
    from app.ui.pages.history import HistoryPage
    from app.ui.widgets import set_cell

    page = HistoryPage(context)
    calls: list[tuple[dict, object]] = []

    def fake_run_task(fn, **kwargs):  # type: ignore[no-untyped-def]
        running = object()
        page._tasks.add(running)
        calls.append((kwargs, running))
        return running

    monkeypatch.setattr(page, "run_task", fake_run_task)
    operation = type(
        "Operation",
        (),
        {
            "id": 1,
            "filename": "a.txt",
            "source_path": "src",
            "destination_path": "dst",
            "undoable": True,
        },
    )()
    try:
        page._operations = {1: operation}
        page.operation_table.setRowCount(1)
        set_cell(page.operation_table, 0, 0, "1", data=1)
        page.operation_table.selectRow(0)
        page._selection_changed()
        assert page.undo_button.isEnabled() is True

        page._create_backup()
        assert page.undo_button.isEnabled() is False

        kwargs, running = calls[-1]
        page._tasks.discard(running)
        kwargs["on_done"](object())
        assert page.undo_button.isEnabled() is True
    finally:
        page.deleteLater()


def test_planner_guards_plan_navigation_during_execution(qt_app, context, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from app.ui.pages.planner import PlannerPage

    page = PlannerPage(context)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        context.organisation,
        "plan",
        lambda plan_id: {"root_path": "root", "status": "approved"},
    )
    summary = type("Summary", (), {"total": 0, "conflicts": 0})()
    monkeypatch.setattr(context.organisation, "summary", lambda plan_id: summary)
    calls: list[tuple[dict, object]] = []

    def fake_run_task(fn, **kwargs):  # type: ignore[no-untyped-def]
        running = object()
        page._tasks.add(running)
        calls.append((kwargs, running))
        return running

    monkeypatch.setattr(page, "run_task", fake_run_task)
    try:
        page._current_plan_id = 1
        assert page.new_plan_button.isEnabled() is True
        page._execute_plan()
        assert page.new_plan_button.isEnabled() is False
        assert page.revalidate_button.isEnabled() is False

        kwargs, running = calls[-1]
        page._tasks.discard(running)
        kwargs["on_done"](type("Report", (), {})())
        assert page.new_plan_button.isEnabled() is True
        assert page.revalidate_button.isEnabled() is False
    finally:
        page.deleteLater()


def test_search_empty_state_hides_on_failure_and_cancel(qt_app, context) -> None:
    from app.ui.pages.search import SearchPage

    page = SearchPage(context)
    try:
        response = type("Response", (), {"hits": [], "took_ms": 1.0, "notes": [], "query": "x"})()
        page._search_done(response)
        assert page.empty_state.isHidden() is False

        page._search_failed("boom")
        assert page.empty_state.isHidden() is True

        page._search_done(response)
        page._search_cancelled()
        assert page.empty_state.isHidden() is True
    finally:
        page.deleteLater()


def test_recommendation_field_labels_use_field_role(qt_app, context) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    try:
        labels = [
            label
            for label in page.findChildren(QtWidgets.QLabel)
            if label.text() in {"Filename", "Folder", "Category"}
        ]
        assert labels
        assert all(label.property("role") == "field" for label in labels)
    finally:
        page.deleteLater()
