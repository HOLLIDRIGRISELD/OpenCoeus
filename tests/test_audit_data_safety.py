"""Focused regressions for audit findings 6 (GUI maintenance work off the GUI thread)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from app.services.recovery_service import BackupInfo  # noqa: E402
from app.ui.pages import history as history_module  # noqa: E402
from app.ui.widgets import set_cell  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _page(qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events: list[tuple[object, ...]] = []

    class FakeRecovery:
        def history(self, *, limit: int = 200, status: str | None = None):
            return []

        def list_backups(self):
            return [BackupInfo(tmp_path / "backup.db", 10, datetime.now())]

        def restore(self, backup: Path) -> None:
            events.append(("restore", backup))

        def integrity_check(self) -> bool:
            events.append(("integrity",))
            return True

        def vacuum(self) -> None:
            events.append(("vacuum",))

    class FakeConfig:
        backup_dir = tmp_path / "backups"

    class FakeContext:
        recovery = FakeRecovery()
        config = FakeConfig()

    page = history_module.HistoryPage(FakeContext())
    tasks: list[tuple[object, dict[str, object]]] = []

    def fake_run_task(fn, **kwargs):
        tasks.append((fn, kwargs))
        return object()

    monkeypatch.setattr(page, "run_task", fake_run_task)
    monkeypatch.setattr(
        history_module.QMessageBox,
        "warning",
        lambda *_args, **_kwargs: history_module.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        history_module.QMessageBox,
        "information",
        lambda *_args, **_kwargs: history_module.QMessageBox.StandardButton.Ok,
    )
    set_cell(page.backup_table, 0, 0, "backup.db", data=str(tmp_path / "backup.db"))
    page.backup_table.selectRow(0)
    return page, events, tasks


def test_restore_runs_on_worker_and_reports_back_on_gui_thread(
    qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, events, tasks = _page(qt_app, tmp_path, monkeypatch)
    messages: list[str] = []
    page.message.connect(messages.append)
    try:
        page._restore_backup()

        assert len(tasks) == 1
        assert events == []
        assert not page.restore_button.isEnabled()

        work, callbacks = tasks[0]
        work(None, None)  # type: ignore[operator]
        assert events == [("restore", tmp_path / "backup.db")]

        callbacks["on_done"](None)  # type: ignore[operator]
        assert page.restore_button.isEnabled()
        assert any("Database restored" in message for message in messages)
    finally:
        page.deleteLater()


def test_integrity_check_runs_on_worker_and_reports_back_on_gui_thread(
    qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, events, tasks = _page(qt_app, tmp_path, monkeypatch)
    try:
        page._integrity_check()

        assert len(tasks) == 1
        assert events == []

        work, callbacks = tasks[0]
        work(None, None)  # type: ignore[operator]
        assert events == [("integrity",)]

        callbacks["on_done"](True)  # type: ignore[operator]
        assert "passed" in page.maintenance_output.text()
        assert page.integrity_button.isEnabled()
    finally:
        page.deleteLater()


def test_vacuum_runs_on_worker_and_reports_back_on_gui_thread(
    qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, events, tasks = _page(qt_app, tmp_path, monkeypatch)
    try:
        page._vacuum()

        assert len(tasks) == 1
        assert events == []

        work, callbacks = tasks[0]
        work(None, None)  # type: ignore[operator]
        assert events == [("vacuum",)]

        callbacks["on_done"](None)  # type: ignore[operator]
        assert "compacted" in page.maintenance_output.text()
        assert page.vacuum_button.isEnabled()
    finally:
        page.deleteLater()
