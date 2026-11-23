"""UI refresh policies must avoid redundant work without changing pinned behavior."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from app.services.context import AppContext
from app.ui.main_window import MainWindow
from app.ui.pages.files import FilesPage
from app.ui.pages.planner import PlannerPage
from app.ui.pages.recommendations import RecommendationsPage


@pytest.fixture()
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_same_page_navigate_does_not_refresh_twice(
    qt_app: QApplication, context: AppContext, monkeypatch
) -> None:
    window = MainWindow(context)
    try:
        calls: list[str] = []
        monkeypatch.setattr(window.pages["dashboard"], "refresh", lambda: calls.append("dashboard"))

        window.navigate("dashboard")

        assert calls == []
    finally:
        window.close()


def test_library_change_marks_pages_dirty_instead_of_refreshing_all(
    qt_app: QApplication, context: AppContext, monkeypatch
) -> None:
    window = MainWindow(context)
    try:
        calls: dict[str, int] = {key: 0 for key in window.pages}
        for key, page in window.pages.items():
            monkeypatch.setattr(page, "refresh", lambda key=key: calls.__setitem__(key, calls[key] + 1))

        window._library_changed()

        assert calls["dashboard"] == 1
        assert calls["files"] == 0
        assert calls["recommendations"] == 0

        window.navigate("files")

        assert calls["files"] == 1
    finally:
        window.close()


def test_duplicates_tab_loads_only_when_selected(
    qt_app: QApplication, context: AppContext, monkeypatch
) -> None:
    page = RecommendationsPage(context)
    try:
        calls: list[int] = []
        monkeypatch.setattr(context, "duplicates", lambda: calls.append(1) or [])

        page.refresh()

        assert calls == []

        page.tabs.setCurrentIndex(1)
        assert len(calls) == 1

        page.tabs.setCurrentIndex(0)
        page.tabs.setCurrentIndex(1)
        assert len(calls) == 1
    finally:
        page.deleteLater()


def test_plan_summary_reuses_loaded_items(
    qt_app: QApplication, context: AppContext, monkeypatch
) -> None:
    page = PlannerPage(context)
    try:
        items: list[object] = []
        summary_args: list[tuple[int, object]] = []
        monkeypatch.setattr(
            context.organisation,
            "plan",
            lambda _plan_id: {"status": "draft", "root_path": "/tmp/library"},
        )
        monkeypatch.setattr(context.organisation, "items", lambda _plan_id: items)
        monkeypatch.setattr(
            context.organisation,
            "summary",
            lambda plan_id, loaded=None: summary_args.append((plan_id, loaded))
            or SimpleNamespace(conflicts=0),
        )

        page._load_plan(7)

        assert summary_args == [(7, items)]
    finally:
        page.deleteLater()


def test_unchanged_selection_skips_detail_reload(
    qt_app: QApplication, context: AppContext, monkeypatch
) -> None:
    page = FilesPage(context)
    try:
        calls: list[int] = []
        monkeypatch.setattr(page, "_show_detail", lambda _file_id: calls.append(_file_id))

        page.table.insertRow(0)
        item = QTableWidgetItem("doc.txt")
        item.setData(Qt.ItemDataRole.UserRole, 42)
        page.table.setItem(0, 0, item)
        page.table.selectRow(0)
        assert calls == [42]

        page._selection_changed()
        page._selection_changed()

        assert calls == [42]
    finally:
        page.deleteLater()
