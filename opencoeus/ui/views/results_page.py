from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..models.app_state import AppState
from ..models.scan_table_model import ScanTableModel
from ..theme import THEME
from ..widgets.table_view import TableView
from .common import section_title


class ResultsPage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._model = ScanTableModel()
        self._table = TableView()
        self._search_edit = QLineEdit()
        self._count_label = QLabel()

        self._build_ui()
        self._state.state_changed.connect(self._refresh)
        self._search_edit.textChanged.connect(self._filter)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(section_title("Scan Results"))

        top = QHBoxLayout()
        self._search_edit.setPlaceholderText("Search files...")
        top.addWidget(self._search_edit, 1)
        export_btn = QPushButton("Export CSV")
        export_btn.clicked.connect(self._export)
        top.addWidget(export_btn)
        layout.addLayout(top)

        self._table.setModel(self._model)
        layout.addWidget(self._table, 1)

        self._count_label.setStyleSheet(f"color: {THEME.text2}; font-size: 12px;")
        layout.addWidget(self._count_label)

    def _refresh(self) -> None:
        if self._state.scan_result:
            self._model.load(self._state.scan_result)
            self._update_count()

    def _filter(self, text: str) -> None:
        if not text or not self._state.scan_result:
            self._model.set_filter(None)
            return
        indices = [
            i for i, r in enumerate(self._state.scan_result.rows)
            if text.lower() in r.path.lower()
        ]
        self._model.set_filter(indices)
        self._update_count()

    def _update_count(self) -> None:
        self._count_label.setText(f"{self._model.rowCount()} file(s)")

    def refresh_theme(self) -> None:
        self._count_label.setStyleSheet(f"color: {THEME.text2}; font-size: 12px;")

    def _export(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if path and self._state.scan_result:
            with open(path, "w") as f:
                f.write("Path,Size,Modified,Status,Topic,Author,Confidence\n")
                for r in self._state.scan_result.rows:
                    f.write(f"{r.path},{r.size},{r.modified_at},{r.status},"
                            f"{r.nlp_topic},{r.nlp_author},{r.nlp_confidence}\n")
