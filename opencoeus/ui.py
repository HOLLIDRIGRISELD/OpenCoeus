from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .config import ScanSettings
from .database import AuditStore
from .engine import ScanEngine, ScanResult, write_manifest
from .folder_tree import FolderNode, build_folder_tree, flatten_tree, set_folder_exclusion
from .profiles import ProfileConfig, create_profile, list_profiles, load_profile


class PhaseOneWorker(QThread):
    # PERFORMS PHASE ONE (FOLDER TREE DISCOVERY AND CLASSIFICATION) OFF THE UI THREAD.
    message = pyqtSignal(str)
    finished_tree = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path, custom_patterns: list[str] | None = None) -> None:
        super().__init__()
        self.selected_folder = selected_folder
        self.custom_patterns = custom_patterns

    def run(self) -> None:
        try:
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            result = engine.run_phase_one(self.message.emit, self.custom_patterns)
            tree_root = build_folder_tree(self.selected_folder, settings.protected_patterns)
            self.finished_tree.emit(result, tree_root)
        except Exception as scan_error:
            self.failed.emit(str(scan_error))


class PhaseTwoWorker(QThread):
    # PERFORMS PHASE TWO (FILE SCANNING WITH EXCLUSIONS) OFF THE UI THREAD.
    message = pyqtSignal(str)
    finished_scan = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path, excluded_folders: set[str]) -> None:
        super().__init__()
        self.selected_folder = selected_folder
        self.excluded_folders = excluded_folders

    def run(self) -> None:
        try:
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            result = engine.run_phase_two(self.excluded_folders, self.message.emit)
            self.finished_scan.emit(result)
        except Exception as scan_error:
            self.failed.emit(str(scan_error))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenCoeus - Data Lifecycle Management")
        self.resize(1100, 700)
        self.scan_result: ScanResult | None = None
        self.folder_tree_root: FolderNode | None = None
        self.excluded_folders: set[str] = set()
        self.current_profile: ProfileConfig | None = None
        self.store = AuditStore()
        self.phase_one_worker: PhaseOneWorker | None = None
        self.phase_two_worker: PhaseTwoWorker | None = None

        self._build_ui()
        self._load_profiles()

    def _build_ui(self) -> None:
        # BUILDS THE MAIN UI LAYOUT WITH LEFT SIDEBAR AND RIGHT TABBED AREA.
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.folder_path_input = QLineEdit()
        choose_folder_button = QPushButton("Choose folder")
        choose_folder_button.clicked.connect(self.choose_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Root folder:"))
        folder_layout.addWidget(self.folder_path_input)
        folder_layout.addWidget(choose_folder_button)
        main_layout.addLayout(folder_layout)

        self.phase_one_button = QPushButton("Phase 1: Discover folders")
        self.phase_one_button.clicked.connect(self.start_phase_one)
        self.phase_two_button = QPushButton("Phase 2: Scan files")
        self.phase_two_button.setEnabled(False)
        self.phase_two_button.clicked.connect(self.start_phase_two)
        self.export_button = QPushButton("Export CSV")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_manifest)
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.phase_one_button)
        button_layout.addWidget(self.phase_two_button)
        button_layout.addWidget(self.export_button)
        main_layout.addLayout(button_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Scan profiles:"))
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        left_layout.addWidget(self.profile_list)
        new_profile_button = QPushButton("New profile")
        new_profile_button.clicked.connect(self._create_new_profile)
        left_layout.addWidget(new_profile_button)
        left_layout.addWidget(QLabel("Folder tree (uncheck to exclude):"))
        self.folder_tree_widget = QTreeWidget()
        self.folder_tree_widget.setHeaderLabels(["Folder", "Files", "Size", "Class"])
        self.folder_tree_widget.setColumnCount(4)
        self.folder_tree_widget.itemChanged.connect(self._on_folder_toggled)
        left_layout.addWidget(self.folder_tree_widget)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(7)
        self.results_table.setHorizontalHeaderLabels([
            "Path", "Size", "Status", "Duplicate of", "Title", "Extension", "Folder",
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabs.addTab(self.results_table, "Scan results")

        self.actions_table = QTableWidget()
        self.actions_table.setColumnCount(4)
        self.actions_table.setHorizontalHeaderLabels([
            "Original Path", "Proposed Path", "Action", "Rule",
        ])
        self.actions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.actions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabs.addTab(self.actions_table, "Proposed actions")

        self.audit_log = QTextEdit(readOnly=True)
        self.tabs.addTab(self.audit_log, "Log")
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right_panel)

        splitter.setSizes([350, 750])
        main_layout.addWidget(splitter)

    def choose_folder(self) -> None:
        selected_folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if selected_folder:
            self.folder_path_input.setText(selected_folder)

    def start_phase_one(self) -> None:
        selected_folder = Path(self.folder_path_input.text())
        if not selected_folder.is_dir():
            QMessageBox.warning(self, "OpenCoeus", "Select a readable folder first.")
            return
        self.audit_log.clear()
        self.phase_one_button.setEnabled(False)
        self.progress_bar.show()
        self.phase_one_worker = PhaseOneWorker(selected_folder)
        self.phase_one_worker.message.connect(self.audit_log.append)
        self.phase_one_worker.finished_tree.connect(self.phase_one_complete)
        self.phase_one_worker.failed.connect(self.scan_failed)
        self.phase_one_worker.start()

    def phase_one_complete(self, scan_result: ScanResult, tree_root: FolderNode) -> None:
        self.scan_result = scan_result
        self.folder_tree_root = tree_root
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self._populate_folder_tree(tree_root)
        self.audit_log.append(
            f"<b>Phase 1 complete:</b> {len(scan_result.classifications)} folders classified."
        )

    def start_phase_two(self) -> None:
        selected_folder = Path(self.folder_path_input.text())
        if not selected_folder.is_dir():
            return
        self.phase_two_button.setEnabled(False)
        self.progress_bar.show()
        self.phase_two_worker = PhaseTwoWorker(selected_folder, self.excluded_folders)
        self.phase_two_worker.message.connect(self.audit_log.append)
        self.phase_two_worker.finished_scan.connect(self.phase_two_complete)
        self.phase_two_worker.failed.connect(self.scan_failed)
        self.phase_two_worker.start()

    def phase_two_complete(self, scan_result: ScanResult) -> None:
        self.scan_result = scan_result
        self.progress_bar.hide()
        self.phase_two_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self._populate_results_table(scan_result)
        self.audit_log.append(
            f"<b>Phase 2 complete:</b> {len(scan_result.rows)} files scanned, "
            f"{scan_result.duplicate_count} duplicates."
        )

    def scan_failed(self, error_message: str) -> None:
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        QMessageBox.critical(self, "Scan failed", error_message)

    def export_manifest(self) -> None:
        if not self.scan_result:
            return
        selected_output_path, _ = QFileDialog.getSaveFileName(
            self, "Save manifest", "opencoeus-manifest.csv", "CSV files (*.csv)"
        )
        if selected_output_path:
            write_manifest(self.scan_result, Path(selected_output_path))
            self.audit_log.append(f"Manifest saved: {selected_output_path}")

    def _load_profiles(self) -> None:
        profiles = list_profiles(self.store)
        self.profile_list.clear()
        for profile in profiles:
            self.profile_list.addItem(profile.name)

    def _on_profile_selected(self, current, _previous) -> None:
        if current is None:
            return
        self.current_profile = load_profile(self.store, 1)

    def _create_new_profile(self) -> None:
        name, ok = QFileDialog.getSaveFileName(self, "Profile name", "", "Text files (*.txt)")
        if name:
            create_profile(self.store, Path(name).stem)
            self._load_profiles()

    def _populate_folder_tree(self, root: FolderNode) -> None:
        self.folder_tree_widget.clear()
        self.folder_tree_widget.blockSignals(True)
        root_item = QTreeWidgetItem(self.folder_tree_widget, [
            root.name, str(root.file_count), self._format_size(root.total_size), "",
        ])
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setCheckState(0, Qt.CheckState.Checked)
        root_item.setData(0, Qt.ItemDataRole.UserRole, root.path.as_posix())
        self._add_children_to_tree(root, root_item)
        self.folder_tree_widget.expandAll()
        self.folder_tree_widget.blockSignals(False)

    def _add_children_to_tree(self, node: FolderNode, parent_item: QTreeWidgetItem) -> None:
        for child in node.children:
            child_item = QTreeWidgetItem(parent_item, [
                child.name, str(child.file_count), self._format_size(child.total_size),
                child.classification or "",
            ])
            child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child_item.setCheckState(0, Qt.CheckState.Checked)
            child_item.setData(0, Qt.ItemDataRole.UserRole, child.path.as_posix())
            if child.is_protected:
                child_item.setForeground(3, Qt.GlobalColor.red)
            self._add_children_to_tree(child, child_item)

    def _on_folder_toggled(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self.folder_tree_root is None:
            return
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if folder_path is None:
            return
        is_checked = item.checkState(0) == Qt.CheckState.Checked
        self.folder_tree_widget.blockSignals(True)
        if is_checked:
            self.excluded_folders.discard(folder_path)
            set_folder_exclusion(self.folder_tree_root, Path(folder_path), excluded=False)
        else:
            self.excluded_folders.add(folder_path)
            set_folder_exclusion(self.folder_tree_root, Path(folder_path), excluded=True)
        self.folder_tree_widget.blockSignals(False)

    def _populate_results_table(self, scan_result: ScanResult) -> None:
        self.results_table.setRowCount(len(scan_result.rows))
        for row_number, manifest_row in enumerate(scan_result.rows):
            self.results_table.setItem(row_number, 0, QTableWidgetItem(manifest_row.path))
            self.results_table.setItem(row_number, 1, QTableWidgetItem(str(manifest_row.size)))
            status_item = QTableWidgetItem(manifest_row.status)
            if manifest_row.status == "duplicate":
                status_item.setForeground(Qt.GlobalColor.red)
            elif manifest_row.status == "protected":
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            self.results_table.setItem(row_number, 2, status_item)
            self.results_table.setItem(row_number, 3, QTableWidgetItem(manifest_row.duplicate_of))
            self.results_table.setItem(row_number, 4, QTableWidgetItem(manifest_row.suggested_title))
            self.results_table.setItem(row_number, 5, QTableWidgetItem(manifest_row.extension))
            self.results_table.setItem(row_number, 6, QTableWidgetItem(manifest_row.folder_path))

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def main() -> int:
    application = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
