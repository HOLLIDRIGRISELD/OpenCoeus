"""Responsive-layout regression tests for the desktop shell.

These run with Qt's offscreen platform. They verify that the shell and its pages
derive their geometry from the current window size instead of fixed pixels.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtGui = pytest.importorskip("PySide6.QtGui")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from app.services.context import AppContext  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.widgets import make_table  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_shell_scales_and_drops_secondary_details(qt_app, context: AppContext) -> None:
    window = MainWindow(context)
    try:
        window.show()

        window.resize(760, 520)
        qt_app.processEvents()
        assert 176 <= window.sidebar.width() <= 260
        assert not window.tagline_label.isVisible()
        assert window.header.minimumHeight() >= 64

        window.resize(1920, 1080)
        qt_app.processEvents()
        assert window.sidebar.width() == 260
        assert window.tagline_label.isVisible()
        assert window.header.minimumHeight() >= 92
    finally:
        window.close()


def test_shell_drops_corner_status_widgets(qt_app, context: AppContext) -> None:
    window = MainWindow(context)
    try:
        window.show()
        texts = {label.text() for label in window.findChildren(QtWidgets.QLabel)}

        assert not any(str(context.config.data_dir) in text for text in texts)
        assert not any(text.startswith("Root:") for text in texts)
        assert not any(text.startswith("Version ") for text in texts)
        assert "Local processing" not in texts
        assert "● Local only" not in texts
    finally:
        window.close()


def test_dashboard_stat_cards_wrap_by_width(qt_app, context: AppContext) -> None:
    window = MainWindow(context)
    try:
        window.show()
        window.navigate("dashboard")
        dashboard = window.pages["dashboard"]

        window.resize(760, 520)
        qt_app.processEvents()
        assert dashboard._stat_columns == 2

        window.resize(1366, 768)
        qt_app.processEvents()
        assert dashboard._stat_columns == 3

        window.resize(1920, 1080)
        qt_app.processEvents()
        assert dashboard._stat_columns == 6
    finally:
        window.close()


def test_settings_grid_collapses_to_one_column(qt_app, context: AppContext) -> None:
    window = MainWindow(context)
    try:
        window.show()
        window.navigate("settings")
        settings = window.pages["settings"]

        window.resize(1024, 600)
        qt_app.processEvents()
        assert settings._settings_columns == 1

        window.resize(1920, 1080)
        qt_app.processEvents()
        assert settings._settings_columns == 2
    finally:
        window.close()


def test_scroll_pages_fit_the_viewport(qt_app, context: AppContext) -> None:
    """Scrollable pages must never push their content sideways off-screen."""

    window = MainWindow(context)
    try:
        window.show()
        window.resize(1024, 600)
        qt_app.processEvents()
        for key in (
            "dashboard",
            "scanner",
            "files",
            "recommendations",
            "search",
            "history",
            "settings",
        ):
            window.navigate(key)
            qt_app.processEvents()
            page = window.pages[key]
            scroll = page.findChild(QtWidgets.QScrollArea)
            assert scroll is not None, key
            assert scroll.widget() is not None
            assert scroll.widget().width() <= page.width() + 2
    finally:
        window.close()


def test_dashboard_cards_keep_full_height(qt_app, context: AppContext) -> None:
    """A short window must scroll the dashboard, not squash its stat cards."""

    window = MainWindow(context)
    try:
        window.show()
        window.navigate("dashboard")
        window.resize(1024, 600)
        qt_app.processEvents()
        dashboard = window.pages["dashboard"]
        for card in dashboard._stat_cards:
            assert card.height() >= card.minimumSizeHint().height() - 2
    finally:
        window.close()


def test_tables_fit_their_viewport(qt_app, context: AppContext) -> None:
    """Adaptive columns must avoid horizontal scrollbars at small widths."""

    window = MainWindow(context)
    try:
        window.show()
        window.resize(1024, 600)
        qt_app.processEvents()
        for key in window.pages:
            window.navigate(key)
            qt_app.processEvents()
            for table in window.pages[key].findChildren(QtWidgets.QTableWidget):
                total = sum(table.columnWidth(i) for i in range(table.columnCount()))
                assert total <= table.viewport().width() + 2
    finally:
        window.close()


def test_adaptive_table_caps_columns_in_a_narrow_host(qt_app) -> None:
    """Content-sized columns must shrink rather than forcing a scrollbar."""

    host = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    table = make_table(
        ["Original file", "Proposed name", "Category", "Confidence", "Status"],
        stretch=1,
    )
    layout.addWidget(table)
    try:
        host.resize(320, 200)
        host.show()
        qt_app.processEvents()
        total = sum(table.columnWidth(i) for i in range(table.columnCount()))
        assert total <= table.viewport().width() + 2
    finally:
        host.close()


def test_pages_fit_with_enlarged_font(qt_app, context: AppContext) -> None:
    """Larger glyph metrics must not reintroduce clipping or overflow."""

    original = qt_app.font()
    enlarged = QtGui.QFont(original)
    enlarged.setPointSize(original.pointSize() + 3)
    qt_app.setFont(enlarged)
    window = None
    try:
        window = MainWindow(context)
        window.show()
        window.resize(1024, 600)
        qt_app.processEvents()
        for key in ("scanner", "history", "files", "settings", "recommendations"):
            window.navigate(key)
            qt_app.processEvents()
            page = window.pages[key]
            for table in page.findChildren(QtWidgets.QTableWidget):
                total = sum(table.columnWidth(i) for i in range(table.columnCount()))
                assert total <= table.viewport().width() + 2, key
    finally:
        if window is not None:
            window.close()
        qt_app.setFont(original)
