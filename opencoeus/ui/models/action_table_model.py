from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from opencoeus.db.models import ProposedAction


_COLUMNS = ["Status", "Action", "Source", "Target", "Name", "New Name", "Rule"]


class ActionTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actions: list[ProposedAction] = []

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._actions)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._actions):
            return None
        a = self._actions[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                0: "APPROVED" if a.approved else "PENDING",
                1: a.action_type.upper() if a.action_type else "",
                2: a.original_path,
                3: a.proposed_path,
                4: a.original_filename or "",
                5: a.new_filename or "",
                6: str(a.rule_id) if a.rule_id else "",
            }.get(col, "")
        if role == Qt.ItemDataRole.UserRole:
            return a
        return None

    def load(self, actions: list[ProposedAction]) -> None:
        self.beginResetModel()
        self._actions = list(actions)
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._actions.clear()
        self.endResetModel()

    def get_action(self, row: int) -> ProposedAction | None:
        if 0 <= row < len(self._actions):
            return self._actions[row]
        return None

    def refresh_status(self, store) -> None:
        if not self._actions:
            return
        ids = [a.id for a in self._actions]
        fresh_map = {f.id: f.approved for f in store.get_actions_by_ids(ids)}
        changed = False
        for a in self._actions:
            if a.id in fresh_map and a.approved != fresh_map[a.id]:
                a.approved = fresh_map[a.id]
                changed = True
        if changed:
            self.layoutChanged.emit()
