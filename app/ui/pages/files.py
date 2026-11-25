"""Files page: browse, inspect and re-analyse the indexed library."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
)

from app.ui.base import BasePage
from app.ui.theme import AMBER, MUTED, TEXT, confidence_color
from app.ui.widgets import (
    Card,
    EmptyState,
    FlowLayout,
    add_actions,
    format_datetime,
    format_percent,
    format_size,
    hint_label,
    make_table,
    muted_label,
    open_file,
    reveal_in_folder,
    scrollable_page,
    selected_data,
    separator,
    set_cell,
)

STATUS_CHOICES = [
    "All statuses",
    "discovered",
    "analysed",
    "pending_review",
    "organised",
    "failed",
    "unsupported",
    "unavailable",
]
SORT_CHOICES = {"Newest first": "modified", "Name": "name", "Largest first": "size"}
PAGE_SIZE = 1000


class FilesPage(BasePage):
    """A filterable table with a detail pane for a single file."""

    library_changed = Signal()
    navigate = Signal(str)

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._summaries: dict[int, object] = {}
        self._current_id: int | None = None
        self._last_detail_id: int | None = -1
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = scrollable_page(self)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top = add_actions(layout, refresh)
        top.insertWidget(
            0,
            muted_label("Every file OpenCoeus has discovered, with the analysis it holds."),
            1,
        )

        self.profile_label = hint_label("")
        layout.addWidget(self.profile_label)

        filters = Card("Filters", subtitle="filename text, lifecycle status and order")
        filter_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter by filename…")
        self.search_edit.setClearButtonEnabled(True)
        filter_row.addWidget(self.search_edit, 2)

        self.status_combo = QComboBox()
        self.status_combo.addItems(STATUS_CHOICES)
        filter_row.addWidget(self.status_combo, 1)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(list(SORT_CHOICES))
        filter_row.addWidget(self.sort_combo, 1)
        filters.add_layout(filter_row)
        self.count_label = hint_label("")
        filters.add(self.count_label)
        layout.addWidget(filters)
        layout.addWidget(separator())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        table_card = Card("Library")
        self.table = make_table(
            ["Name", "Category", "Status", "Size", "Modified"],
            stretch=0,
        )
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(lambda _index: self._open_selected())
        table_card.add(self.table)
        self.empty_state = EmptyState(
            "No files yet", "Open Scan & analyse to register a folder."
        )
        self.empty_state.setVisible(False)
        table_card.add(self.empty_state)
        splitter.addWidget(table_card)

        detail_card = Card("File detail")
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        detail_card.add(self.detail)

        buttons = FlowLayout()
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(self._open_selected)
        self.reveal_button = QPushButton("Reveal")
        self.reveal_button.clicked.connect(self._reveal_selected)
        self.analyse_button = QPushButton("Analyse")
        self.analyse_button.setProperty("primary", True)
        self.analyse_button.clicked.connect(self._analyse_selected)
        self.review_button = QPushButton("Review →")
        self.review_button.clicked.connect(lambda: self.navigate.emit("recommendations"))
        for button in (self.open_button, self.reveal_button, self.analyse_button):
            button.setEnabled(False)
            buttons.addWidget(button)
        buttons.addWidget(self.review_button)
        detail_card.add_layout(buttons)
        splitter.addWidget(detail_card)
        table_card.setMinimumWidth(365)
        detail_card.setMinimumWidth(240)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.refresh)
        self.search_edit.textChanged.connect(lambda _text: self._debounce.start())
        self.status_combo.currentIndexChanged.connect(self.refresh)
        self.sort_combo.currentIndexChanged.connect(self.refresh)

        self.detail.setHtml(
            f"<p style='color:{MUTED}'>Select a file to see its details, "
            "evidence and available actions.</p>"
        )

    def refresh(self) -> None:
        self._last_detail_id = -1
        previous_id = self._current_id
        active = self.ctx.profiles.active()
        if active is None:
            self.profile_label.setText("Active profile: none")
        else:
            included = ", ".join(active.included_folders) or "all"
            excluded = ", ".join(active.excluded_folders) or "none"
            patterns = ", ".join(active.custom_patterns) or "none"
            self.profile_label.setText(
                f"Active profile: {active.name} — root {active.root_path}; "
                f"include {included}; exclude {excluded}; patterns {patterns}"
            )

        status = self.status_combo.currentText()
        filters = {
            "status": None if status == "All statuses" else status,
            "text_filter": self.search_edit.text().strip() or None,
            "order_by": SORT_CHOICES.get(self.sort_combo.currentText(), "modified"),
        }
        try:
            summaries = self.ctx.files.list_summaries(limit=PAGE_SIZE + 1, **filters)
            total = self.ctx.files.count_summaries(
                **{key: value for key, value in filters.items() if key != "order_by"}
            )
            summaries = summaries[:PAGE_SIZE]
        except Exception as exc:
            self.message.emit(f"Could not load files: {exc}")
            self._summaries.clear()
            self._current_id = None
            self.table.setRowCount(0)
            for button in (self.open_button, self.reveal_button, self.analyse_button):
                button.setEnabled(False)
            self.count_label.setText("Files could not be loaded.")
            self.empty_state.setVisible(True)
            return

        self._summaries = {summary.id: summary for summary in summaries}
        self.empty_state.setVisible(not summaries)
        self.table.setRowCount(0)
        for row, summary in enumerate(summaries):
            self.table.insertRow(row)
            set_cell(self.table, row, 0, summary.name, data=summary.id, bold=True)
            set_cell(self.table, row, 1, summary.category or "—")
            set_cell(
                self.table,
                row,
                2,
                summary.status.replace("_", " "),
                tooltip="Processing lifecycle status",
            )
            set_cell(self.table, row, 3, format_size(summary.size))
            set_cell(self.table, row, 4, format_datetime(summary.modified_at))

        if total > len(summaries):
            self.count_label.setText(
                f"Showing first {len(summaries)} of {total} file(s); the rest are not loaded."
            )
        else:
            self.count_label.setText(
                f"{len(summaries)} file(s) shown."
                if summaries
                else "No files match the current filters."
            )
        if previous_id is not None and previous_id in self._summaries:
            self._select_row(previous_id)
        elif summaries:
            self.table.selectRow(0)
        else:
            self._current_id = None
            self._selection_changed()

    def _select_row(self, file_id: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == file_id:
                self.table.selectRow(row)
                return

    def _selection_changed(self) -> None:
        file_id = selected_data(self.table)
        self._current_id = int(file_id) if file_id is not None else None
        if self._current_id == self._last_detail_id:
            return
        self._last_detail_id = self._current_id
        has_selection = self._current_id is not None
        for button in (self.open_button, self.reveal_button, self.analyse_button):
            button.setEnabled(has_selection)
        if not has_selection:
            self.detail.setHtml(
                f"<p style='color:{MUTED}'>Select a file to see its details.</p>"
            )
            return
        self._show_detail(self._current_id)

    def _show_detail(self, file_id: int) -> None:
        summary = self._summaries.get(file_id)
        if summary is None:
            return
        detail = None
        try:
            detail = self.ctx.recommendations.detail(file_id)
        except Exception as exc:
            self.message.emit(f"Could not load file details: {exc}")
            detail = None

        colour = confidence_color(getattr(detail, "confidence", None))
        rows = [
            ("Current name", html.escape(summary.name)),
            ("Path", f"<span style='font-family:monospace'>{html.escape(summary.path)}</span>"),
            ("Status", html.escape(summary.status.replace("_", " "))),
            ("Category", html.escape((getattr(detail, "category", None) or summary.category) or "—")),
            (
                "Confidence",
                f"<span style='color:{colour}'>"
                f"{format_percent(getattr(detail, 'confidence', None))}</span>",
            ),
            ("Title", html.escape((getattr(detail, "title", None) or summary.title) or "—")),
            ("Size", format_size(summary.size)),
            ("Modified", format_datetime(summary.modified_at)),
        ]
        parts = ["<h3 style='margin-top:0'>" + html.escape(summary.name) + "</h3>"]
        for label, value in rows:
            parts.append(
                f"<p style='margin:2px 0'><span style='color:{MUTED}'>{label}:</span> "
                f"{value}</p>"
            )

        if detail is not None and getattr(detail, "summary", None):
            parts.append(
                f"<h4>Summary</h4><p style='color:{TEXT}'>"
                + html.escape(str(detail.summary))
                + "</p>"
            )
        if detail is not None and getattr(detail, "suggested_name", None):
            parts.append("<h4>Recommendation</h4><ul>")
            parts.append(
                "<li>Filename: <b>" + html.escape(str(detail.suggested_name)) + "</b></li>"
            )
            if detail.suggested_folder:
                parts.append(
                    "<li>Folder: <b>" + html.escape(str(detail.suggested_folder)) + "</b></li>"
                )
            if detail.method:
                parts.append(
                    "<li>Classified by: " + html.escape(str(detail.method)) + "</li>"
                )
            parts.append("</ul>")
        tags = getattr(detail, "tags", None) or summary.tags
        if tags:
            parts.append(
                f"<p style='color:{MUTED}'>Tags: " + html.escape(", ".join(tags)) + "</p>"
            )
        evidence = list(getattr(detail, "evidence", []) or [])[:6]
        if evidence:
            parts.append("<h4>Evidence</h4><ul>")
            for item in evidence:
                parts.append("<li>" + html.escape(str(item)) + "</li>")
            parts.append("</ul>")
        warnings = list(getattr(detail, "warnings", []) or [])[:5]
        if warnings:
            parts.append(f"<h4 style='color:{AMBER}'>Needs attention</h4><ul>")
            for item in warnings:
                parts.append("<li>" + html.escape(str(item)) + "</li>")
            parts.append("</ul>")
        self.detail.setHtml("".join(parts))

    def _path_for_selected(self) -> Path | None:
        if self._current_id is None:
            return None
        summary = self._summaries.get(self._current_id)
        return Path(summary.path) if summary is not None else None

    def _open_selected(self) -> None:
        path = self._path_for_selected()
        if path is None:
            return
        if not path.exists():
            QMessageBox.warning(self, "File missing", f"{path} no longer exists on disk.")
            return
        if not open_file(path):
            QMessageBox.information(self, "Could not open", f"No application opened {path}.")

    def _reveal_selected(self) -> None:
        path = self._path_for_selected()
        if path is not None:
            reveal_in_folder(path)

    def _analyse_selected(self) -> None:
        if self._current_id is None:
            return
        file_id = self._current_id
        self.analyse_button.setEnabled(False)
        self.analyse_button.setText("Analysing…")
        use_llm = bool(self.ctx.settings.enable_llm)

        def work(_progress, _cancel):  # type: ignore[no-untyped-def]
            return self.ctx.analysis.analyse_file(file_id, use_llm=use_llm)

        self.run_task(
            work,
            label="Analysis",
            on_done=self._analysis_done,
            on_failed=self._analysis_failed,
        )

    def _analysis_done(self, outcome: object) -> None:
        self.analyse_button.setText("Analyse")
        self.analyse_button.setEnabled(True)
        error = getattr(outcome, "error", None)
        if error:
            self.message.emit(f"Analysis did not complete: {error}")
        else:
            self.message.emit(
                f"Analysed: {getattr(outcome, 'category_path', 'n/a')} "
                f"({format_percent(getattr(outcome, 'confidence', None))})."
            )
        self.refresh()
        self.library_changed.emit()

    def _analysis_failed(self, error: str) -> None:
        self.analyse_button.setText("Analyse")
        self.analyse_button.setEnabled(True)
        self.message.emit(f"Analysis failed: {error}")
        QMessageBox.critical(self, "Analysis failed", error)

    def has_selection(self) -> bool:
        return self._current_id is not None


__all__ = ["FilesPage"]
