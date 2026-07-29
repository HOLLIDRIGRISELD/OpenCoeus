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

# COLUMN WIDTHS FOR RESULTS TABLE: [Name, Suggested, Path, Size, Modified, Status, Hash, Group,
# Topic, Author, Org, Conf].
_RESULTS_COL_WIDTHS = [160, 160, 220, 70, 100, 90, 80, 50, 100, 80, 80, 60, 160]


class ResultsPage(QWidget):
    """Results page with filtering and duplicate group view."""

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
            "Has Suggested Title",
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
            ["Name", "Suggested", "Path", "Size", "Modified", "Status", "Hash", "Group",
             "Topic", "Author", "Org", "Conf", "Dest"],
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
        """Store reference to main window."""
        self._main = main

    # FILL RESULTS

    def fill_results(self, result: ScanResult):
        """Populate results table with color-coded status."""
        self._raw_results = result
        self.results_table.clear()

        for entry in result.rows:
            name = entry.suggested_title or os.path.basename(entry.path)
            suggested = entry.suggested_title if entry.suggested_title and entry.suggested_title != os.path.basename(entry.path) else ""
            self._add_result_row(
                name, suggested, entry.path, entry.size, entry.modified_at,
                entry.status, entry.sha256, entry.duplicate_of,
                entry.nlp_topic, entry.nlp_author, entry.nlp_organization,
                entry.nlp_confidence, entry.smart_destination,
            )

    def _add_result_row(self, name, suggested, path, size, modified, status, file_hash, group,
                        nlp_topic="", nlp_author="", nlp_org="", nlp_conf=0.0, nlp_dest=""):
        """Add a single row to the results table."""
        if status == "duplicate":
            badge = status_badge(status.upper(), COLORS['red'], COLORS.get('red_bg', '#3b1518'))
        elif status == "unique":
            badge = status_badge(status.upper(), COLORS['green'], COLORS.get('green_bg', '#14302a'))
        elif status == "excluded":
            badge = status_badge(status.upper(), COLORS['text3'], COLORS.get('surface3', '#252642'))
        else:
            badge = status_badge(status.upper(), COLORS['text'], COLORS.get('surface2', '#1f2038'))

        conf_text = f"{nlp_conf:.0%}" if nlp_conf > 0 else ""
        self.results_table.addRow(
            widgets=[
                (name, None),
                (suggested, None),
                (truncate_path(path), None),
                (fmt_size(size), None),
                (str(modified) if modified else "—", None),
                ("", badge),
                (file_hash[:12] if file_hash else "", None),
                (str(group) if group else "", None),
                (nlp_topic if nlp_topic else "", None),
                (nlp_author if nlp_author else "", None),
                (nlp_org if nlp_org else "", None),
                (conf_text, None),
                (nlp_dest if nlp_dest else "", None),
            ],
            tooltips=[
                name, suggested, path, "", "", "", file_hash or "", "",
                nlp_topic, nlp_author, nlp_org, f"{nlp_conf:.0%}" if nlp_conf > 0 else "",
                nlp_dest,
            ],
        )

    # ERROR DISPLAY

    def show_errors(self, errors: list[str]):
        """Show/hide error section."""
        if not errors:
            self.error_section.hide()
            return
        self.error_section.show()
        self.error_section.setPlainText("\n".join(errors))

    # FILTERING

    def _filter_results(self):
        """Filter by combo selection and search text."""
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
            suggested = entry.suggested_title if entry.suggested_title and entry.suggested_title != os.path.basename(entry.path) else ""

            # APPLY FILTER.
            if filter_text == "Duplicates Only" and entry.status != "duplicate":
                continue
            if filter_text == "Unique Files" and entry.status != "unique":
                continue
            if filter_text == "Has Suggested Title" and not entry.suggested_title:
                continue

            # APPLY SEARCH.
            if search_text and search_text not in name.lower() and search_text not in entry.path.lower():
                continue

            self._add_result_row(
                name, suggested, entry.path, entry.size, entry.modified_at,
                entry.status, entry.sha256, entry.duplicate_of,
                entry.nlp_topic, entry.nlp_author, entry.nlp_organization,
                entry.nlp_confidence, entry.smart_destination,
            )

    def _show_duplicate_groups(self, search_text: str):
        """Group duplicates by original file."""
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
            suggested = original.suggested_title if original.suggested_title and original.suggested_title != os.path.basename(original.path) else ""
            dup_count = len(entries) - 1

            # APPLY SEARCH.
            if search_text and search_text not in name.lower() and search_text not in original.path.lower():
                continue

            self._add_result_row(
                f"{name} (+{dup_count} copies)",
                suggested,
                original.path, original.size, original.modified_at,
                f"{dup_count} duplicates", original.sha256, original.duplicate_of,
                original.nlp_topic, original.nlp_author, original.nlp_organization,
                original.nlp_confidence, original.smart_destination,
            )

    # DOUBLE CLICK TO OPEN FILE

    def _on_result_double_clicked(self, row: int):
        """Open file in default application on double-click."""
        path_lbl = self.results_table.item(row, 2)
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
