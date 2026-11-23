"""Headless smoke test for the desktop shell.

The test uses Qt's offscreen platform, so it runs on a machine without a
display. It only checks that the window and all pages can be constructed and
navigated; behavioural coverage lives in the service tests.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from app.services.context import AppContext  # noqa: E402
from app.ui.main_window import NAVIGATION, MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_main_window_constructs_and_navigates_all_pages(qt_app, context: AppContext) -> None:
    window = MainWindow(context)
    try:
        assert set(window.pages) == {key for key, *_ in NAVIGATION}
        assert len(window.pages) == 8
        assert window.stack.count() == 8
        assert "rules" not in window.pages

        for key, *_ in NAVIGATION:
            window.navigate(key)
            assert window.stack.currentWidget() is window.pages[key]

        window.navigate("dashboard")
        assert window._current_key == "dashboard"
        assert window.statusBar() is not None
    finally:
        window.close()
