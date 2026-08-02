from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from ..theme import THEME


class PreviewDialog(QDialog):
    def __init__(self, title: str, tree_data: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 450)
        self.setStyleSheet(f"QDialog {{ background-color: {THEME.bg}; }}")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel("Resulting folder structure after organization:")
        header.setStyleSheet(f"color: {THEME.text}; font-size: 13px; padding: 8px;")
        layout.addWidget(header)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Path"])
        tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {THEME.surface}; color: {THEME.text};
                border: 1px solid {THEME.border}; border-radius: 6px;
                font-size: 12px;
            }}
            QTreeWidget::item {{ padding: 4px 8px; }}
        """)
        self._build_tree(tree, tree_data, None)
        tree.expandAll()
        layout.addWidget(tree, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _build_tree(self, tree: QTreeWidget, data: dict, parent: QTreeWidgetItem | None) -> None:
        for key, val in sorted(data.items()):
            item = QTreeWidgetItem(parent or tree)
            item.setText(0, key)
            if isinstance(val, dict):
                self._build_tree(tree, val, item)
