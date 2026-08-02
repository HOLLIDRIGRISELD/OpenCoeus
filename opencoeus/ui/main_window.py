from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)
from sqlalchemy import inspect as sa_inspect

from opencoeus.db import AuditStore
from opencoeus.db.models import OrganizationRule
from opencoeus.settings import Settings

from .controllers.action_controller import ActionController
from .controllers.rule_controller import RuleController
from .controllers.scan_controller import ScanController
from .models.app_state import AppState
from .theme import THEME
from .views.actions_page import ActionsPage
from .views.folders_page import FoldersPage
from .views.home_page import HomePage
from .views.log_page import LogPage
from .views.results_page import ResultsPage
from .views.rules_page import RulesPage
from .views.settings_page import SettingsPage
from .widgets.navigation import Sidebar
from .widgets.toast import ToastManager


PAGE_IDS = ["home", "folders", "results", "actions", "rules", "log", "settings"]
PAGE_CLASSES = [HomePage, FoldersPage, ResultsPage, ActionsPage, RulesPage, LogPage, SettingsPage]


class MainWindow(QMainWindow):
    def __init__(self, store: AuditStore) -> None:
        super().__init__()
        self.store = store
        self._state = AppState()
        self._settings = Settings.load()
        self._state.settings = self._settings
        self._toasts = ToastManager(self)

        self._scan_ctrl = ScanController(store, self)
        self._action_ctrl = ActionController(store, self)
        self._rule_ctrl = RuleController(store, self)

        self._pages: list[QWidget] = []
        self._stack = QStackedWidget()
        self._sidebar = Sidebar()
        self._status_label = QLabel()

        THEME.set_dark(self._settings.dark_theme)
        self._state.dark = THEME.dark
        self._build_window()
        self._wire_controllers()
        self._load_data()
        self._setup_shortcuts()
        self._recover_crashed_batches()
        self._navigate(0)

    @property
    def action_controller(self) -> ActionController:
        return self._action_ctrl

    @property
    def rule_controller(self) -> RuleController:
        return self._rule_ctrl

    def _build_window(self) -> None:
        self.setWindowTitle("OpenCoeus")
        self.setMinimumSize(960, 540)
        self.resize(1280, 720)
        self.setStyleSheet(THEME.global_stylesheet())

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar.page_changed.connect(self._navigate)
        root.addWidget(self._sidebar)

        for cls in PAGE_CLASSES:
            page = cls(self._state)
            self._stack.addWidget(page)
            self._pages.append(page)
        root.addWidget(self._stack, 1)

        # Status bar
        self._status_label.setStyleSheet(
            f"color: {THEME.text2}; font-size: 11px; background: transparent; padding: 2px;"
        )
        self.statusBar().addWidget(self._status_label)
        self.statusBar().setStyleSheet(
            f"background-color: {THEME.status_bg}; border-top: 1px solid {THEME.border};"
        )

    def _wire_controllers(self) -> None:
        self._scan_ctrl.log_message.connect(self._on_log)
        self._scan_ctrl.scan_done.connect(self._on_scan_done)
        self._scan_ctrl.organize_done.connect(self._on_organize_done)
        self._scan_ctrl.scan_failed.connect(self._on_error)
        self._scan_ctrl.busy_changed.connect(self._on_busy)

        self._action_ctrl.log_message.connect(self._on_log)
        self._action_ctrl.actions_saved.connect(self._on_actions_saved)
        self._action_ctrl.preparation_done.connect(
            lambda bid, cnt: self._on_log(f"Batch #{bid} prepared ({cnt} entries)")
        )
        self._action_ctrl.execution_done.connect(self._on_execution_done)
        self._action_ctrl.undo_done.connect(self._on_undo_done)
        self._action_ctrl.operation_failed.connect(self._on_error)
        self._action_ctrl.busy_changed.connect(self._on_busy)

        self._rule_ctrl.rules_loaded.connect(self._on_rules_loaded)
        self._rule_ctrl.error_occurred.connect(self._on_error)

    @staticmethod
    def _rules_as_dicts(rules: list) -> list[dict]:
        result: list[dict] = []
        for r in rules:
            if isinstance(r, dict):
                result.append(r)
            elif isinstance(r, OrganizationRule):
                result.append({c.key: getattr(r, c.key) for c in sa_inspect(r).mapper.column_attrs})
            else:
                result.append(dict(r))
        return result

    def _load_data(self) -> None:
        rules = self._rule_ctrl.load()
        self._state.rules = self._rules_as_dicts(rules)

    def _setup_shortcuts(self) -> None:
        def act(key: str, slot):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(slot)
            self.addAction(a)

        for index, key in enumerate(["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6", "Ctrl+7"]):
            act(key, lambda idx=index: self._navigate(idx))

    def _navigate(self, index: int) -> None:
        if index < 0 or index >= len(self._pages):
            return
        self._stack.setCurrentWidget(self._pages[index])
        self._sidebar.set_active(index)

    def start_scan(self, folder: Path) -> None:
        self._scan_ctrl.discover_and_scan(folder)
        self._on_log(f"Starting scan: {folder}")

    def execute_actions(self) -> None:
        if self._settings.confirm_execute:
            ret = QMessageBox.question(
                self, "Confirm Execution",
                "This will rename and move files according to approved actions. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        self._action_ctrl.prepare_and_execute()

    def undo_last(self) -> None:
        if self._settings.confirm_undo:
            ret = QMessageBox.question(
                self, "Confirm Undo",
                "Revert the most recent completed batch?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        self._action_ctrl.undo_last()

    def show_preview(self) -> None:
        from .views.preview_dialog import PreviewDialog
        if not self._state.matches:
            QMessageBox.information(self, "Preview", "No actions to preview.")
            return
        tree = self._build_preview_tree(self._state.matches)
        dlg = PreviewDialog("Organization Preview", tree, self)
        dlg.exec()

    def toggle_theme(self) -> None:
        THEME.toggle()
        self._state.dark = THEME.dark
        self._settings.dark_theme = THEME.dark
        self._settings.save()
        self.setStyleSheet(THEME.global_stylesheet())
        self._status_label.setStyleSheet(
            f"color: {THEME.text2}; font-size: 11px; background: transparent; padding: 2px;"
        )
        self.statusBar().setStyleSheet(
            f"background-color: {THEME.status_bg}; border-top: 1px solid {THEME.border};"
        )
        self._sidebar.refresh_theme()
        for page in self._pages:
            refresh = getattr(page, "refresh_theme", None)
            if callable(refresh):
                refresh()
        self._toasts.show("Theme toggled", 2000, THEME.accent)

    def set_organize_after_scan(self, enabled: bool) -> None:
        self._settings.organize_after_scan = enabled
        self._settings.save()

    def set_confirm_execute(self, enabled: bool) -> None:
        self._settings.confirm_execute = enabled
        self._settings.save()

    def set_confirm_undo(self, enabled: bool) -> None:
        self._settings.confirm_undo = enabled
        self._settings.save()

    def _build_preview_tree(self, matches) -> dict:
        root: dict = {}
        for m in matches:
            parts = m.proposed_path.replace("\\", "/").strip("/").split("/")
            current = root
            for p in parts[:-1]:
                current = current.setdefault(p, {})
            current[parts[-1]] = {}
        return root

    def _on_log(self, msg: str) -> None:
        log_page = self._pages[PAGE_IDS.index("log")]
        if isinstance(log_page, LogPage):
            log_page.append(msg)
        self._status_label.setText(msg)

    def _on_scan_done(self, result) -> None:
        try:
            self._state.scan_result = result
            self._state.folder_tree_flat = result.folder_tree_flat
            self._state.excluded = {
                c["folder_path"] for c in result.classifications
                if c.get("recommended_action") == "exclude"
            }
            self._on_log(
                f"Scan complete: {len(result.classifications)} folders classified, "
                f"{len(self._state.excluded)} excluded"
            )

            rules = self._state.rules
            if self._state.folder and rules and self._settings.organize_after_scan:
                self._scan_ctrl.organize(
                    self._state.folder, self._state.excluded, [], rules,
                )
        except Exception as e:
            self._on_error(f"Scan handler error: {e}")

    def _on_organize_done(self, result, matches) -> None:
        try:
            self._state.scan_result = result
            self._state.matches = matches
            self._on_log(f"Organization complete: {len(matches)} actions proposed")

            actions = self._action_ctrl.save_actions(matches)
            self._state.actions = actions
            batches = self._action_ctrl.get_batches()
            self._state.batches = batches
            self._navigate(PAGE_IDS.index("actions"))
            self._toasts.show(f"{len(matches)} actions proposed", 4000, THEME.green)
        except Exception as e:
            self._on_error(f"Organize handler error: {e}")

    def _on_actions_saved(self, actions) -> None:
        self._state.actions = actions

    def _on_execution_done(self, result) -> None:
        success = getattr(result, "completed", 0)
        failed = getattr(result, "failed", 0)
        self._on_log(f"Execution complete: {success} succeeded, {failed} failed")
        batches = self._action_ctrl.get_batches()
        self._state.batches = batches
        self._toasts.show(f"Executed: {success} OK, {failed} failed", 5000,
                          THEME.green if not failed else THEME.red)

    def _on_undo_done(self, errors) -> None:
        if errors:
            self._on_log(f"Undo completed with errors: {errors}")
            self._toasts.show("Undo had errors", 5000, THEME.red)
        else:
            self._on_log("Undo completed successfully")
            self._toasts.show("Undo successful", 3000, THEME.green)
        batches = self._action_ctrl.get_batches()
        self._state.batches = batches

    def _on_rules_loaded(self, rules) -> None:
        self._state.rules = self._rules_as_dicts(rules)

    def _on_error(self, msg: str) -> None:
        self._on_log(f"ERROR: {msg}")
        QMessageBox.critical(self, "Error", msg)

    def _on_busy(self, busy: bool) -> None:
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def _recover_crashed_batches(self) -> None:
        from opencoeus.executor import cleanup_stale_holding_folders, recover_crashed_batches
        try:
            recovered = recover_crashed_batches(self.store)
            swept = cleanup_stale_holding_folders()
            if recovered > 0:
                self._on_log(f"Recovery: {recovered} interrupted batch(es) restored.")
                QMessageBox.information(
                    self, "Recovery",
                    f"Restored {recovered} interrupted batch(es) from a previous session.\n"
                    "Files have been moved back to their original locations.",
                )
            if swept > 0:
                self._on_log(f"Cleanup: removed {swept} empty leftover holding folder(s).")
        except Exception as exc:
            self._on_log(f"Crash recovery failed: {exc}")

    def closeEvent(self, event) -> None:
        self._scan_ctrl.cancel()
        self._action_ctrl.cancel()
        event.accept()
