"""Accessibility and interaction regressions for the desktop UI."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")


def _contrast(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]

        def linear(channel: float) -> float:
            return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

        red, green, blue = (linear(channel) for channel in channels)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_stylesheet_has_no_focus_outline() -> None:
    from app.ui.theme import STYLESHEET

    assert "outline: none" in STYLESHEET
    assert "outline:" not in STYLESHEET.replace("outline: none", "")
    for selector in (
        "QPushButton:focus",
        'QPushButton[nav="true"]:focus',
        "QCheckBox:focus",
        "QTableWidget:focus",
        "QTabBar::tab:focus",
    ):
        assert selector not in STYLESHEET


def test_secondary_text_and_control_boundaries_meet_contrast() -> None:
    from app.ui.theme import (
        ACCENT_DARK,
        ACCENT_SOFT,
        BORDER_STRONG,
        FAINT,
        SCROLL_HOVER,
        SLATE_850,
        SLATE_900,
        SLATE_950,
    )

    for background in (SLATE_850, SLATE_900, SLATE_950):
        assert _contrast(FAINT, background) >= 4.5
    assert _contrast(ACCENT_SOFT, ACCENT_DARK) >= 4.5
    assert _contrast(BORDER_STRONG, SLATE_850) >= 3.0
    assert _contrast(BORDER_STRONG, SLATE_950) >= 3.0
    assert _contrast(SCROLL_HOVER, SLATE_950) >= _contrast(BORDER_STRONG, SLATE_950)


def test_status_messages_remain_until_replaced(qt_app, context, monkeypatch) -> None:
    from app.ui.main_window import MainWindow

    window = MainWindow(context)
    try:
        calls: list[tuple[str, int]] = []
        monkeypatch.setattr(
            window.statusBar(),
            "showMessage",
            lambda message, timeout=0: calls.append((message, timeout)),
        )
        window._show_message("Analysis failed: disk full")

        assert calls[-1] == ("Analysis failed: disk full", 0)
    finally:
        window.close()


def test_navigation_advertises_keyboard_shortcuts(qt_app, context) -> None:
    from PySide6.QtGui import QKeySequence, QShortcut

    from app.ui.main_window import MainWindow

    window = MainWindow(context)
    try:
        assert "Ctrl+1" in window.nav_buttons["dashboard"].toolTip()
        assert "Ctrl+8" in window.nav_buttons["settings"].toolTip()
        assert QKeySequence("Ctrl+9") not in {
            shortcut.key() for shortcut in window.findChildren(QShortcut)
        }
    finally:
        window.close()


def test_planner_scrolls_and_can_cancel_execution(qt_app, context) -> None:
    from PySide6.QtWidgets import QScrollArea

    from app.ui.pages.planner import PlannerPage

    page = PlannerPage(context)
    try:
        assert page.findChild(QScrollArea) is not None
        assert page.cancel_button.text() == "Cancel"
    finally:
        page.deleteLater()


def test_search_can_cancel_an_in_flight_query(qt_app, context) -> None:
    from app.ui.pages.search import SearchPage

    page = SearchPage(context)
    try:
        assert page.cancel_button.text() == "Cancel"
        assert not page.cancel_button.isEnabled()
    finally:
        page.deleteLater()


def test_recommendation_status_is_human_readable(qt_app, context, analysed_library) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    try:
        page.refresh()
        statuses = [
            page.suggestion_table.item(row, 4).text()
            for row in range(page.suggestion_table.rowCount())
        ]
        assert statuses
        assert all("_" not in status for status in statuses)
    finally:
        page.deleteLater()


def test_category_change_keeps_a_manually_edited_folder(qt_app, context) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    try:
        page.folder_edit.setText("Archive/2026")
        page._category_changed("Finance/Invoices")

        assert page.folder_edit.text() == "Archive/2026"
    finally:
        page.deleteLater()


def test_accept_button_states_that_edits_are_saved(qt_app, context) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    try:
        assert "save" in page.accept_button.text().lower()
    finally:
        page.deleteLater()


def test_failed_detail_lookup_is_reported(qt_app, context, analysed_library, monkeypatch) -> None:
    from app.ui.pages.files import FilesPage

    def fail(*_args, **_kwargs):
        raise RuntimeError("detail store unavailable")

    monkeypatch.setattr(context.recommendations, "detail", fail)
    page = FilesPage(context)
    messages: list[str] = []
    page.message.connect(messages.append)
    try:
        file_id = next(iter(page._summaries))
        page._show_detail(file_id)

        assert messages
    finally:
        page.deleteLater()


def test_failed_recommendation_detail_clears_the_form(
    qt_app, context, analysed_library, monkeypatch
) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    def boom(*_args, **_kwargs):
        raise RuntimeError("detail store unavailable")

    page = RecommendationsPage(context)
    try:
        file_id = next(iter(page._suggestions))
        page._load_detail(file_id)
        assert page._detail is not None

        monkeypatch.setattr(context.recommendations, "detail", boom)
        page._load_detail(file_id)

        assert page._detail is None
        assert page.filename_edit.text() == ""
        assert not page.save_button.isEnabled()
        assert not page.accept_button.isEnabled()
    finally:
        page.deleteLater()


def test_mismatched_detail_is_not_applied_to_another_file(
    qt_app, context, analysed_library, monkeypatch
) -> None:
    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    writes: list[tuple[str, int]] = []
    ok = type("Result", (), {"ok": True})()
    monkeypatch.setattr(
        context.recommendations,
        "set_filename",
        lambda file_id, value: (writes.append(("filename", file_id)), ok)[1],
    )
    monkeypatch.setattr(
        context.recommendations,
        "set_category",
        lambda file_id, value: (writes.append(("category", file_id)), ok)[1],
    )
    monkeypatch.setattr(
        context.recommendations,
        "set_folder",
        lambda file_id, value: (writes.append(("folder", file_id)), ok)[1],
    )
    try:
        file_id = next(iter(page._suggestions))
        page._load_detail(file_id)
        page._current_id = -1
        page.filename_edit.setText("stale-edit.txt")

        assert page._apply_edits() is False
        assert writes == []
    finally:
        page.deleteLater()


def test_library_refresh_keeps_the_selected_file(qt_app, context, analysed_library) -> None:
    from PySide6.QtCore import Qt

    from app.ui.pages.files import FilesPage

    page = FilesPage(context)
    try:
        ids = [
            page.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(page.table.rowCount())
        ]
        assert len(ids) > 1
        page.table.selectRow(1)
        assert page._current_id == ids[1]

        page.refresh()

        assert page._current_id == ids[1]
    finally:
        page.deleteLater()


def test_review_refresh_keeps_the_selected_suggestion(qt_app, context, analysed_library) -> None:
    from PySide6.QtCore import Qt

    from app.ui.pages.recommendations import RecommendationsPage

    page = RecommendationsPage(context)
    try:
        ids = [
            page.suggestion_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(page.suggestion_table.rowCount())
        ]
        assert len(ids) > 1
        page.suggestion_table.selectRow(1)
        assert page._current_id == ids[1]

        page.refresh()

        assert page._current_id == ids[1]
    finally:
        page.deleteLater()


def test_empty_dashboard_explains_the_fresh_session(qt_app, context) -> None:
    from app.ui.pages.dashboard import DashboardPage

    page = DashboardPage(context)
    try:
        text = page.empty_hint.text().lower()
        assert "starts empty" in text or "fresh session" in text
    finally:
        page.deleteLater()
