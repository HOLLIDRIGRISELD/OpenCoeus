from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QProgressBar, QTextEdit, QVBoxLayout, QWidget

from .config import ScanSettings
from .engine import ScanEngine, ScanResult, write_manifest


class ScanWorker(QThread):
    message = pyqtSignal(str)
    finished_scan = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path) -> None:
        super().__init__()
        self.selected_folder = selected_folder

    def run(self) -> None:
        try:
            # RUNS THE FILE SCAN OUTSIDE THE USER-INTERFACE THREAD.
            scan_engine = ScanEngine(ScanSettings(self.selected_folder))
            self.finished_scan.emit(scan_engine.run(self.message.emit))
        except Exception as scan_error:
            self.failed.emit(str(scan_error))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenCoeus - Offline Data Lifecycle Management")
        self.resize(900, 580)
        self.scan_result: ScanResult | None = None
        self.scan_worker: ScanWorker | None = None
        self.folder_path_input = QLineEdit()
        choose_folder_button = QPushButton("Choose folder")
        choose_folder_button.clicked.connect(self.choose_folder)
        self.run_button = QPushButton("Run safe scan")
        self.run_button.clicked.connect(self.start_scan)
        self.export_button = QPushButton("Export CSV manifest")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_manifest)
        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setRange(0, 0)
        self.scan_progress_bar.hide()
        self.audit_log = QTextEdit(readOnly=True)

        main_layout = QVBoxLayout()
        folder_selection_layout = QHBoxLayout()
        folder_selection_layout.addWidget(QLabel("Folder to scan:"))
        folder_selection_layout.addWidget(self.folder_path_input)
        folder_selection_layout.addWidget(choose_folder_button)
        main_layout.addLayout(folder_selection_layout)
        main_layout.addWidget(self.run_button)
        main_layout.addWidget(self.export_button)
        main_layout.addWidget(self.scan_progress_bar)
        main_layout.addWidget(QLabel("Audit log - this release does not alter files:"))
        main_layout.addWidget(self.audit_log)
        main_container = QWidget()
        main_container.setLayout(main_layout)
        self.setCentralWidget(main_container)

    def choose_folder(self) -> None:
        selected_folder = QFileDialog.getExistingDirectory(self, "Select folder to scan")
        if selected_folder:
            self.folder_path_input.setText(selected_folder)

    def start_scan(self) -> None:
        selected_folder = Path(self.folder_path_input.text())
        if not selected_folder.is_dir():
            QMessageBox.warning(self, "OpenCoeus", "Select a readable folder first.")
            return

        # RESETS THE INTERFACE BEFORE STARTING A NEW BACKGROUND SCAN.
        self.audit_log.clear()
        self.scan_result = None
        self.run_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.scan_progress_bar.show()
        self.scan_worker = ScanWorker(selected_folder)
        self.scan_worker.message.connect(self.audit_log.append)
        self.scan_worker.finished_scan.connect(self.scan_complete)
        self.scan_worker.failed.connect(self.scan_failed)
        self.scan_worker.start()

    def scan_complete(self, completed_result: ScanResult) -> None:
        self.scan_result = completed_result
        self.scan_progress_bar.hide()
        self.run_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.audit_log.append(
            f"<b>Complete:</b> {len(completed_result.rows)} files scanned, "
            f"{completed_result.duplicate_count} exact duplicates. "
            f"{len(completed_result.errors)} warnings."
        )

    def scan_failed(self, error_message: str) -> None:
        self.scan_progress_bar.hide()
        self.run_button.setEnabled(True)
        QMessageBox.critical(self, "Scan failed", error_message)

    def export_manifest(self) -> None:
        if not self.scan_result:
            return
        selected_output_path, _ = QFileDialog.getSaveFileName(
            self, "Save audit manifest", "opencoeus-manifest.csv", "CSV files (*.csv)"
        )
        if selected_output_path:
            write_manifest(self.scan_result, Path(selected_output_path))
            self.audit_log.append(f"Manifest saved: {selected_output_path}")


def main() -> int:
    application = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
