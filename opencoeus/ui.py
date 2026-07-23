from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSplitter, QStatusBar, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .config import ScanSettings
from .database import AuditStore
from .engine import ScanEngine, ScanResult, write_manifest
from .folder_tree import FolderNode, build_folder_tree, set_folder_exclusion
from .profiles import ProfileConfig, create_profile, list_profiles, load_profile_by_name
from .rules_engine import RulesEngine, RuleMatch


DEFAULT_RULES = [
    {"id": 1, "name": "Documents", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".rtf", ".odt"]}',
     "destination_template": "{folder}/Documents/{filename}", "action_type": "move"},
    {"id": 2, "name": "Images", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff"]}',
     "destination_template": "{folder}/Images/{filename}", "action_type": "move"},
    {"id": 3, "name": "Audio", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"]}',
     "destination_template": "{folder}/Audio/{filename}", "action_type": "move"},
    {"id": 4, "name": "Video", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"]}',
     "destination_template": "{folder}/Video/{filename}", "action_type": "move"},
    {"id": 5, "name": "Archives", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]}',
     "destination_template": "{folder}/Archives/{filename}", "action_type": "move"},
    {"id": 6, "name": "Code", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".go", ".rs", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".toml"]}',
     "destination_template": "{folder}/Code/{filename}", "action_type": "move"},
    {"id": 7, "name": "Installers", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".msi", ".exe", ".dmg", ".deb", ".rpm", ".apk"]}',
     "destination_template": "{folder}/Installers/{filename}", "action_type": "move"},
    {"id": 8, "name": "Old files archive", "rule_type": "date", "enabled": True, "priority": 50,
     "rule_config": '{"older_than_days": 365}',
     "destination_template": "{folder}/Archive/{date_year}/{filename}", "action_type": "move"},
]


class PhaseOneWorker(QThread):
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
        self.setMinimumSize(800, 500)
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
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        # TOP BAR: folder input + action buttons + progress bar.
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select a folder to scan...")
        self.folder_path_input.setMinimumWidth(300)
        browse_button = QPushButton("Browse")
        browse_button.setFixedWidth(70)
        browse_button.clicked.connect(self._choose_folder)
        self.phase_one_button = QPushButton("1. Discover folders")
        self.phase_one_button.setFixedWidth(140)
        self.phase_one_button.clicked.connect(self._start_phase_one)
        self.phase_two_button = QPushButton("2. Scan && organize")
        self.phase_two_button.setFixedWidth(140)
        self.phase_two_button.setEnabled(False)
        self.phase_two_button.clicked.connect(self._start_phase_two)
        self.export_button = QPushButton("Export CSV")
        self.export_button.setFixedWidth(90)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_manifest)
        top_bar.addWidget(self.folder_path_input, 1)
        top_bar.addWidget(browse_button)
        top_bar.addWidget(self.phase_one_button)
        top_bar.addWidget(self.phase_two_button)
        top_bar.addWidget(self.export_button)
        root_layout.addLayout(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.hide()
        root_layout.addWidget(self.progress_bar)

        # MAIN AREA: splitter with left (profiles + tree) and right (tabs).
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # LEFT SIDEBAR.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_layout.addWidget(self._label("Profiles"))
        profile_row = QHBoxLayout()
        profile_row.setSpacing(4)
        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(100)
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_list, 1)
        add_profile_button = QPushButton("+")
        add_profile_button.setFixedSize(24, 24)
        add_profile_button.setToolTip("Create new profile")
        add_profile_button.clicked.connect(self._create_new_profile)
        profile_row.addWidget(add_profile_button)
        left_layout.addLayout(profile_row)

        left_layout.addWidget(self._label("Folders (uncheck to exclude)"))
        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabels(["Folder", "Files", "Size", "Type"])
        self.folder_tree.setColumnCount(4)
        self.folder_tree.setAlternatingRowColors(True)
        self.folder_tree.itemChanged.connect(self._on_folder_toggled)
        self.folder_tree.setMinimumWidth(250)
        left_layout.addWidget(self.folder_tree, 1)

        splitter.addWidget(left)

        # RIGHT PANEL: tabs.
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # TAB 1: scan results.
        self.results_table = self._make_table(
            ["Path", "Size", "Status", "Duplicate of", "Title", "Ext", "Folder"],
            stretch_column=0,
        )
        self.tabs.addTab(self.results_table, "Scan results")

        # TAB 2: proposed actions.
        actions_page = QWidget()
        actions_layout = QVBoxLayout(actions_page)
        actions_layout.setContentsMargins(0, 4, 0, 0)
        actions_layout.setSpacing(4)

        actions_toolbar = QHBoxLayout()
        actions_toolbar.setSpacing(4)
        approve_btn = QPushButton("Approve selected")
        approve_btn.clicked.connect(self._approve_selected)
        approve_all_btn = QPushButton("Approve all")
        approve_all_btn.clicked.connect(self._approve_all)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._reject_selected)
        self.actions_count_label = QLabel("No actions")
        actions_toolbar.addWidget(approve_btn)
        actions_toolbar.addWidget(approve_all_btn)
        actions_toolbar.addWidget(remove_btn)
        actions_toolbar.addStretch()
        actions_toolbar.addWidget(self.actions_count_label)
        actions_layout.addLayout(actions_toolbar)

        self.actions_table = self._make_table(
            ["Status", "Original Path", "Proposed Path", "Action", "Reason"],
            stretch_column=1,
            select_mode=QTableWidget.SelectionMode.ExtendedSelection,
        )
        actions_layout.addWidget(self.actions_table, 1)
        self.tabs.addTab(actions_page, "Proposed actions")

        # TAB 3: log.
        self.audit_log = QTextEdit()
        self.audit_log.setReadOnly(True)
        self.audit_log.setMinimumHeight(100)
        self.tabs.addTab(self.audit_log, "Log")

        right_layout.addWidget(self.tabs, 1)
        splitter.addWidget(right)

        # STRETCH: left gets 30%, right gets 70%.
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([330, 770])

        root_layout.addWidget(splitter, 1)

        # STATUS BAR.
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; padding-top: 4px;")
        return lbl

    def _make_table(
        self,
        headers: list[str],
        stretch_column: int = 0,
        select_mode: QTableWidget.SelectionMode = QTableWidget.SelectionMode.SingleSelection,
    ) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(select_mode)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        return table

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            self.folder_path_input.setText(folder)

    def _start_phase_one(self) -> None:
        folder = Path(self.folder_path_input.text())
        if not folder.is_dir():
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
        self.phase_one_worker = PhaseOneWorker(folder)
        self.phase_one_worker.message.connect(self.audit_log.append)
        self.phase_one_worker.finished_tree.connect(self._phase_one_done)
        self.phase_one_worker.failed.connect(self._scan_failed)
        self.phase_one_worker.start()

    def _phase_one_done(self, scan_result: ScanResult, tree_root: FolderNode) -> None:
        self.scan_result = scan_result
        self.folder_tree_root = tree_root
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self._fill_folder_tree(tree_root)
        n = len(scan_result.classifications)
        ex = len(self.excluded_folders)
        self.status_bar.showMessage(f"Phase 1 done: {n} folders classified, {ex} excluded. Review tree, then click 'Scan && organize'.")
        self.audit_log.append(f"<b>Phase 1:</b> {n} folders classified, {ex} excluded automatically.")

    def _start_phase_two(self) -> None:
        folder = Path(self.folder_path_input.text())
        if not folder.is_dir():
            return
        self.phase_two_button.setEnabled(False)
        self.phase_one_button.setEnabled(False)
        self.progress_bar.show()
        self.status_bar.showMessage("Phase 2: Scanning files and applying rules...")
        profile = self.current_profile or ProfileConfig()
        self.phase_two_worker = PhaseTwoWorker(folder, self.excluded_folders, self.active_rules, profile)
        self.phase_two_worker.message.connect(self.audit_log.append)
        self.phase_two_worker.finished_scan.connect(self._phase_two_done)
        self.phase_two_worker.failed.connect(self._scan_failed)
        self.phase_two_worker.start()

    def _phase_two_done(self, scan_result: ScanResult, matches: list[RuleMatch]) -> None:
        self.scan_result = scan_result
        self.proposed_matches = matches
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self._fill_results_table(scan_result)
        self._fill_actions_table(matches)
        self.tabs.setCurrentIndex(0)
        dup = scan_result.duplicate_count
        self.status_bar.showMessage(
            f"Phase 2 done: {len(scan_result.rows)} files, {dup} duplicates, {len(matches)} proposed actions."
        )
        self.audit_log.append(
            f"<b>Phase 2:</b> {len(scan_result.rows)} files, {dup} duplicates, {len(matches)} actions proposed."
        )

    def _scan_failed(self, msg: str) -> None:
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.status_bar.showMessage("Scan failed")
        QMessageBox.critical(self, "Scan failed", msg)

    def _export_manifest(self) -> None:
        if not self.scan_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save manifest", "opencoeus-manifest.csv", "CSV files (*.csv)")
        if path:
            write_manifest(self.scan_result, Path(path))
            self.audit_log.append(f"Manifest saved: {path}")

    # ACTIONS TABLE CONTROLS.

    def _approve_selected(self) -> None:
        rows = {idx.row() for idx in self.actions_table.selectedIndexes()}
        for r in rows:
            item = self.actions_table.item(r, 0)
            if item and item.text() != "APPROVED":
                item.setText("APPROVED")
                item.setForeground(QColor("darkgreen"))
        self._refresh_actions_count()

    def _approve_all(self) -> None:
        for r in range(self.actions_table.rowCount()):
            item = self.actions_table.item(r, 0)
            if item:
                item.setText("APPROVED")
                item.setForeground(QColor("darkgreen"))
        self._refresh_actions_count()

    def _reject_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.actions_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.actions_table.removeRow(r)
            if r < len(self.proposed_matches):
                self.proposed_matches.pop(r)
        self._refresh_actions_count()

    def _refresh_actions_count(self) -> None:
        approved = sum(
            1 for r in range(self.actions_table.rowCount())
            if self.actions_table.item(r, 0) and self.actions_table.item(r, 0).text() == "APPROVED"
        )
        total = self.actions_table.rowCount()
        self.actions_count_label.setText(f"{approved}/{total} approved")

    # PROFILES.

    def _load_profiles(self) -> None:
        self.profile_list.clear()
        for p in list_profiles(self.store):
            self.profile_list.addItem(p.name)

    def _on_profile_selected(self, current, _prev) -> None:
        self.current_profile = load_profile_by_name(self.store, current.text()) if current else None

    def _create_new_profile(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if ok and name.strip():
            create_profile(self.store, name.strip())
            self._load_profiles()

    # FOLDER TREE.

    def _fill_folder_tree(self, root: FolderNode) -> None:
        self.folder_tree.clear()
        self.folder_tree.blockSignals(True)
        root_item = QTreeWidgetItem(self.folder_tree, [
            root.name, str(root.file_count), self._fmt(root.total_size), "",
        ])
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setCheckState(0, Qt.CheckState.Checked)
        root_item.setData(0, Qt.ItemDataRole.UserRole, root.path.as_posix())
        self._add_tree_children(root, root_item)
        self.folder_tree.expandToDepth(1)
        self.folder_tree.blockSignals(False)

    def _add_tree_children(self, node: FolderNode, parent: QTreeWidgetItem) -> None:
        for child in node.children:
            item = QTreeWidgetItem(parent, [
                child.name, str(child.file_count), self._fmt(child.total_size),
                child.classification or "",
            ])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, Qt.ItemDataRole.UserRole, child.path.as_posix())
            if child.recommended_action == "exclude":
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setForeground(3, QColor("red"))
                self.excluded_folders.add(child.path.as_posix())
            else:
                item.setCheckState(0, Qt.CheckState.Checked)
                if child.classification in {"source_code", "unknown"}:
                    item.setForeground(3, QColor("darkYellow"))
            self._add_tree_children(child, item)

    def _on_folder_toggled(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0 or self.folder_tree_root is None:
            return
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if path_str is None:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        self.folder_tree.blockSignals(True)
        if checked:
            self.excluded_folders.discard(path_str)
            set_folder_exclusion(self.folder_tree_root, Path(path_str), excluded=False)
        else:
            self.excluded_folders.add(path_str)
            set_folder_exclusion(self.folder_tree_root, Path(path_str), excluded=True)
        self.folder_tree.blockSignals(False)

    # POPULATE TABLES.

    def _fill_results_table(self, result: ScanResult) -> None:
        t = self.results_table
        t.setRowCount(len(result.rows))
        for i, r in enumerate(result.rows):
            t.setItem(i, 0, QTableWidgetItem(r.path))
            t.setItem(i, 1, QTableWidgetItem(self._fmt(r.size)))
            status = QTableWidgetItem(r.status.upper())
            color = {"duplicate": "red", "protected": "darkYellow", "unique": "darkGreen"}.get(r.status)
            if color:
                status.setForeground(QColor(color))
            t.setItem(i, 2, status)
            t.setItem(i, 3, QTableWidgetItem(r.duplicate_of))
            t.setItem(i, 4, QTableWidgetItem(r.suggested_title))
            t.setItem(i, 5, QTableWidgetItem(r.extension))
            t.setItem(i, 6, QTableWidgetItem(r.folder_path))

    def _fill_actions_table(self, matches: list[RuleMatch]) -> None:
        t = self.actions_table
        t.setRowCount(len(matches))
        for i, m in enumerate(matches):
            status = QTableWidgetItem("PENDING")
            status.setForeground(QColor("gray"))
            t.setItem(i, 0, status)
            t.setItem(i, 1, QTableWidgetItem(m.original_path))
            t.setItem(i, 2, QTableWidgetItem(m.proposed_path))
            t.setItem(i, 3, QTableWidgetItem(m.action_type.upper()))
            t.setItem(i, 4, QTableWidgetItem(m.reason))
        self._refresh_actions_count()
        self.tabs.setCurrentIndex(1)

    @staticmethod
    def _fmt(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1048576:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1048576:.1f} MB"


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
