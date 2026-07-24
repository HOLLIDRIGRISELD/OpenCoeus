from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QAction, QColor, QKeySequence
from PyQt6.QtWidgets import (
    QButtonGroup, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMenuBar, QMessageBox, QProgressBar,
    QPushButton, QStatusBar, QVBoxLayout, QWidget,
)

from ..config import ScanSettings
from ..database import AuditStore
from ..engine import ScanEngine, ScanResult
from ..executor import ExecutionResult
from ..folder_tree import FolderNode, build_folder_tree, build_node_index, set_folder_exclusion
from ..profiles import (
    ProfileConfig, create_profile, delete_profile, list_profiles,
    load_profile_by_name, update_profile,
)
from ..rules_engine import DEFAULT_RULES, RulesEngine, RuleMatch
from .theme import COLORS, global_stylesheet
from .widgets import SidebarButton, StatCard
from .pages import HomePage, FoldersPage, ResultsPage, ActionsPage, RulesPage, LogPage
from .dialogs import AboutDialog, BatchDetailDialog, ProfileEditDialog, RuleEditDialog
from .workers import (
    PhaseOneWorker, PhaseTwoWorker, ExportWorker,
    ExecutionWorker, PrepareWorker, UndoWorker,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenCoeus v0.1.0")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 800)
        self.setWindowIcon(self._create_icon())

        # SHARED STATE.
        self.scan_result: ScanResult | None = None
        self.folder_tree_root: FolderNode | None = None
        self.excluded_folders: set[str] = set()
        self.current_profile: ProfileConfig | None = None
        self.active_rules: list[dict] = list(DEFAULT_RULES)
        self.proposed_matches: list[RuleMatch] = []
        self._node_index: dict[str, FolderNode] = {}
        self.store = AuditStore()
        self._action_id_map: dict[str, int] = {}

        # WORKER REFERENCES.
        self.phase_one_worker: PhaseOneWorker | None = None
        self.phase_two_worker: PhaseTwoWorker | None = None
        self.execution_worker: ExecutionWorker | None = None
        self.prepare_worker: PrepareWorker | None = None
        self.undo_worker: UndoWorker | None = None
        self.export_worker: ExportWorker | None = None

        # LOG BUFFER.
        self._log_buffer: list[str] = []
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.setInterval(100)

        # BUILD UI.
        self._nav_buttons: list[SidebarButton] = []
        self._pages: list[QWidget] = []
        self._build_ui()
        self._build_menu_bar()
        self.setStyleSheet(global_stylesheet())

        # INITIALIZE PAGES.
        self.home_page.set_main(self)
        self.folders_page.set_main(self)
        self.results_page.set_main(self)
        self.actions_page.set_main(self)
        self.rules_page.set_main(self)
        self.log_page.set_main(self)

        # INITIAL DATA LOAD.
        self._load_profiles()
        self._switch_page(0)
        self.status_bar.showMessage("Ready")

        # CRASH RECOVERY ON STARTUP.
        self._recover_crashed_batches()

    @staticmethod
    def _create_icon():
        """Create a simple icon from app initials using QPixmap."""
        from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(COLORS["accent2"]))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#ffffff"))
        font = QFont("Arial", 28, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "OC")
        painter.end()
        return QIcon(pixmap)

    # ---- UI CONSTRUCTION ---- #
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # SIDEBAR.
        sidebar = QWidget()
        sidebar.setFixedWidth(150)
        sidebar.setStyleSheet(f"""
            QWidget {{
                background: {COLORS["sidebar_bg"]};
                border-right: 1px solid {COLORS["border"]};
            }}
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(8, 16, 8, 16)
        sb_layout.setSpacing(4)

        app_label = QLabel("OpenCoeus")
        app_label.setStyleSheet(f"color: {COLORS['accent']}; font-size: 15px; font-weight: bold; border: none; padding: 4px 8px;")
        sb_layout.addWidget(app_label)

        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        nav_labels = ["Home", "Folders", "Results", "Actions", "Rules", "Log"]
        for i, label in enumerate(nav_labels):
            btn = SidebarButton(label)
            btn.setToolTip(f"Switch to {label} page (Ctrl+{i+1})")
            nav_group.addButton(btn, i)
            self._nav_buttons.append(btn)
            sb_layout.addWidget(btn)
        sb_layout.addStretch()
        root.addWidget(sidebar)

        # MAIN CONTENT.
        content = QWidget()
        content.setStyleSheet(f"background: {COLORS['bg']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self._build_header(content_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.hide()
        content_layout.addWidget(self.progress_bar)

        # PAGES.
        self.home_page = HomePage()
        self.folders_page = FoldersPage()
        self.results_page = ResultsPage()
        self.actions_page = ActionsPage()
        self.rules_page = RulesPage()
        self.log_page = LogPage()

        self._pages = [
            self.home_page,
            self.folders_page,
            self.results_page,
            self.actions_page,
            self.rules_page,
            self.log_page,
        ]
        page_container = QWidget()
        page_stack = QVBoxLayout(page_container)
        page_stack.setContentsMargins(0, 0, 0, 0)
        page_stack.setSpacing(0)
        for page in self._pages:
            page_stack.addWidget(page)
        content_layout.addWidget(page_container, 1)
        root.addWidget(content, 1)

        nav_group.idClicked.connect(self._switch_page)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        header = QWidget()
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            QWidget {{
                background: {COLORS["surface"]};
                border-bottom: 1px solid {COLORS["border"]};
            }}
        """)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(20, 0, 20, 0)
        hlay.setSpacing(12)

        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select a folder to scan...")
        self.folder_path_input.setMinimumWidth(280)
        self.folder_path_input.setToolTip("Path to the root folder for scanning (Ctrl+O to browse)")
        hlay.addWidget(self.folder_path_input, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(80)
        browse_btn.setToolTip("Browse for a folder (Ctrl+O)")
        browse_btn.clicked.connect(self._choose_folder)
        hlay.addWidget(browse_btn)

        self.phase_one_button = QPushButton("Discover")
        self.phase_one_button.setFixedWidth(100)
        self.phase_one_button.setToolTip("Discover and classify folders (F5)")
        self.phase_one_button.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS["accent2"]}; color: #ffffff;
                border: 1px solid {COLORS["accent"]}; font-weight: bold;
            }}
            QPushButton:hover {{ background: {COLORS["accent"]}; }}
            QPushButton:disabled {{ background: {COLORS["surface3"]}; color: {COLORS["text3"]}; border-color: {COLORS["surface3"]}; }}
        """)
        self.phase_one_button.clicked.connect(self._start_phase_one)
        hlay.addWidget(self.phase_one_button)

        self.phase_two_button = QPushButton("Scan & Organize")
        self.phase_two_button.setFixedWidth(130)
        self.phase_two_button.setEnabled(False)
        self.phase_two_button.setToolTip("Scan files and apply rules (F6)")
        self.phase_two_button.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS["green"]}; color: #000000;
                border: 1px solid {COLORS["green"]}; font-weight: bold;
            }}
            QPushButton:hover {{ background: #47cc5a; }}
            QPushButton:disabled {{ background: {COLORS["surface3"]}; color: {COLORS["text3"]}; border-color: {COLORS["surface3"]}; }}
        """)
        self.phase_two_button.clicked.connect(self._start_phase_two)
        hlay.addWidget(self.phase_two_button)

        self.export_button = QPushButton("Export")
        self.export_button.setFixedWidth(80)
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("Export scan manifest to CSV (Ctrl+E)")
        self.export_button.clicked.connect(self._export_manifest)
        hlay.addWidget(self.export_button)

        parent_layout.addWidget(header)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(f"""
            QMenuBar {{
                background: {COLORS["surface"]}; color: {COLORS["text"]};
                border-bottom: 1px solid {COLORS["border"]};
            }}
            QMenuBar::item:selected {{ background: {COLORS["surface3"]}; }}
            QMenu {{
                background: {COLORS["surface"]}; color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
            }}
            QMenu::item:selected {{ background: {COLORS["accent2"]}; }}
        """)

        # FILE MENU.
        file_menu = menu_bar.addMenu("&File")
        new_profile_action = QAction("&New Profile", self)
        new_profile_action.setShortcut(QKeySequence("Ctrl+N"))
        new_profile_action.setToolTip("Create a new scan profile")
        new_profile_action.triggered.connect(self.home_page._create_new_profile)
        file_menu.addAction(new_profile_action)

        open_folder_action = QAction("&Open Folder...", self)
        open_folder_action.setShortcut(QKeySequence("Ctrl+O"))
        open_folder_action.setToolTip("Browse for a folder to scan")
        open_folder_action.triggered.connect(self._choose_folder)
        file_menu.addAction(open_folder_action)

        file_menu.addSeparator()

        export_action = QAction("&Export CSV...", self)
        export_action.setShortcut(QKeySequence("Ctrl+E"))
        export_action.setToolTip("Export scan results to CSV")
        export_action.triggered.connect(self._export_manifest)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # VIEW MENU.
        view_menu = menu_bar.addMenu("&View")
        page_shortcuts = ["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6"]
        page_names = ["&Home", "&Folders", "&Results", "&Actions", "&Rules", "&Log"]
        for i, (name, shortcut) in enumerate(zip(page_names, page_shortcuts)):
            action = QAction(name, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda checked, idx=i: self._switch_page(idx))
            view_menu.addAction(action)

        # ACTIONS MENU.
        actions_menu = menu_bar.addMenu("&Actions")
        discover_action = QAction("&Discover Folders", self)
        discover_action.setShortcut(QKeySequence("F5"))
        discover_action.triggered.connect(self._start_phase_one)
        actions_menu.addAction(discover_action)

        scan_action = QAction("&Scan & Organize", self)
        scan_action.setShortcut(QKeySequence("F6"))
        scan_action.triggered.connect(self._start_phase_two)
        actions_menu.addAction(scan_action)

        actions_menu.addSeparator()

        execute_action = QAction("&Execute Approved", self)
        execute_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        execute_action.triggered.connect(self.actions_page._execute_batch)
        actions_menu.addAction(execute_action)

        undo_action = QAction("&Undo Last Batch", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        undo_action.triggered.connect(self.actions_page._undo_last_batch)
        actions_menu.addAction(undo_action)

        # HELP MENU.
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About OpenCoeus", self)
        about_action.setShortcut(QKeySequence("F1"))
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    # ---- PAGE NAVIGATION ---- #
    def _switch_page(self, index: int) -> None:
        if index < 0 or index >= len(self._pages):
            return
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        if index < len(self._nav_buttons):
            self._nav_buttons[index].setChecked(True)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            self.folder_path_input.setText(folder)

    # ---- LOG ---- #
    def _on_log_message(self, msg: str) -> None:
        self._log_buffer.append(msg)
        if not self._log_timer.isActive():
            self._log_timer.start()

    def _flush_log(self) -> None:
        if self._log_buffer:
            self.log_page.append_message("\n".join(self._log_buffer))
            self._log_buffer.clear()
        self._log_timer.stop()

    # ---- PHASE ONE ---- #
    def _start_phase_one(self) -> None:
        folder = Path(self.folder_path_input.text())
        if not folder.is_dir():
            QMessageBox.warning(self, "OpenCoeus", "Select a readable folder first.")
            return
        self._cleanup_workers()
        self.log_page.clear_log()
        self.results_page.fill_results(ScanResult(rows=[], errors=[], classifications=[]))
        self.excluded_folders.clear()
        self.proposed_matches.clear()
        self.phase_one_button.setEnabled(False)
        self.phase_two_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.progress_bar.show()
        self.status_bar.showMessage("Discovering folders...")
        profile = self.current_profile or ProfileConfig()
        self.phase_one_worker = PhaseOneWorker(folder, profile)
        self.phase_one_worker.message.connect(self._on_log_message)
        self.phase_one_worker.finished_tree.connect(self._phase_one_done)
        self.phase_one_worker.failed.connect(self._scan_failed)
        self.phase_one_worker.start()

    def _phase_one_done(self, scan_result: ScanResult, tree_root: FolderNode) -> None:
        self.scan_result = scan_result
        self.folder_tree_root = tree_root
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.folders_page.fill_tree(tree_root)
        n = len(scan_result.classifications)
        ex = len(self.excluded_folders)
        self.status_bar.showMessage(f"Phase 1 complete — {n} folders classified, {ex} excluded")
        self._on_log_message(f"<b>Phase 1:</b> {n} folders classified, {ex} excluded automatically.")
        self.home_page.update_stats(folders=n, files="—", duplicates="—", actions="—")
        self._switch_page(1)

    def _scan_failed(self, msg: str) -> None:
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self.status_bar.showMessage("Scan failed")
        logger.error("Scan failed: %s", msg)
        QMessageBox.critical(self, "Scan failed", msg)

    # ---- PHASE TWO ---- #
    def _start_phase_two(self) -> None:
        folder = Path(self.folder_path_input.text())
        if not folder.is_dir():
            return
        self._cleanup_workers()
        self.phase_two_button.setEnabled(False)
        self.phase_one_button.setEnabled(False)
        self.progress_bar.show()
        self.status_bar.showMessage("Scanning files and applying rules...")
        profile = self.current_profile or ProfileConfig()
        self.phase_two_worker = PhaseTwoWorker(folder, self.excluded_folders, self.active_rules, profile)
        self.phase_two_worker.message.connect(self._on_log_message)
        self.phase_two_worker.finished_scan.connect(self._phase_two_done)
        self.phase_two_worker.failed.connect(self._scan_failed)
        self.phase_two_worker.start()

    def _phase_two_done(self, scan_result: ScanResult, matches: list[RuleMatch]) -> None:
        self.scan_result = scan_result
        self.proposed_matches = list(matches)
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.export_button.setEnabled(True)

        # PERSIST PROPOSED ACTIONS TO DATABASE.
        if self.current_profile is None or self.current_profile.profile_id is None:
            self.current_profile = create_profile("default")
        profile_id = self.current_profile.profile_id
        actions_data = [
            {"original_path": m.original_path, "proposed_path": m.proposed_path,
             "action_type": m.action_type, "rule_id": m.rule_id, "reason": m.reason}
            for m in matches
        ]
        self.store.save_proposed_actions(profile_id, actions_data)
        saved_actions = self.store.get_proposed_actions(profile_id)
        self._action_id_map = {a.original_path: a.id for a in saved_actions}

        self.results_page.fill_results(scan_result)
        self.results_page.show_errors(scan_result.errors)
        self.actions_page.fill_actions(matches, self._action_id_map)
        self._switch_page(2)

        dup = scan_result.duplicate_count
        self.home_page.update_stats(
            folders=len(scan_result.classifications) if hasattr(scan_result, 'classifications') else "—",
            files=len(scan_result.rows),
            duplicates=dup,
            actions=len(matches),
        )
        self.status_bar.showMessage(
            f"Phase 2 complete — {len(scan_result.rows)} files, {dup} duplicates, {len(matches)} actions"
        )
        self._on_log_message(
            f"<b>Phase 2:</b> {len(scan_result.rows)} files, {dup} duplicates, {len(matches)} actions proposed."
        )

    # ---- EXPORT ---- #
    def _export_manifest(self) -> None:
        if not self.scan_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save manifest", "opencoeus-manifest.csv", "CSV files (*.csv)")
        if path:
            self._on_log_message(f"Exporting manifest to {path}...")
            self.export_worker = ExportWorker(self.scan_result, Path(path))
            self.export_worker.finished_export.connect(
                lambda p: self._on_log_message(f"<b>Manifest saved:</b> {p}")
            )
            self.export_worker.start()

    # ---- EXECUTE APPROVED ACTIONS ---- #
    def _execute_approved(self) -> None:
        if self.prepare_worker and self.prepare_worker.isRunning():
            return
        if self.execution_worker and self.execution_worker.isRunning():
            return
        if self.current_profile is None or self.current_profile.profile_id is None:
            self.current_profile = create_profile("default")
        profile_id = self.current_profile.profile_id
        approved_count = sum(
            1 for r in range(self.actions_page.actions_table.rowCount())
            if self.actions_page.actions_table.item(r, 0)
            and self.actions_page.actions_table.item(r, 0).text().isdigit()
        )
        if approved_count == 0:
            QMessageBox.information(self, "Execute", "No actions to execute.")
            return
        confirm = QMessageBox.question(
            self, "Execute Actions",
            f"Execute {approved_count} approved file moves?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.progress_bar.show()
        self.status_bar.showMessage("Preparing execution...")
        self._cleanup_workers()
        self.prepare_worker = PrepareWorker(self.store, profile_id, f"{approved_count} file moves from UI")
        self.prepare_worker.finished_preparation.connect(self._on_preparation_done)
        self.prepare_worker.failed.connect(self._on_preparation_failed)
        self.prepare_worker.start()

    def _on_preparation_done(self, batch_id: int, count: int) -> None:
        self.prepare_worker = None
        if batch_id == 0:
            self.progress_bar.hide()
            QMessageBox.warning(self, "Execute", "No actions to execute.")
            return
        self.status_bar.showMessage(f"Executing batch {batch_id}...")
        self.execution_worker = ExecutionWorker(batch_id, self.store)
        self.execution_worker.message.connect(self._on_log_message)
        self.execution_worker.finished_execution.connect(self._on_execution_done)
        self.execution_worker.start()

    def _on_preparation_failed(self, msg: str) -> None:
        self.prepare_worker = None
        self.progress_bar.hide()
        self._on_log_message(f"Preparation failed: {msg}")
        QMessageBox.critical(self, "Execution", f"Preparation failed:\n{msg}")

    def _on_execution_done(self, result) -> None:
        self.progress_bar.hide()
        self.execution_worker = None
        self.actions_page.refresh_actions_count()
        self.actions_page.refresh_batch_history()
        msg = f"Execution complete: {result.completed} completed, {result.failed} failed."
        self.status_bar.showMessage(msg, 5000)
        self._on_log_message(f"<b>{msg}</b>")
        if result.errors:
            for error in result.errors:
                self._on_log_message(f"  ERROR: {error}")
        if result.failed > 0:
            QMessageBox.warning(self, "Execution", f"{result.failed} files failed to move.\nCheck the log for details.")
        else:
            QMessageBox.information(self, "Execution", f"Successfully moved {result.completed} files.")

    # ---- UNDO LAST BATCH ---- #
    def _undo_last_batch(self) -> None:
        if self.undo_worker and self.undo_worker.isRunning():
            return
        profile_id = self.current_profile.profile_id if self.current_profile and self.current_profile.profile_id else None
        batches = self.store.get_undoable_batches(profile_id)
        if not batches:
            QMessageBox.information(self, "Undo", "No completed batches to undo.")
            return
        batch = batches[0]
        from ..models import EntryStatus
        entry_count = len(self.store.get_entries_by_batch(batch.id, status=EntryStatus.COMPLETED))
        confirm = QMessageBox.question(
            self, "Undo Batch",
            f"Undo batch from {batch.created_at}?\n{entry_count} files will be moved back.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._cleanup_workers()
        self.progress_bar.show()
        self.status_bar.showMessage(f"Undoing batch {batch.id}...")
        self.undo_worker = UndoWorker(batch.id, self.store)
        self.undo_worker.message.connect(self._on_log_message)
        self.undo_worker.finished_undo.connect(self._on_undo_done)
        self.undo_worker.start()

    def _on_undo_done(self, errors: list) -> None:
        self.progress_bar.hide()
        self.undo_worker = None
        self.actions_page.refresh_actions_count()
        self.actions_page.refresh_batch_history()
        if errors:
            for error in errors:
                self._on_log_message(f"  WARNING: {error}")
            QMessageBox.warning(self, "Undo", f"Undo completed with {len(errors)} warnings.")
        else:
            self.status_bar.showMessage("Undo complete.", 5000)
            QMessageBox.information(self, "Undo", "Batch undone. Files restored.")

    # ---- THREAD CLEANUP ---- #
    def _cleanup_workers(self) -> None:
        for worker in (self.phase_one_worker, self.phase_two_worker,
                       self.execution_worker, self.prepare_worker,
                       self.undo_worker, self.export_worker):
            if worker is None:
                continue
            worker.blockSignals(True)
            if worker.isRunning():
                worker.quit()
            worker.wait(8000)
        self.phase_one_worker = None
        self.phase_two_worker = None
        self.execution_worker = None
        self.prepare_worker = None
        self.undo_worker = None
        self.export_worker = None

    def closeEvent(self, event) -> None:
        self._cleanup_workers()
        event.accept()

    # ---- PROFILES ---- #
    def _load_profiles(self) -> None:
        self.home_page.load_profiles(self.store)

    # ---- CRASH RECOVERY ---- #
    def _recover_crashed_batches(self) -> None:
        from ..executor import recover_crashed_batches
        try:
            recovered = recover_crashed_batches(self.store)
            if recovered > 0:
                logger.info("Recovered %d crashed batches on startup", recovered)
                self._on_log_message(f"<b>Recovery:</b> {recovered} interrupted batch(es) restored.")
                QMessageBox.information(
                    self, "Recovery",
                    f"Restored {recovered} interrupted batch(es) from a previous session.\n"
                    "Files have been moved back to their original locations."
                )
        except Exception as exc:
            logger.error("Crash recovery failed: %s", exc)
