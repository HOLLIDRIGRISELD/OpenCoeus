from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from opencoeus.db.models import OrganizationRule


_COLUMNS = ["ID", "Name", "Type", "Action", "Template", "Enabled", "Priority"]


class RuleTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rules: list[OrganizationRule | dict] = []

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rules)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rules):
            return None
        r = self._rules[index.row()]
        is_dict = isinstance(r, dict)
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                0: str(r.get("id", "") if is_dict else (r.id or "")),
                1: r.get("name", "") if is_dict else (r.name or ""),
                2: r.get("rule_type", "") if is_dict else (r.rule_type or ""),
                3: r.get("action_type", "") if is_dict else (r.action_type or ""),
                4: r.get("destination_template", "") if is_dict else (r.destination_template or ""),
                5: "Yes" if (r.get("enabled", False) if is_dict else r.enabled) else "No",
                6: str(r.get("priority", 0) if is_dict else (r.priority or 0)),
            }.get(col, "")
        if role == Qt.ItemDataRole.UserRole:
            return r
        return None

    def load(self, rules: list[OrganizationRule | dict]) -> None:
        self.beginResetModel()
        self._rules = list(rules)
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._rules.clear()
        self.endResetModel()

    def get_rule(self, row: int) -> OrganizationRule | dict | None:
        if 0 <= row < len(self._rules):
            return self._rules[row]
        return None
