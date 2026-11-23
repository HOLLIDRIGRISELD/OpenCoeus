"""Visual and control-level regressions for the window chrome and pages."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_line_edit_shows_the_start_of_a_long_value(qt_app) -> None:
    from app.ui.widgets import LineEdit

    edit = LineEdit()
    edit.setText("C:/Users/somebody/very/long/path/that/does/not/fit/in/the/field")

    assert edit.cursorPosition() == 0


def test_dashboard_hides_the_start_hint_once_files_exist(qt_app, context, analysed_library) -> None:
    from app.ui.pages.dashboard import DashboardPage

    page = DashboardPage(context)
    try:
        page.refresh()

        assert page.empty_hint.isHidden()
    finally:
        page.deleteLater()


def test_dashboard_shows_the_start_hint_for_an_empty_library(qt_app, context) -> None:
    from app.ui.pages.dashboard import DashboardPage

    page = DashboardPage(context)
    try:
        page.refresh()

        assert not page.empty_hint.isHidden()
    finally:
        page.deleteLater()


def test_progress_bars_stay_thin(qt_app, context) -> None:
    from app.ui.pages.scanner import ScannerPage

    page = ScannerPage(context)
    try:
        assert page.scan_progress.maximumHeight() <= 10
        assert page.analyse_progress.maximumHeight() <= 10
    finally:
        page.deleteLater()


def test_finished_scan_and_analysis_can_rerun(qt_app, context, tmp_path, monkeypatch) -> None:
    from app.ui.pages.scanner import ScannerPage

    page = ScannerPage(context)
    labels: list[str] = []

    def fake_run_task(_fn, **kwargs):
        labels.append(kwargs["label"])
        task = type("Task", (), {"cancelled": False})()
        page._tasks.add(task)
        return task

    monkeypatch.setattr(page, "run_task", fake_run_task)
    try:
        finished = type("Task", (), {"cancelled": False})()
        page._scan_task = finished
        page._analyse_task = finished
        page.path_edit.setText(str(tmp_path))

        page.start_scan()
        page.start_analysis()

        assert labels == ["Scan", "Analysis"]

        labels.clear()
        page.start_scan()
        page.start_analysis()

        assert labels == []
    finally:
        page.deleteLater()


def test_review_category_field_does_not_force_a_wide_panel(qt_app, context) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    try:
        page.category_combo.addItem("Technical/Documentation/Some Very Long Category Name")

        assert page.category_combo.minimumSizeHint().width() < 260
    finally:
        page.deleteLater()
