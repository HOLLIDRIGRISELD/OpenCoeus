from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..models.app_state import AppState
from ..theme import THEME
from .common import section_title

_COLUMNS = ["Folder", "Classification", "Action", "Reason"]


class FoldersPage(QWidget):
    def __init__(self, app_state: AppState, parent=None) -> None:
        super().__init__(parent)
        self._state = app_state
        self._populating = False
        self._tree = QTreeWidget()
        self._count_label = QLabel()
        self._build_ui()
        self._state.state_changed.connect(self._on_state_changed)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(section_title("Folders"))
        layout.addWidget(QLabel("Uncheck folders to exclude them from scanning and organization."))

        toolbar = QHBoxLayout()
        expand_btn = QPushButton("Expand All")
        expand_btn.clicked.connect(self._tree.expandAll)
        toolbar.addWidget(expand_btn)
        collapse_btn = QPushButton("Collapse All")
        collapse_btn.clicked.connect(self._tree.collapseAll)
        toolbar.addWidget(collapse_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._tree.setColumnCount(len(_COLUMNS))
        self._tree.setHeaderLabels(_COLUMNS)
        self._tree.setUniformRowHeights(True)
        self._tree.header().setStretchLastSection(True)
        self._tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._tree, 1)

        self._count_label.setStyleSheet(
            f"color: {THEME.text2}; font-size: 12px; background: transparent;"
        )
        layout.addWidget(self._count_label)

    def _on_state_changed(self, key: str, _value) -> None:
        if key in ("folder_tree_flat", "excluded"):
            self._populate()

    def _populate(self) -> None:
        self._populating = True
        try:
            self._tree.clear()
            excluded = self._state.excluded
            stack: list[tuple[int, QTreeWidgetItem]] = []
            for node in self._state.folder_tree_flat:
                item = QTreeWidgetItem()
                item.setText(0, node.get("name") or node.get("path") or "")
                item.setText(1, node.get("classification") or "")
                item.setText(2, node.get("recommended_action") or "")
                item.setText(3, node.get("reason") or "")
                item.setData(0, Qt.ItemDataRole.UserRole, node.get("path") or "")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    0,
                    Qt.CheckState.Unchecked if node.get("path") in excluded else Qt.CheckState.Checked,
                )
                while stack and stack[-1][0] >= int(node.get("depth") or 0):
                    stack.pop()
                if stack:
                    stack[-1][1].addChild(item)
                else:
                    self._tree.addTopLevelItem(item)
                stack.append((int(node.get("depth") or 0), item))
            total = self._tree.topLevelItemCount() + sum(
                self._count_children(self._tree.topLevelItem(i)) for i in range(self._tree.topLevelItemCount())
            )
            self._count_label.setText(
                f"{total} folders, {len(excluded)} excluded"
            )
        finally:
            self._populating = False

    @staticmethod
    def _count_children(item: QTreeWidgetItem) -> int:
        count = item.childCount()
        for i in range(item.childCount()):
            count += FoldersPage._count_children(item.child(i))
        return count

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._populating or column != 0:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        new = set(self._state.excluded)
        if item.checkState(0) == Qt.CheckState.Unchecked:
            new.add(path)
        else:
            new.discard(path)
        if new != self._state.excluded:
            self._state.excluded = new

    def refresh_theme(self) -> None:
        self._count_label.setStyleSheet(
            f"color: {THEME.text2}; font-size: 12px; background: transparent;"
        )
