from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from opencoeus.db.models import TransactionBatch


_COLUMNS = ["ID", "Description", "Status", "Date"]


class BatchTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._batches: list[TransactionBatch] = []

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._batches)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._batches):
            return None
        b = self._batches[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                0: str(b.id),
                1: b.description or "",
                2: b.status if b.status else "",
                3: str(b.created_at)[:19] if b.created_at else "",
            }.get(col, "")
        if role == Qt.ItemDataRole.UserRole:
            return b
        return None

    def load(self, batches: list[TransactionBatch]) -> None:
        self.beginResetModel()
        self._batches = list(batches)
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._batches.clear()
        self.endResetModel()
