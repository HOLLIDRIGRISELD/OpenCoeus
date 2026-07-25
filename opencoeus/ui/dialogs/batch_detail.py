from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...database import AuditStore
from ..theme import COLORS, dialog_stylesheet, text_button_qss


class BatchDetailDialog(QDialog):
    def __init__(self, store: AuditStore, batch_id: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Batch #{batch_id} Details")
        self.setMinimumSize(700, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # BATCH INFO HEADER
        batch = store.get_batch(batch_id)
        if batch:
            info_lines = [
                f"Description: {batch.description or '(none)'}",
                f"Status: {batch.status}",
                f"Created: {batch.created_at}",
            ]
            info_text = "\n".join(info_lines)
        else:
            info_text = f"Batch #{batch_id} (not found)"

        info_label = QLabel(info_text)
        info_label.setStyleSheet(f"color: {COLORS['text2']}; font-size: 12px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # ENTRIES TABLE
        entries = store.get_entries_by_batch(batch_id)
        table = QTableWidget(len(entries), 5)
        table.setHorizontalHeaderLabels(["ID", "Status", "Source Path", "Destination Path", "Error"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)

        for row_idx, entry in enumerate(entries):
            table.setItem(row_idx, 0, QTableWidgetItem(str(entry.id)))
            table.setItem(row_idx, 1, QTableWidgetItem(entry.status))
            table.setItem(row_idx, 2, QTableWidgetItem(entry.source_path))
            table.setItem(row_idx, 3, QTableWidgetItem(entry.destination_path))
            table.setItem(row_idx, 4, QTableWidgetItem(entry.error_message or ""))

        table.resizeColumnsToContents()
        layout.addWidget(table)

        # CLOSE BUTTON
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(90)
        close_btn.setStyleSheet(text_button_qss())
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(dialog_stylesheet())
