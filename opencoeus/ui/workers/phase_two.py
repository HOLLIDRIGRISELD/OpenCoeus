from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from ...config import ScanSettings
from ...engine import ScanEngine
from ...profiles import ProfileConfig
from ...rules_engine import RulesEngine


class PhaseTwoWorker(QThread):
    message = pyqtSignal(str)
    finished_scan = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path, excluded_folders: set[str],
                 rules: list[dict], profile: ProfileConfig) -> None:
        super().__init__()
        self.selected_folder = selected_folder
        self.excluded_folders = excluded_folders
        self.rules = rules
        self.profile = profile

    def run(self) -> None:
        try:
            all_excluded = set(self.excluded_folders)
            if self.profile and self.profile.excluded_folders:
                all_excluded.update(self.profile.excluded_folders)
            included = self.profile.included_folders if self.profile and self.profile.included_folders else None
            doc_extract = self.profile.document_extraction if self.profile else True
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            scan_result = engine.run_phase_two(
                all_excluded,
                lambda msg: self.message.emit(str(msg)),
                included_folders=included,
                extract_documents=doc_extract,
            )
            rules_engine = RulesEngine(self.profile, scan_root=self.selected_folder.as_posix())
            matches = rules_engine.evaluate(scan_result.rows, self.rules)
            self.finished_scan.emit(scan_result, matches)
        except Exception as exc:
            self.failed.emit(str(exc))
