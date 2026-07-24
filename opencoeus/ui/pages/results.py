from __future__ import annotations

import os
import subprocess
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..theme import COLORS
from ...engine import ScanResult
from .common import make_table, make_container, section_title, section_sub, truncate_path, fmt_size


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

        # RESULTS TABLE
        self.results_table = make_table(
            ["Name", "Path", "Size", "Modified", "Status", "Hash", "Group"],
            stretch_column=1,
        )
        self.results_table.doubleClicked.connect(self._on_result_double_clicked)
        root.addWidget(make_container(self.results_table))

        # ERROR SECTION (HIDDEN BY DEFAULT)
        self.error_section = QTextEdit()
        self.error_section.setReadOnly(True)
        self.error_section.setMaximumHeight(120)
        self.error_section.setStyleSheet(
            f"background: {COLORS.get('surface', '#2b2b2b')}; "
            f"color: {COLORS.get('error', '#e06c75')}; "
            "border-radius: 8px; padding: 8px; font-family: monospace;"
        )
        self.error_section.hide()
        root.addWidget(self.error_section)

    # ── MAIN WINDOW REFERENCE ──────────────────────────────────────────────

    def set_main(self, main):
        """STORE REFERENCE TO MAIN WINDOW."""
        self._main = main

    # ── FILL RESULTS ───────────────────────────────────────────────────────

    def fill_results(self, result: ScanResult):
        """POPULATE RESULTS TABLE WITH COLOR-CODED STATUS."""
        self._raw_results = result
        self.results_table.setRowCount(0)
        self.results_table.setSortingEnabled(False)

        rows = []
        for entry in result.scanned_files:
            name = entry.get("name", "")
            path = entry.get("path", "")
            size = entry.get("size", 0)
            modified = entry.get("modified", "")
            status = entry.get("status", "")
            file_hash = entry.get("hash", "")
            group = entry.get("group", "")

            rows.append((name, path, size, modified, status, file_hash, group))

        self.results_table.setRowCount(len(rows))
        for r, (name, path, size, modified, status, file_hash, group) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)

            truncated = truncate_path(path)
            path_item = QTableWidgetItem(truncated)
            path_item.setToolTip(path)

            size_item = QTableWidgetItem(fmt_size(size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            modified_item = QTableWidgetItem(str(modified))

            status_item = QTableWidgetItem(status)
            if status == "duplicate":
                status_item.setForeground(self._color("error", "#e06c75"))
            elif status == "unique":
                status_item.setForeground(self._color("success", "#98c379"))
            elif status == "excluded":
                status_item.setForeground(self._color("text2", "#7f848e"))
            else:
                status_item.setForeground(self._color("text", "#ffffff"))

            hash_item = QTableWidgetItem(file_hash[:12] if file_hash else "")
            hash_item.setToolTip(file_hash or "")

            group_item = QTableWidgetItem(str(group) if group else "")

            self.results_table.setItem(r, 0, name_item)
            self.results_table.setItem(r, 1, path_item)
            self.results_table.setItem(r, 2, size_item)
            self.results_table.setItem(r, 3, modified_item)
            self.results_table.setItem(r, 4, status_item)
            self.results_table.setItem(r, 5, hash_item)
            self.results_table.setItem(r, 6, group_item)

        self.results_table.setSortingEnabled(True)

    # ── ERROR DISPLAY ──────────────────────────────────────────────────────

    def show_errors(self, errors: list[str]):
        """SHOW/HIDE ERROR SECTION."""
        if not errors:
            self.error_section.hide()
            return
        self.error_section.show()
        self.error_section.setPlainText("\n".join(errors))

    # ── FILTERING ──────────────────────────────────────────────────────────

    def _filter_results(self):
        """FILTER BY COMBO SELECTION AND SEARCH TEXT."""
        if self._raw_results is None:
            return

        filter_text = self.filter_combo.currentText()
        search_text = self.search_input.text().strip().lower()

        if filter_text == "Duplicate Groups":
            self._show_duplicate_groups(search_text)
            return

        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)

        rows = []
        for entry in self._raw_results.scanned_files:
            name = entry.get("name", "")
            path = entry.get("path", "")
            size = entry.get("size", 0)
            modified = entry.get("modified", "")
            status = entry.get("status", "")
            file_hash = entry.get("hash", "")
            group = entry.get("group", "")

            # APPLY FILTER
            if filter_text == "Duplicates Only" and status != "duplicate":
                continue
            if filter_text == "Unique Files" and status != "unique":
                continue

            # APPLY SEARCH
            if search_text and search_text not in name.lower() and search_text not in path.lower():
                continue

            rows.append((name, path, size, modified, status, file_hash, group))

        self.results_table.setRowCount(len(rows))
        for r, (name, path, size, modified, status, file_hash, group) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)

            truncated = truncate_path(path)
            path_item = QTableWidgetItem(truncated)
            path_item.setToolTip(path)

            size_item = QTableWidgetItem(fmt_size(size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            modified_item = QTableWidgetItem(str(modified))

            status_item = QTableWidgetItem(status)
            if status == "duplicate":
                status_item.setForeground(self._color("error", "#e06c75"))
            elif status == "unique":
                status_item.setForeground(self._color("success", "#98c379"))
            elif status == "excluded":
                status_item.setForeground(self._color("text2", "#7f848e"))
            else:
                status_item.setForeground(self._color("text", "#ffffff"))

            hash_item = QTableWidgetItem(file_hash[:12] if file_hash else "")
            hash_item.setToolTip(file_hash or "")

            group_item = QTableWidgetItem(str(group) if group else "")

            self.results_table.setItem(r, 0, name_item)
            self.results_table.setItem(r, 1, path_item)
            self.results_table.setItem(r, 2, size_item)
            self.results_table.setItem(r, 3, modified_item)
            self.results_table.setItem(r, 4, status_item)
            self.results_table.setItem(r, 5, hash_item)
            self.results_table.setItem(r, 6, group_item)

        self.results_table.setSortingEnabled(True)

    def _show_duplicate_groups(self, search_text: str):
        """GROUP DUPLICATES BY ORIGINAL FILE."""
        if self._raw_results is None:
            return

        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)

        # BUILD GROUPS BY HASH
        groups: dict[str, list[dict]] = {}
        for entry in self._raw_results.scanned_files:
            if entry.get("status") != "duplicate":
                continue
            h = entry.get("hash", "")
            if not h:
                continue
            groups.setdefault(h, []).append(entry)

        rows = []
        for h, entries in groups.items():
            original = entries[0] if entries else None
            if original is None:
                continue
            name = original.get("name", "")
            path = original.get("path", "")
            size = original.get("size", 0)
            modified = original.get("modified", "")
            file_hash = original.get("hash", "")
            group = original.get("group", "")
            dup_count = len(entries) - 1

            # APPLY SEARCH
            if search_text and search_text not in name.lower() and search_text not in path.lower():
                continue

            rows.append((
                f"{name} (+{dup_count} copies)",
                path,
                size,
                modified,
                f"{dup_count} duplicates",
                file_hash,
                group,
            ))

        self.results_table.setRowCount(len(rows))
        for r, (name, path, size, modified, status, file_hash, group) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)

            truncated = truncate_path(path)
            path_item = QTableWidgetItem(truncated)
            path_item.setToolTip(path)

            size_item = QTableWidgetItem(fmt_size(size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            modified_item = QTableWidgetItem(str(modified))

            status_item = QTableWidgetItem(status)
            status_item.setForeground(self._color("error", "#e06c75"))

            hash_item = QTableWidgetItem(file_hash[:12] if file_hash else "")
            hash_item.setToolTip(file_hash or "")

            group_item = QTableWidgetItem(str(group) if group else "")

            self.results_table.setItem(r, 0, name_item)
            self.results_table.setItem(r, 1, path_item)
            self.results_table.setItem(r, 2, size_item)
            self.results_table.setItem(r, 3, modified_item)
            self.results_table.setItem(r, 4, status_item)
            self.results_table.setItem(r, 5, hash_item)
            self.results_table.setItem(r, 6, group_item)

        self.results_table.setSortingEnabled(True)

    # ── DOUBLE-CLICK TO OPEN FILE ──────────────────────────────────────────

    def _on_result_double_clicked(self, index):
        """OPEN FILE IN DEFAULT APPLICATION ON DOUBLE-CLICK."""
        row = index.row()
        path_item = self.results_table.item(row, 1)
        if path_item is None:
            return
        full_path = path_item.toolTip() or path_item.text()
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

    # ── HELPERS ────────────────────────────────────────────────────────────

    @staticmethod
    def _color(key: str, default: str) -> str:
        """GET COLOR FROM THEME OR FALLBACK."""
        try:
            from ..theme import COLORS
            return COLORS.get(key, default)
        except ImportError:
            return default
