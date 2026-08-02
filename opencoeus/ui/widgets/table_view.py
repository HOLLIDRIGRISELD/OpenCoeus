from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTableView, QWidget


class TableView(QTableView):
    row_double_clicked = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(False)
        self.setShowGrid(True)
        self.setSortingEnabled(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setHighlightSections(False)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.doubleClicked.connect(self._on_double_click)

    def _on_double_click(self, index) -> None:
        self.row_double_clicked.emit(index.row())

    def selected_rows(self) -> list[int]:
        return [idx.row() for idx in self.selectionModel().selectedRows()]
