from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from opencoeus.config import ScanSettings
from opencoeus.db import AuditStore
from opencoeus.engine.scanner import ScanEngine


class _ScanWorker(QThread):
    message = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, folder: Path, patterns: list[str], profile_id: int,
                 store: AuditStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._folder = folder
        self._patterns = patterns
        self._profile_id = profile_id
        self._store = store

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            self.message.emit("Scanning folder structure...")
            settings = ScanSettings(self._folder, extract_documents=True)
            engine = ScanEngine(settings, self._store)
            result = engine.run_phase_one(
                progress_callback=lambda m: self.message.emit(str(m)),
                custom_patterns=self._patterns or None,
                profile_id=self._profile_id,
            )
            if self.isInterruptionRequested():
                return
            self.completed.emit(result)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.failed.emit(str(e))


class _OrganizeWorker(QThread):
    message = pyqtSignal(str)
    completed = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, folder: Path, excluded: set[str], patterns: list[str],
                 profile_id: int, rules: list[dict],
                 store: AuditStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._folder = folder
        self._excluded = excluded
        self._patterns = patterns
        self._profile_id = profile_id
        self._rules = rules
        self._store = store

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            from opencoeus.profiles import ProfileConfig, load_profile
            profile = load_profile(self._store, self._profile_id) or ProfileConfig(name="default")
            excluded = self._excluded | set(profile.excluded_folders)
            included = profile.included_folders or None
            extract = profile.document_extraction
            settings = ScanSettings(self._folder, extract_documents=extract)
            engine = ScanEngine(settings, self._store)
            result = engine.run_phase_two(
                excluded_folders=excluded,
                included_folders=included,
                progress_callback=lambda m: self.message.emit(str(m)),
                extract_documents=extract,
            )
            if self.isInterruptionRequested():
                return
            from opencoeus.rules.engine import RulesEngine
            from opencoeus.llm import build_llm_engine
            llm_engine = build_llm_engine(profile)
            r_engine = RulesEngine(profile, scan_root=self._folder.as_posix(), llm_engine=llm_engine)
            matches = r_engine.evaluate(result.rows, self._rules)
            if self.isInterruptionRequested():
                return
            self.completed.emit(result, matches)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.failed.emit(str(e))


class ScanController(QObject):
    log_message = pyqtSignal(str)
    scan_done = pyqtSignal(object)
    organize_done = pyqtSignal(object, object)
    scan_failed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, store: AuditStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._worker: QThread | None = None

    def _profile_id(self) -> int:
        profiles = self._store.list_profiles()
        if profiles:
            return profiles[0].id
        from opencoeus.profiles import create_profile
        p = create_profile(self._store, "default")
        return p.profile_id

    @staticmethod
    def _wire_worker_signals(worker: QThread) -> None:
        worker.message.connect(worker.parent().log_message)
        worker.failed.connect(lambda e: worker.parent().scan_failed.emit(e))
        worker.failed.connect(lambda: worker.parent().busy_changed.emit(False))
        worker.failed.connect(worker.parent()._on_worker_done)
        worker.finished.connect(worker.deleteLater)

    def discover_and_scan(self, folder: Path, patterns: list[str] | None = None) -> None:
        self._cancel()
        self.busy_changed.emit(True)
        pid = self._profile_id()
        worker = _ScanWorker(folder, patterns or [], pid, self._store, self)
        worker.completed.connect(lambda r: self.scan_done.emit(r))
        worker.completed.connect(lambda: self.busy_changed.emit(False))
        worker.completed.connect(self._on_worker_done)
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def organize(self, folder: Path, excluded: set[str], patterns: list[str],
                 rules: list[dict]) -> None:
        self._cancel()
        self.busy_changed.emit(True)
        pid = self._profile_id()
        worker = _OrganizeWorker(folder, excluded, patterns, pid, rules, self._store, self)
        worker.completed.connect(lambda r, m: self.organize_done.emit(r, m))
        worker.completed.connect(lambda: self.busy_changed.emit(False))
        worker.completed.connect(self._on_worker_done)
        self._wire_worker_signals(worker)
        self._worker = worker
        worker.start()

    def _on_worker_done(self, *args) -> None:
        worker = self.sender()
        if worker is not None and self._worker is worker:
            self._worker = None

    def cancel(self) -> None:
        self._cancel()

    def _cancel(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.quit()
            if not worker.wait(3000):
                worker.finished.connect(worker.deleteLater)
