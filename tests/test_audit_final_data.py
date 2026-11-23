"""Task 1 regressions for GUI restore safety and backup naming."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import recovery_service
from app.services.recovery_service import RecoveryService
from app.ui.main_window import MainWindow
from app.ui.pages.history import HistoryPage


def test_main_window_stop_for_restore_cancels_tasks_and_disables_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    window = SimpleNamespace(
        cancel_tasks=lambda: events.append("cancel"),
        setEnabled=lambda enabled: events.append(("enabled", enabled)),
    )

    class FakePool:
        def waitForDone(self) -> None:
            events.append("drain")

    monkeypatch.setattr(
        "app.ui.main_window.QThreadPool",
        SimpleNamespace(globalInstance=lambda: FakePool()),
    )

    MainWindow.stop_for_restore(window)  # type: ignore[arg-type]

    assert events == ["cancel", "drain", ("enabled", False)]


def _restore_fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, fails: bool):
    from app.ui.pages import history as history_module

    backup = tmp_path / "backup.db"
    backup.write_bytes(b"backup")
    events: list[object] = []
    restored: list[Path] = []

    window = SimpleNamespace(
        stop_for_restore=lambda: events.append("stop"),
        close=lambda: events.append("close"),
        setEnabled=lambda enabled: events.append(("enabled", enabled)),
    )

    class Button:
        def __or__(self, _other: object) -> Button:
            return self

    class FakeMessageBox:
        class StandardButton:
            Yes = Button()
            Cancel = Button()

        @staticmethod
        def warning(*_args: object) -> Button:
            return FakeMessageBox.StandardButton.Yes

        @staticmethod
        def information(*_args: object) -> None:
            events.append("info")

        @staticmethod
        def critical(*_args: object) -> None:
            events.append("critical")

    class FakeMessage:
        def emit(self, text: str) -> None:
            events.append(("message", text))

    def restore(path: Path) -> None:
        if fails:
            raise RuntimeError("restore failed")
        restored.append(path)

    fake_self = SimpleNamespace(
        ctx=SimpleNamespace(recovery=SimpleNamespace(restore=restore)),
        backup_table=object(),
        message=FakeMessage(),
        window=lambda: window,
        _set_busy=lambda busy: events.append(("busy", busy)),
    )

    def run_task(fn, *, label: str, on_done, on_failed):  # type: ignore[no-untyped-def]
        events.append(("task", label))
        assert "stop" in events
        try:
            result = fn(lambda *_args: None, None)
        except Exception as exc:
            on_failed(str(exc))
        else:
            on_done(result)
        return object()

    fake_self.run_task = run_task
    monkeypatch.setattr(history_module, "selected_data", lambda _table: str(backup))
    monkeypatch.setattr(history_module, "QMessageBox", FakeMessageBox)
    return fake_self, events, restored


def test_restore_cancels_tasks_and_closes_window_after_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_self, events, restored = _restore_fake(monkeypatch, tmp_path, fails=False)

    HistoryPage._restore_backup(fake_self)  # type: ignore[arg-type]

    assert restored == [tmp_path / "backup.db"]
    assert events == [
        "stop",
        ("busy", True),
        ("task", "Restore"),
        ("busy", False),
        "info",
        ("message", "Database restored; restart OpenCoeus to continue."),
        "close",
    ]


def test_restore_failure_restores_window_controls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_self, events, restored = _restore_fake(monkeypatch, tmp_path, fails=True)

    HistoryPage._restore_backup(fake_self)  # type: ignore[arg-type]

    assert restored == []
    assert ("enabled", True) in events
    assert "critical" in events


def test_default_backup_names_do_not_collide_within_one_second(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Clock(datetime):
        times = iter(
            (datetime(2026, 1, 1, 0, 0, 0, 111111), datetime(2026, 1, 1, 0, 0, 0, 222222))
        )

        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return next(cls.times)

    class FakeDatabase:
        def __init__(self) -> None:
            self.paths: list[Path] = []

        def backup(self, destination: Path) -> Path:
            self.paths.append(destination)
            return destination

    monkeypatch.setattr(recovery_service, "datetime", Clock)
    db = FakeDatabase()
    service = RecoveryService(
        SimpleNamespace(backup_dir=tmp_path), db, None, None, None  # type: ignore[arg-type]
    )

    first = service.backup()
    second = service.backup()

    assert first != second
    assert first.name.startswith("opencoeus-")
    assert db.paths == [first, second]
