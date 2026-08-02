from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..models.action_table_model import ActionTableModel
from ..models.batch_table_model import BatchTableModel
from ..models.app_state import AppState
from ..theme import THEME
from ..widgets.table_view import TableView
from .common import section_title


class ActionsPage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._action_model = ActionTableModel()
        self._batch_model = BatchTableModel()
        self._action_table = TableView()
        self._batch_table = TableView()
        self._info_label = QLabel()

        self._build_ui()
        self._state.state_changed.connect(self._refresh)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(section_title("Proposed Actions"))

        btn_row = QHBoxLayout()
        self._approve_all_btn = QPushButton("Approve All")
        self._approve_sel_btn = QPushButton("Approve Selected")
        self._reject_sel_btn = QPushButton("Reject Selected")
        self._preview_btn = QPushButton("Preview")
        self._execute_btn = THEME.btn_primary("Execute")
        self._undo_btn = QPushButton("Undo Last")
        for b in [self._approve_all_btn, self._approve_sel_btn, self._reject_sel_btn,
                  self._preview_btn, self._undo_btn]:
            b.clicked.connect(lambda _checked, bb=b: self._handle_btn(bb))
        self._execute_btn.clicked.connect(self._execute)
        btn_row.addWidget(self._approve_all_btn)
        btn_row.addWidget(self._approve_sel_btn)
        btn_row.addWidget(self._reject_sel_btn)
        btn_row.addWidget(self._preview_btn)
        btn_row.addWidget(self._execute_btn)
        btn_row.addWidget(self._undo_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._action_table.setModel(self._action_model)
        layout.addWidget(self._action_table, 3)

        layout.addWidget(section_title("Batch History"))
        self._batch_table.setModel(self._batch_model)
        layout.addWidget(self._batch_table, 2)

        self._info_label.setStyleSheet(f"color: {THEME.text2}; font-size: 12px; padding: 4px;")
        layout.addWidget(self._info_label)

    def _connect_ctrl(self) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow):
            ctrl = w.action_controller
            try:
                ctrl.approval_done.disconnect(self._on_approval_done)
            except TypeError:
                pass
            ctrl.approval_done.connect(self._on_approval_done)

    def _on_approval_done(self, count: int) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow):
            self._action_model.refresh_status(w.store)
        self._info_label.setText(f"{count} action(s) updated")

    def _handle_btn(self, btn: QPushButton) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if not isinstance(w, MainWindow):
            return
        ctrl = w.action_controller
        self._connect_ctrl()
        text = btn.text()
        if text == "Approve All":
            ctrl.approve_all()
            self._info_label.setText("Approving all actions...")
        elif text == "Approve Selected":
            self._toggle_approval(True)
        elif text == "Reject Selected":
            self._toggle_approval(False)
        elif text == "Preview":
            w.show_preview()
        elif text == "Undo Last":
            w.undo_last()

    def _toggle_approval(self, approved: bool) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if not isinstance(w, MainWindow):
            return
        ctrl = w.action_controller
        rows = self._action_table.selected_rows()
        ids = []
        for row in rows:
            a = self._action_model.get_action(row)
            if a:
                ids.append(a.id)
        if not ids:
            return
        label = "approving" if approved else "rejecting"
        self._info_label.setText(f"{label} {len(ids)} action(s)...")
        if approved:
            ctrl.approve_selected(ids)
        else:
            ctrl.reject_selected(ids)

    def _execute(self) -> None:
        from ..main_window import MainWindow
        w = self.window()
        if isinstance(w, MainWindow):
            w.execute_actions()

    def _refresh(self) -> None:
        if self._state.actions:
            self._action_model.load(self._state.actions)
        if self._state.batches:
            self._batch_model.load(self._state.batches)

    def refresh_theme(self) -> None:
        t = THEME
        self._info_label.setStyleSheet(f"color: {t.text2}; font-size: 12px; padding: 4px;")
        self._execute_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t.accent}; color: #fff; border: none;
                border-radius: 6px; padding: 6px 16px;
                font-weight: 600; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {t.accent_hov}; }}
            QPushButton:pressed {{ background-color: {t.accent_dim}; }}
            QPushButton:disabled {{ background-color: {t.surface3}; color: {t.text3}; }}
        """)
