from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from opencoeus.engine.manifest import ScanResult

from ..views.common import fmt_size


_COLUMNS = ["Name", "Path", "Size", "Modified", "Status", "Destination"]


class ScanTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[list[str]] = []
        self._filtered: list[int] | None = None

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._filtered is not None:
            return len(self._filtered)
        return len(self._rows)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._filtered[index.row()] if self._filtered is not None else index.row()
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._rows[row][col]
        if role == Qt.ItemDataRole.UserRole:
            return self._rows[row]
        return None

    def load(self, result: ScanResult) -> None:
        self.beginResetModel()
        self._rows = []
        for r in result.rows:
            self._rows.append([
                r.path.split("/")[-1] or r.path.split("\\")[-1],
                str(r.path),
                fmt_size(r.size),
                r.modified_at[:10] if r.modified_at else "",
                r.status.upper(),
                r.smart_destination,
            ])
        self._filtered = None
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self._filtered = None
        self.endResetModel()

    def set_filter(self, indices: list[int] | None) -> None:
        self.beginResetModel()
        self._filtered = indices
        self.endResetModel()
