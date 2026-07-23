from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QSplitter, QStatusBar, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .config import ScanSettings
from .database import AuditStore
from .engine import ScanEngine, ScanResult, write_manifest
from .folder_tree import FolderNode, build_folder_tree, set_folder_exclusion
from .profiles import ProfileConfig, create_profile, list_profiles, load_profile, load_profile_by_name
from .rules_engine import RulesEngine, RuleMatch


# DEFAULT RULES THAT APPLY COMMON ORGANIZATION PATTERNS OUT OF THE BOX.
DEFAULT_RULES = [
    {
        "id": 1, "name": "Documents", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".rtf", ".odt"]}',
        "destination_template": "{folder}/Documents/{filename}", "action_type": "move",
    },
    {
        "id": 2, "name": "Images", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff"]}',
        "destination_template": "{folder}/Images/{filename}", "action_type": "move",
    },
    {
        "id": 3, "name": "Audio", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"]}',
        "destination_template": "{folder}/Audio/{filename}", "action_type": "move",
    },
    {
        "id": 4, "name": "Video", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"]}',
        "destination_template": "{folder}/Video/{filename}", "action_type": "move",
    },
    {
        "id": 5, "name": "Archives", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]}',
        "destination_template": "{folder}/Archives/{filename}", "action_type": "move",
    },
    {
        "id": 6, "name": "Code", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".go", ".rs", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".toml"]}',
        "destination_template": "{folder}/Code/{filename}", "action_type": "move",
    },
    {
        "id": 7, "name": "Installers", "rule_type": "extension", "enabled": True, "priority": 10,
        "rule_config": '{"extensions": [".msi", ".exe", ".dmg", ".deb", ".rpm", ".apk"]}',
        "destination_template": "{folder}/Installers/{filename}", "action_type": "move",
    },
    {
        "id": 8, "name": "Old files archive", "rule_type": "date", "enabled": True, "priority": 50,
        "rule_config": '{"older_than_days": 365}',
        "destination_template": "{folder}/Archive/{date_year}/{filename}", "action_type": "move",
    },
]


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
            result = engine.run_phase_one(lambda msg: self.message.emit(str(msg)), self.custom_patterns)
            tree_root = build_folder_tree(self.selected_folder, settings.protected_patterns, max_depth=5)
            self.finished_tree.emit(result, tree_root)
        except Exception as scan_error:
            self.failed.emit(str(scan_error))


class PhaseTwoWorker(QThread):
    # PERFORMS PHASE TWO (FILE SCANNING + RULES ENGINE) OFF THE UI THREAD.
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
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            scan_result = engine.run_phase_two(self.excluded_folders, lambda msg: self.message.emit(str(msg)))
            rules_engine = RulesEngine(self.profile)
            matches = rules_engine.evaluate(scan_result.rows, self.rules)
            self.finished_scan.emit(scan_result, matches)
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
        self.active_rules: list[dict] = list(DEFAULT_RULES)
        self.proposed_matches: list[RuleMatch] = []
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

        # ROOT FOLDER SELECTION ROW.
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select a folder to scan...")
        choose_folder_button = QPushButton("Browse...")
        choose_folder_button.clicked.connect(self.choose_folder)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Root folder:"))
        folder_layout.addWidget(self.folder_path_input)
        folder_layout.addWidget(choose_folder_button)
        main_layout.addLayout(folder_layout)

        # PHASE ONE / PHASE TWO / EXPORT BUTTON ROW.
        self.phase_one_button = QPushButton("1. Discover folders")
        self.phase_one_button.clicked.connect(self.start_phase_one)
        self.phase_two_button = QPushButton("2. Scan & organize")
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

        # PROGRESS BAR.
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

        # MAIN SPLITTER: LEFT (PROFILES + FOLDER TREE) | RIGHT (TABS).
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # LEFT PANEL: PROFILES + FOLDER TREE.
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("Scan profiles:"))
        profile_row = QHBoxLayout()
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_list)
        new_profile_button = QPushButton("+")
        new_profile_button.setFixedWidth(30)
        new_profile_button.setToolTip("Create new profile")
        new_profile_button.clicked.connect(self._create_new_profile)
        profile_row.addWidget(new_profile_button)
        left_layout.addLayout(profile_row)

        left_layout.addWidget(QLabel("Folder tree (uncheck to exclude from scan):"))
        self.folder_tree_widget = QTreeWidget()
        self.folder_tree_widget.setHeaderLabels(["Folder", "Files", "Size", "Type"])
        self.folder_tree_widget.setColumnCount(4)
        self.folder_tree_widget.itemChanged.connect(self._on_folder_toggled)
        self.folder_tree_widget.setAlternatingRowColors(True)
        left_layout.addWidget(self.folder_tree_widget)
        splitter.addWidget(left_panel)

        # RIGHT PANEL: TABBED RESULTS.
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()

        # SCAN RESULTS TAB.
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(7)
        self.results_table.setHorizontalHeaderLabels([
            "Path", "Size", "Status", "Duplicate of", "Title", "Ext", "Folder",
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setAlternatingRowColors(True)
        self.tabs.addTab(self.results_table, "Scan results")

        # PROPOSED ACTIONS TAB WITH APPROVE/REJECT CONTROLS.
        actions_tab = QWidget()
        actions_layout = QVBoxLayout(actions_tab)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_toolbar = QHBoxLayout()
        self.approve_selected_button = QPushButton("Approve selected")
        self.approve_selected_button.clicked.connect(self._approve_selected)
        self.approve_all_button = QPushButton("Approve all")
        self.approve_all_button.clicked.connect(self._approve_all)
        self.reject_selected_button = QPushButton("Remove selected")
        self.reject_selected_button.clicked.connect(self._reject_selected)
        actions_toolbar.addWidget(self.approve_selected_button)
        actions_toolbar.addWidget(self.approve_all_button)
        actions_toolbar.addWidget(self.reject_selected_button)
        actions_toolbar.addStretch()
        self.actions_count_label = QLabel("No actions proposed")
        actions_toolbar.addWidget(self.actions_count_label)
        actions_layout.addLayout(actions_toolbar)

        self.actions_table = QTableWidget()
        self.actions_table.setColumnCount(5)
        self.actions_table.setHorizontalHeaderLabels([
            "Status", "Original Path", "Proposed Path", "Action", "Reason",
        ])
        self.actions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.actions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.actions_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.actions_table.setAlternatingRowColors(True)
        actions_layout.addWidget(self.actions_table)
        self.tabs.addTab(actions_tab, "Proposed actions")

        # LOG TAB.
        self.audit_log = QTextEdit(readOnly=True)
        self.tabs.addTab(self.audit_log, "Log")

        right_layout.addWidget(self.tabs)
        splitter.addWidget(right_panel)

        splitter.setSizes([350, 750])
        main_layout.addWidget(splitter)

        # STATUS BAR.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

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
        self.results_table.setRowCount(0)
        self.actions_table.setRowCount(0)
        self.proposed_matches.clear()
        self.excluded_folders.clear()
        self.phase_one_button.setEnabled(False)
        self.phase_two_button.setEnabled(False)
        self.progress_bar.show()
        self.status_bar.showMessage("Phase 1: Discovering folders...")
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
        self.status_bar.showMessage(
            f"Phase 1 complete: {len(scan_result.classifications)} folders classified. "
            f"Review the tree and uncheck folders to exclude, then click 'Scan & organize'."
        )
        self.audit_log.append(
            f"<b>Phase 1 complete:</b> {len(scan_result.classifications)} folders classified. "
            f"Excluded: {len(self.excluded_folders)} folders."
        )

    def start_phase_two(self) -> None:
        selected_folder = Path(self.folder_path_input.text())
        if not selected_folder.is_dir():
            return
        self.phase_two_button.setEnabled(False)
        self.phase_one_button.setEnabled(False)
        self.progress_bar.show()
        self.status_bar.showMessage("Phase 2: Scanning files and applying rules...")
        profile = self.current_profile or ProfileConfig()
        self.phase_two_worker = PhaseTwoWorker(
            selected_folder, self.excluded_folders, self.active_rules, profile,
        )
        self.phase_two_worker.message.connect(self.audit_log.append)
        self.phase_two_worker.finished_scan.connect(self.phase_two_complete)
        self.phase_two_worker.failed.connect(self.scan_failed)
        self.phase_two_worker.start()

    def phase_two_complete(self, scan_result: ScanResult, matches: list[RuleMatch]) -> None:
        self.scan_result = scan_result
        self.proposed_matches = matches
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self._populate_results_table(scan_result)
        self._populate_actions_table(matches)
        self.tabs.setCurrentIndex(0)
        self.status_bar.showMessage(
            f"Phase 2 complete: {len(scan_result.rows)} files scanned, "
            f"{scan_result.duplicate_count} duplicates, "
            f"{len(matches)} proposed actions."
        )
        self.audit_log.append(
            f"<b>Phase 2 complete:</b> {len(scan_result.rows)} files scanned, "
            f"{scan_result.duplicate_count} duplicates, "
            f"{len(matches)} organization actions proposed."
        )

    def scan_failed(self, error_message: str) -> None:
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.status_bar.showMessage("Scan failed")
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

    def _approve_selected(self) -> None:
        selected_rows = {idx.row() for idx in self.actions_table.selectedIndexes()}
        for row in selected_rows:
            status_item = self.actions_table.item(row, 0)
            if status_item and status_item.text() != "APPROVED":
                status_item.setText("APPROVED")
                status_item.setForeground(Qt.GlobalColor.darkGreen)
        self._update_actions_count()

    def _approve_all(self) -> None:
        for row in range(self.actions_table.rowCount()):
            status_item = self.actions_table.item(row, 0)
            if status_item:
                status_item.setText("APPROVED")
                status_item.setForeground(Qt.GlobalColor.darkGreen)
        self._update_actions_count()

    def _reject_selected(self) -> None:
        selected_rows = sorted({idx.row() for idx in self.actions_table.selectedIndexes()}, reverse=True)
        for row in selected_rows:
            self.actions_table.removeRow(row)
            if row < len(self.proposed_matches):
                self.proposed_matches.pop(row)
        self._update_actions_count()

    def _update_actions_count(self) -> None:
        approved = sum(
            1 for row in range(self.actions_table.rowCount())
            if self.actions_table.item(row, 0) and self.actions_table.item(row, 0).text() == "APPROVED"
        )
        total = self.actions_table.rowCount()
        self.actions_count_label.setText(f"{approved}/{total} approved")

    def _load_profiles(self) -> None:
        profiles = list_profiles(self.store)
        self.profile_list.clear()
        for profile in profiles:
            self.profile_list.addItem(profile.name)

    def _on_profile_selected(self, current, _previous) -> None:
        if current is None:
            self.current_profile = None
            return
        self.current_profile = load_profile_by_name(self.store, current.text())

    def _create_new_profile(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if ok and name.strip():
            create_profile(self.store, name.strip())
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
        self.folder_tree_widget.expandToDepth(1)
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
            if child.recommended_action == "exclude":
                child_item.setForeground(3, Qt.GlobalColor.red)
                child_item.setCheckState(0, Qt.CheckState.Unchecked)
                self.excluded_folders.add(child.path.as_posix())
            elif child.classification in {"source_code", "unknown"}:
                child_item.setForeground(3, Qt.GlobalColor.darkYellow)
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
            self.results_table.setItem(row_number, 1, QTableWidgetItem(self._format_size(manifest_row.size)))
            status_item = QTableWidgetItem(manifest_row.status.upper())
            if manifest_row.status == "duplicate":
                status_item.setForeground(Qt.GlobalColor.red)
            elif manifest_row.status == "protected":
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            elif manifest_row.status == "unique":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            self.results_table.setItem(row_number, 2, status_item)
            self.results_table.setItem(row_number, 3, QTableWidgetItem(manifest_row.duplicate_of))
            self.results_table.setItem(row_number, 4, QTableWidgetItem(manifest_row.suggested_title))
            self.results_table.setItem(row_number, 5, QTableWidgetItem(manifest_row.extension))
            self.results_table.setItem(row_number, 6, QTableWidgetItem(manifest_row.folder_path))

    def _populate_actions_table(self, matches: list[RuleMatch]) -> None:
        self.actions_table.setRowCount(len(matches))
        for row_number, match in enumerate(matches):
            status_item = QTableWidgetItem("PENDING")
            status_item.setForeground(Qt.GlobalColor.gray)
            self.actions_table.setItem(row_number, 0, status_item)
            self.actions_table.setItem(row_number, 1, QTableWidgetItem(match.original_path))
            self.actions_table.setItem(row_number, 2, QTableWidgetItem(match.proposed_path))
            action_item = QTableWidgetItem(match.action_type.upper())
            self.actions_table.setItem(row_number, 3, action_item)
            self.actions_table.setItem(row_number, 4, QTableWidgetItem(match.reason))
        self._update_actions_count()
        self.tabs.setCurrentIndex(1)

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
