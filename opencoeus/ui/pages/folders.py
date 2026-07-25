from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS, accent_button_qss, text_button_qss
from ...folder_tree import FolderNode, build_node_index, set_folder_exclusion
from .common import CardTree, make_container, section_title, section_sub


# COLUMN WIDTHS: [Arrow(30), CB(30), Name, Files, Size, Classification, Status].
_FOLDER_COL_WIDTHS = [30, 30, 250, 80, 80, 100, 100]


class FoldersPage(QWidget):
    """FOLDER TREE PAGE WITH CARD-BASED TREE AND TRI-STATE CHECKBOXES."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._excluded: set[str] = set()
        self._node_index: dict[str, FolderNode] = {}

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # TITLE ROW
        title_row = QHBoxLayout()
        title_row.addWidget(section_title("Folder Tree"))
        title_row.addStretch()
        self.count_label = QLabel("0 folders")
        self.count_label.setStyleSheet(
            f"color: {COLORS.get('text2', '#7f848e')}; font-size: 12px;"
        )
        title_row.addWidget(self.count_label)
        root.addLayout(title_row)

        root.addWidget(section_sub("Uncheck folders to exclude them from scanning."))

        # TOOLBAR
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        btn_expand = QPushButton("Expand All")
        btn_expand.setToolTip("Expand all folders")
        btn_expand.clicked.connect(self._expand_all)
        btn_expand.setStyleSheet(accent_button_qss())
        toolbar.addWidget(btn_expand)

        btn_collapse = QPushButton("Collapse All")
        btn_collapse.setToolTip("Collapse all folders")
        btn_collapse.clicked.connect(self._collapse_all)
        btn_collapse.setStyleSheet(text_button_qss())
        toolbar.addWidget(btn_collapse)

        toolbar.addStretch()
        root.addLayout(toolbar)

        # CARD TREE
        self.card_tree = CardTree(
            ["", "", "Folder", "Files", "Size", "Type", "Status"],
            column_widths=_FOLDER_COL_WIDTHS,
        )
        self.card_tree.check_changed.connect(self._on_folder_toggled)
        root.addWidget(make_container(self.card_tree))

    # MAIN WINDOW REFERENCE

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # TREE POPULATION

    def fill_tree(self, root_node: FolderNode):
        """POPULATE CARDTREE FROM A FOLDERNODE TREE."""
        self.card_tree.clear()
        self._excluded.clear()
        self._node_index = build_node_index(root_node)

        # ADD ROOT NODE ITSELF.
        self.card_tree.addNode(
            name=root_node.name,
            path=root_node.path.as_posix(),
            depth=0,
            file_count=root_node.file_count,
            total_size=root_node.total_size,
            classification=root_node.classification,
            excluded=root_node.excluded,
            has_children=len(root_node.children) > 0,
        )

        # ADD ALL DESCENDANTS IN PREORDER.
        self._add_tree_children(root_node, depth=1)

        # COMPUTE PARENT/CHILD RELATIONSHIPS AND VISIBILITY.
        self.card_tree.finalizeHierarchy()

        # UPDATE COUNT.
        total = self.card_tree.rowCount()
        self.count_label.setText(f"{total} folders")

    def _add_tree_children(self, node: FolderNode, depth: int):
        """RECURSIVELY ADD CHILD NODES TO THE CARDTREE."""
        for child in node.children:
            self._excluded.add(child.path.as_posix()) if child.excluded else None

            self.card_tree.addNode(
                name=child.name,
                path=child.path.as_posix(),
                depth=depth,
                file_count=child.file_count,
                total_size=child.total_size,
                classification=child.classification,
                excluded=child.excluded,
                has_children=len(child.children) > 0,
            )

            # RECURSE.
            self._add_tree_children(child, depth + 1)

    # EXPAND / COLLAPSE

    def _expand_all(self):
        """EXPAND ALL FOLDERS."""
        self.card_tree.expandAll()

    def _collapse_all(self):
        """COLLAPSE ALL FOLDERS."""
        self.card_tree.collapseAll()

    # CHECKBOX HANDLING

    def _on_folder_toggled(self, row_index: int, checked: bool):
        """HANDLE CHECKBOX TOGGLING WITH PERSISTENCE TO DATABASE."""
        path = self.card_tree.getNodePath(row_index)
        if not path:
            return

        # UPDATE EXCLUDED SET.
        if not checked:
            self._excluded.add(path)
        else:
            self._excluded.discard(path)

        # PERSIST TO DATABASE.
        if self._main is not None and hasattr(self._main, "store") and self._main.store is not None:
            node = self._node_index.get(path)
            if node is not None:
                excluded = not checked
                if self._main.folder_tree_root is not None:
                    set_folder_exclusion(
                        self._main.folder_tree_root, Path(path), excluded,
                        node_index=self._node_index,
                    )

        # REBUILD EXCLUDED SET FROM ALL CHECKBOXES (PROPAGATION AFFECTS CHILDREN).
        self._excluded = self.card_tree.getExcludedPaths()

    # PUBLIC ACCESSORS

    def get_excluded_folders(self) -> set[str]:
        """RETURN CURRENT EXCLUDED FOLDER SET."""
        return set(self._excluded)
