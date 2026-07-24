from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from ...config import ScanSettings
from ...engine import ScanEngine
from ...folder_tree import build_folder_tree
from ...profiles import ProfileConfig


class PhaseOneWorker(QThread):
    message = pyqtSignal(str)
    finished_tree = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path, profile: ProfileConfig) -> None:
        super().__init__()
        self.selected_folder = selected_folder
        self.profile = profile

    def run(self) -> None:
        try:
            merged_patterns = list(self.profile.custom_protected_patterns) if self.profile else []
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            result = engine.run_phase_one(
                lambda msg: self.message.emit(str(msg)),
                custom_patterns=merged_patterns or None,
                profile_id=self.profile.profile_id if self.profile and self.profile.profile_id else 1,
            )
            tree_root = build_folder_tree(self.selected_folder, settings.protected_patterns, max_depth=5)
            self.finished_tree.emit(result, tree_root)
        except Exception as exc:
            self.failed.emit(str(exc))
