from __future__ import annotations

import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS
from ...engine import ScanResult
from .common import (
    CardTable, make_container, section_title, section_sub,
    status_badge, truncate_path, fmt_size,
)

# COLUMN WIDTHS FOR RESULTS TABLE: [Name, Path, Size, Modified, Status, Hash, Group].
_RESULTS_COL_WIDTHS = [180, 250, 80, 120, 110, 100, 60]


class ResultsPage(QWidget):
    """RESULTS PAGE WITH FILTERING AND DUPLICATE GROUP VIEW."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = None
        self._raw_results: ScanResult | None = None

        # ROOT LAYOUT
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        root.addWidget(section_title("Scan Results"))
        root.addWidget(section_sub("Files discovered during the scan phase."))

        # FILTER BAR
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            "All Files",
            "Duplicates Only",
            "Unique Files",
            "Duplicate Groups",
        ])
        self.filter_combo.currentIndexChanged.connect(self._filter_results)
        filter_bar.addWidget(self.filter_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name or path...")
        self.search_input.textChanged.connect(self._filter_results)
        filter_bar.addWidget(self.search_input)

        root.addLayout(filter_bar)

        # RESULTS TABLE (CARD-BASED).
        self.results_table = CardTable(
            ["Name", "Path", "Size", "Modified", "Status", "Hash", "Group"],
            column_widths=_RESULTS_COL_WIDTHS,
        )
        self.results_table.row_double_clicked.connect(self._on_result_double_clicked)
        root.addWidget(make_container(self.results_table))

        # ERROR SECTION (HIDDEN BY DEFAULT)
        self.error_section = QTextEdit()
        self.error_section.setReadOnly(True)
        self.error_section.setMaximumHeight(120)
        self.error_section.setStyleSheet(
            f"background: {COLORS.get('surface', '#2b2b2b')}; "
            f"color: {COLORS.get('red', '#f87171')}; "
            "border-radius: 8px; padding: 8px; font-family: monospace;"
        )
        self.error_section.hide()
        root.addWidget(self.error_section)

    # MAIN WINDOW REFERENCE

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # FILL RESULTS

    def fill_results(self, result: ScanResult):
        """POPULATE RESULTS TABLE WITH COLOR-CODED STATUS."""
        self._raw_results = result
        self.results_table.clear()

        for entry in result.rows:
            name = entry.suggested_title or os.path.basename(entry.path)
            self._add_result_row(
                name, entry.path, entry.size, entry.modified_at,
                entry.status, entry.sha256, entry.duplicate_of,
            )

    def _add_result_row(self, name, path, size, modified, status, file_hash, group):
        """ADD A SINGLE ROW TO THE RESULTS TABLE."""
        if status == "duplicate":
            badge = status_badge(status.upper(), COLORS['red'], COLORS.get('red_bg', '#3b1518'))
        elif status == "unique":
            badge = status_badge(status.upper(), COLORS['green'], COLORS.get('green_bg', '#14302a'))
        elif status == "excluded":
            badge = status_badge(status.upper(), COLORS['text3'], COLORS.get('surface3', '#252642'))
        else:
            badge = status_badge(status.upper(), COLORS['text'], COLORS.get('surface2', '#1f2038'))

        self.results_table.addRow(
            widgets=[
                (name, None),
                (truncate_path(path), None),
                (fmt_size(size), None),
                (str(modified) if modified else "—", None),
                ("", badge),
                (file_hash[:12] if file_hash else "", None),
                (str(group) if group else "", None),
            ],
            tooltips=[
                name, path, "", "", "", file_hash or "", "",
            ],
        )

    # ERROR DISPLAY

    def show_errors(self, errors: list[str]):
        """SHOW/HIDE ERROR SECTION."""
        if not errors:
            self.error_section.hide()
            return
        self.error_section.show()
        self.error_section.setPlainText("\n".join(errors))

    # FILTERING

    def _filter_results(self):
        """FILTER BY COMBO SELECTION AND SEARCH TEXT."""
        if self._raw_results is None:
            return

        filter_text = self.filter_combo.currentText()
        search_text = self.search_input.text().strip().lower()

        if filter_text == "Duplicate Groups":
            self._show_duplicate_groups(search_text)
            return

        self.results_table.clear()

        for entry in self._raw_results.rows:
            name = entry.suggested_title or os.path.basename(entry.path)

            # APPLY FILTER.
            if filter_text == "Duplicates Only" and entry.status != "duplicate":
                continue
            if filter_text == "Unique Files" and entry.status != "unique":
                continue

            # APPLY SEARCH.
            if search_text and search_text not in name.lower() and search_text not in entry.path.lower():
                continue

            self._add_result_row(
                name, entry.path, entry.size, entry.modified_at,
                entry.status, entry.sha256, entry.duplicate_of,
            )

    def _show_duplicate_groups(self, search_text: str):
        """GROUP DUPLICATES BY ORIGINAL FILE."""
        if self._raw_results is None:
            return

        self.results_table.clear()

        # BUILD GROUPS BY HASH.
        groups: dict[str, list] = {}
        for entry in self._raw_results.rows:
            if entry.status != "duplicate":
                continue
            h = entry.sha256
            if not h:
                continue
            groups.setdefault(h, []).append(entry)

        for h, entries in groups.items():
            original = entries[0] if entries else None
            if original is None:
                continue
            name = original.suggested_title or os.path.basename(original.path)
            dup_count = len(entries) - 1

            # APPLY SEARCH.
            if search_text and search_text not in name.lower() and search_text not in original.path.lower():
                continue

            self._add_result_row(
                f"{name} (+{dup_count} copies)",
                original.path, original.size, original.modified_at,
                f"{dup_count} duplicates", original.sha256, original.duplicate_of,
            )

    # DOUBLE CLICK TO OPEN FILE

    def _on_result_double_clicked(self, row: int):
        """OPEN FILE IN DEFAULT APPLICATION ON DOUBLE-CLICK."""
        path_lbl = self.results_table.item(row, 1)
        if path_lbl is None:
            return
        full_path = path_lbl.toolTip() or path_lbl.text()
        if not full_path:
            return
        if not os.path.isfile(full_path):
            QMessageBox.warning(
                self,
                "File Not Found",
                f"The file no longer exists:\n{full_path}",
            )
            return
        try:
            if sys.platform == "win32":
                os.startfile(full_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", full_path])
            else:
                subprocess.Popen(["xdg-open", full_path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{e}")
