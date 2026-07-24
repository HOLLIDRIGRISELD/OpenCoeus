from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from ...engine import ScanResult, write_manifest


class ExportWorker(QThread):
    finished_export = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, scan_result: ScanResult, path: Path) -> None:
        super().__init__()
        self.scan_result = scan_result
        self.path = path

    def run(self) -> None:
        try:
            write_manifest(self.scan_result, self.path)
            self.finished_export.emit(str(self.path))
        except Exception as exc:
            self.failed.emit(str(exc))
