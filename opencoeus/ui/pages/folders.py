from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHeaderView,
    QLabel,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS
from ...folder_tree import FolderNode, build_node_index, set_folder_exclusion
from .common import make_container, section_title, section_sub


class FoldersPage(QWidget):
    """FOLDER TREE PAGE WITH TRI-STATE CHECKBOXES."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._excluded: set[str] = set()
        self._node_index: dict[str, FolderNode] = {}

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(section_title("Folder Tree"))
        root.addWidget(section_sub("Uncheck folders to exclude them from scanning."))

        # TREE WIDGET
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder", "Files", "Size", "Type"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.setColumnWidth(0, 320)
        self.tree.setRootIsDecorated(True)
        self.tree.itemChanged.connect(self._on_folder_toggled)

        root.addWidget(make_container(self.tree))

    # ── MAIN WINDOW REFERENCE ──────────────────────────────────────────────

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # ── TREE POPULATION ────────────────────────────────────────────────────

    def fill_tree(self, root_node: FolderNode):
        """POPULATE QTREEWIDGET FROM A FOLDERNODE TREE."""
        self.tree.blockSignals(True)
        self.tree.clear()
        self._excluded.clear()
        self._node_index = build_node_index(root_node)

        for child in root_node.children:
            self._add_tree_children(self.tree.invisibleRootItem(), child)
        self.tree.blockSignals(False)

    def _add_tree_children(self, parent_item: QTreeWidgetItem, node: FolderNode):
        """RECURSIVELY ADD FOLDERNODES AS TREE ITEMS."""
        item = QTreeWidgetItem(parent_item)
        item.setText(0, node.name)
        item.setText(1, str(node.file_count) if node.file_count else "")
        item.setText(2, str(node.total_size) if node.total_size else "")
        item.setText(3, node.classification or "")
        item.setData(0, Qt.ItemDataRole.UserRole, node.path)

        # CLASSIFICATION COLOR
        class_color = COLORS.get("text", "#ffffff")
        if node.classification == "code":
            class_color = "#61afef"
        elif node.classification == "data":
            class_color = "#e5c07b"
        elif node.classification == "document":
            class_color = "#98c379"
        elif node.classification == "media":
            class_color = "#c678dd"
        elif node.classification == "archive":
            class_color = "#e06c75"
        item.setForeground(3, QColor(class_color))

        # TRI-STATE CHECKBOX
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        if node.excluded:
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self._excluded.add(node.path)
        else:
            item.setCheckState(0, Qt.CheckState.Checked)

        # RECURSE CHILDREN
        for child in node.children:
            self._add_tree_children(item, child)

    # ── CHECKBOX HANDLING ──────────────────────────────────────────────────

    def _on_folder_toggled(self, item: QTreeWidgetItem, col: int):
        """HANDLE CHECKBOX TOGGLING WITH PARENT/CHILD PROPAGATION."""
        if col != 0:
            return

        self.tree.blockSignals(True)
        state = item.checkState(0)

        # PROPAGATE TO CHILDREN
        self._set_children_check_state(item, state)

        # PROPAGATE TO PARENT
        self._update_parent_check_state(item)

        # UPDATE EXCLUDED SET
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            if state == Qt.CheckState.Unchecked:
                self._excluded.add(path)
            else:
                self._excluded.discard(path)

            # PERSIST TO DATABASE
            if self._main is not None and hasattr(self._main, "store") and self._main.store is not None:
                node = self._node_index.get(path)
                if node is not None:
                    excluded = state == Qt.CheckState.Unchecked
                    set_folder_exclusion(self._main.store, path, excluded)

        self.tree.blockSignals(False)

    def _set_children_check_state(self, parent: QTreeWidgetItem, state: Qt.CheckState):
        """RECURSIVELY SET CHILDREN CHECK STATE."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            path = child.data(0, Qt.ItemDataRole.UserRole)
            if path:
                if state == Qt.CheckState.Unchecked:
                    self._excluded.add(path)
                else:
                    self._excluded.discard(path)
            self._set_children_check_state(child, state)

    def _update_parent_check_state(self, item: QTreeWidgetItem):
        """RECURSIVELY UPDATE PARENT TRI-STATE CHECKBOX."""
        parent = item.parent()
        if parent is None:
            return

        checked = 0
        unchecked = 0
        for i in range(parent.childCount()):
            child = parent.child(i)
            cs = child.checkState(0)
            if cs == Qt.CheckState.Checked:
                checked += 1
            elif cs == Qt.CheckState.Unchecked:
                unchecked += 1

        if unchecked == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Unchecked)
        elif checked == parent.childCount():
            parent.setCheckState(0, Qt.CheckState.Checked)
        else:
            parent.setCheckState(0, Qt.CheckState.PartiallyChecked)

        path = parent.data(0, Qt.ItemDataRole.UserRole)
        if path:
            if parent.checkState(0) == Qt.CheckState.Unchecked:
                self._excluded.add(path)
            else:
                self._excluded.discard(path)

        self._update_parent_check_state(parent)

    # ── PUBLIC ACCESSORS ───────────────────────────────────────────────────

    def get_excluded_folders(self) -> set[str]:
        """RETURN CURRENT EXCLUDED FOLDER SET."""
        return set(self._excluded)
