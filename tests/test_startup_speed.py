"""Startup must not block the Qt event loop on local model runtime startup."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QTimer

from app.core.config import AppConfig
from app.infrastructure.models import BatchExecution
from app.services.context import AppContext
from app.ui import app as app_module


def test_runtime_start_is_deferred_until_event_loop(monkeypatch) -> None:
    events: list[str] = []
    scheduled: list[tuple[int, object]] = []
    create_kwargs: dict[str, object] = {}

    class FakeQApplication:
        @staticmethod
        def setHighDpiScaleFactorRoundingPolicy(*_args) -> None:
            return None

        def __init__(self, _argv) -> None:
            return None

        def setApplicationName(self, _value) -> None:
            return None

        def setApplicationDisplayName(self, _value) -> None:
            return None

        def setApplicationVersion(self, _value) -> None:
            return None

        def setOrganizationName(self, _value) -> None:
            return None

        def setStyle(self, _value) -> None:
            return None

        def setStyleSheet(self, _value) -> None:
            return None

        def exec(self) -> int:
            events.append("exec")
            assert "start" not in events
            if scheduled:
                scheduled[0][1]()
            return 0

    class FakeRuntime:
        def __init__(self, _base_url) -> None:
            return None

        def start(self) -> None:
            events.append("start")

        def stop(self) -> None:
            events.append("stop")

    class FakeWindow:
        def __init__(self, _context) -> None:
            return None

        def show(self) -> None:
            events.append("show")

    class FakeSettings:
        llm_base_url = "http://127.0.0.1:11434"
        enable_llm = True

    class FakeContext:
        settings = FakeSettings()

        @staticmethod
        def create(**kwargs):
            create_kwargs.update(kwargs)
            return FakeContext()

        def close(self) -> None:
            events.append("close")

    class FakeThread:
        def __init__(self, *, target, daemon=False) -> None:
            events.append("thread_create")
            self.ident = None

        def start(self) -> None:
            events.append("thread_start")
            self.ident = 1

        def join(self, timeout=None) -> None:
            return None

    def fake_single_shot(delay, callback) -> None:
        scheduled.append((delay, callback))

    monkeypatch.setattr(app_module, "QApplication", FakeQApplication)
    monkeypatch.setattr(app_module, "AppContext", FakeContext)
    monkeypatch.setattr(app_module, "MainWindow", FakeWindow)
    monkeypatch.setattr(app_module, "LocalRuntime", FakeRuntime)
    monkeypatch.setattr(app_module, "threading", SimpleNamespace(Thread=FakeThread))
    monkeypatch.setattr(QTimer, "singleShot", fake_single_shot)

    assert app_module.run([]) == 0
    assert create_kwargs == {"purge": False}
    assert events == ["show", "thread_create", "exec", "thread_start", "stop", "close"]
    assert "start" not in events
    assert len(scheduled) == 1
    assert scheduled[0][0] == 0


def test_startup_keeps_session_while_staged_batch_is_unfinished(config: AppConfig) -> None:
    first = AppContext(config, purge=False)
    try:
        root = config.data_dir.parent / "stage-library"
        source = root / "a.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("invoice totals invoice totals", encoding="utf-8")
        first.scanning.scan(root)
        first.analysis.analyse_pending(use_llm=False)
        file_id = first.files.find_by_path(source)
        assert file_id is not None
        plan_id = first.organisation.create_plan()
        batch_id = first.batches.create(plan_id, config.data_dir / "holding")
        holding = config.data_dir / "holding" / f"batch-{batch_id}" / "a.txt"
        first.batches.record_item(batch_id, file_id, source, holding, root / "Finance" / "a.txt")
    finally:
        first.close()

    second = AppContext(config, purge=True)
    try:
        assert second.files.find_by_path(source) is not None
        with second.db.session() as session:
            assert session.query(BatchExecution).count() == 1
    finally:
        second.close()
