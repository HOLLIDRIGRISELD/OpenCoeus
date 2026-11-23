"""Search page: keyword, semantic and hybrid retrieval over the local index."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextBrowser,
)

from app.domain.enums import SearchMode
from app.ui.base import BasePage
from app.ui.theme import ACCENT, FAINT, MUTED, TEXT
from app.ui.widgets import (
    Card,
    EmptyState,
    FlowLayout,
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

MODE_LABELS = {
    "Hybrid (recommended)": SearchMode.HYBRID.value,
    "Keyword (exact words)": SearchMode.KEYWORD.value,
    "Semantic (meaning)": SearchMode.SEMANTIC.value,
}


class SearchPage(BasePage):
    """A single query bar with explainable results."""

    navigate = Signal(str)

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._hits: dict[int, object] = {}
        self._last_detail_id: int | None = -1
        self._pending = False
        self._search_task = None
        self._build()

    def _build(self) -> None:
        layout = scrollable_page(self)

        top = QHBoxLayout()
        top.addWidget(
            muted_label(
                "Search the text OpenCoeus extracted. Everything runs against your local database."
            ),
            1,
        )
        layout.addLayout(top)

        query_card = Card("Ask your library")
        query_row = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText('e.g. "invoice from March" or "lecture notes graph theory"')
        self.query_edit.returnPressed.connect(self.start_search)
        query_row.addWidget(self.query_edit, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(MODE_LABELS))
        query_row.addWidget(self.mode_combo)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(5, 100)
        self.limit_spin.setValue(25)
        self.limit_spin.setPrefix("max ")
        query_row.addWidget(self.limit_spin)

        self.search_button = QPushButton("Search")
        self.search_button.setProperty("primary", True)
        self.search_button.clicked.connect(self.start_search)
        query_row.addWidget(self.search_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(
            lambda: self._search_task and self._search_task.cancel()
        )
        query_row.addWidget(self.cancel_button)
        query_card.add_layout(query_row)

        self.notes_label = hint_label(
            "Hybrid mode fuses keyword rank and semantic similarity using Reciprocal Rank Fusion."
        )
        query_card.add(self.notes_label)
        layout.addWidget(query_card)
        layout.addWidget(separator())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        results_card = Card("Results")
        self.results_count = hint_label("Enter a query to begin.")
        results_card.add(self.results_count)
        self.empty_state = EmptyState(
            "No results", "Try a broader query or switch search mode."
        )
        self.empty_state.setVisible(False)
        results_card.add(self.empty_state)
        self.results_table = make_table(
            ["Document", "Category", "Mode", "Match", "Snippet"],
            stretch=4,
        )
        self.results_table.itemSelectionChanged.connect(self._selection_changed)
        self.results_table.doubleClicked.connect(lambda _index: self._open_selected())
        results_card.add(self.results_table)
        splitter.addWidget(results_card)

        detail_card = Card("Why this result")
        self.detail_browser = QTextBrowser()
        self.detail_browser.setHtml(
            f"<p style='color:{MUTED}'>Select a result to see its path, category and "
            "matching passage.</p>"
        )
        detail_card.add(self.detail_browser)

        actions = FlowLayout()
        self.open_button = QPushButton("Open")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)
        self.reveal_button = QPushButton("Reveal")
        self.reveal_button.setEnabled(False)
        self.reveal_button.clicked.connect(self._reveal_selected)
        actions.addWidget(self.open_button)
        actions.addWidget(self.reveal_button)
        detail_card.add_layout(actions)
        splitter.addWidget(detail_card)
        results_card.setMinimumWidth(280)
        detail_card.setMinimumWidth(240)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def start_search(self) -> None:
        if self._pending:
            return
        query = self.query_edit.text().strip()
        if not query:
            self.notes_label.setText("Enter a query first.")
            return
        mode = MODE_LABELS.get(self.mode_combo.currentText(), SearchMode.HYBRID.value)
        limit = self.limit_spin.value()
        self._pending = True
        self.search_button.setEnabled(False)
        self.search_button.setText("Searching…")
        self.cancel_button.setEnabled(True)
        self.notes_label.setText("Searching…")

        def work(_progress, cancel):  # type: ignore[no-untyped-def]
            cancel.begin()
            try:
                return self.ctx.search.search(query, mode=mode, limit=limit, cancel=cancel)
            finally:
                cancel.finish()

        self._search_task = self.run_task(
            work,
            label="Search",
            on_done=self._search_done,
            on_failed=self._search_failed,
            on_cancelled=self._search_cancelled,
        )

    def _search_done(self, response: object) -> None:
        self._pending = False
        self._search_task = None
        self.cancel_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.search_button.setText("Search")
        hits = list(getattr(response, "hits", []))
        self._hits = {hit.file_id: hit for hit in hits}
        self._last_detail_id = -1
        self.empty_state.setVisible(not hits)
        self.results_table.setRowCount(0)

        for row, hit in enumerate(hits):
            self.results_table.insertRow(row)
            set_cell(self.results_table, row, 0, hit.filename, data=hit.file_id, bold=True)
            set_cell(self.results_table, row, 1, hit.category or "—")
            set_cell(self.results_table, row, 2, hit.mode)
            set_cell(self.results_table, row, 3, f"{hit.match_percent}%")
            snippet = (hit.snippet or "").replace("\n", " ").strip()
            set_cell(
                self.results_table,
                row,
                4,
                snippet[:160] + ("…" if len(snippet) > 160 else ""),
                tooltip=snippet,
            )

        took = getattr(response, "took_ms", 0.0)
        notes = list(getattr(response, "notes", []))
        self.notes_label.setText(
            f"{len(hits)} result(s) in {took:.1f} ms. " + " ".join(notes)
        )
        self.results_count.setText(
            f"Showing {len(hits)} result(s) for {getattr(response, 'query', '')!r}."
            if hits
            else "No matches. Try different words or another mode."
        )
        if hits:
            self.results_table.selectRow(0)
        else:
            self._selection_changed()

    def _search_failed(self, error: str) -> None:
        self._pending = False
        self._search_task = None
        self.cancel_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.search_button.setText("Search")
        self.empty_state.setVisible(False)
        self.notes_label.setText(f"Search failed: {error}")

    def _search_cancelled(self) -> None:
        self._pending = False
        self._search_task = None
        self.cancel_button.setEnabled(False)
        self.search_button.setEnabled(True)
        self.search_button.setText("Search")
        self.empty_state.setVisible(False)
        self.notes_label.setText("Search cancelled.")

    def _selection_changed(self) -> None:
        raw = selected_data(self.results_table)
        hit_id = int(raw) if raw is not None else None
        if hit_id == self._last_detail_id:
            return
        self._last_detail_id = hit_id
        if raw is None:
            self.open_button.setEnabled(False)
            self.reveal_button.setEnabled(False)
            self.detail_browser.setHtml(
                f"<p style='color:{MUTED}'>Select a result to see its context.</p>"
            )
            return
        self.open_button.setEnabled(True)
        self.reveal_button.setEnabled(True)
        hit = self._hits.get(int(raw))
        if hit is None:
            return
        parts = [
            f"<h3 style='margin-top:0'>{html.escape(hit.filename)}</h3>",
            f"<p style='color:{MUTED}; font-family:monospace; font-size:11px'>"
            f"{html.escape(str(hit.path))}</p>",
            "<p>"
            f"<b>{hit.match_percent}%</b> match · {html.escape(hit.mode)} mode · "
            f"{html.escape(hit.category or 'Unclassified')}</p>",
        ]
        if hit.explanation:
            parts.append(
                f"<p style='color:{TEXT}'>{html.escape(str(hit.explanation))}</p>"
            )
        if hit.snippet:
            parts.append(
                f"<h4>Matching passage</h4><blockquote style='color:{TEXT}; "
                f"border-left:2px solid {ACCENT}; padding-left:10px'>"
                f"{html.escape(str(hit.snippet))}</blockquote>"
            )
        parts.append(
            f"<p style='color:{FAINT}'>Ranking combines the raw score with the selected "
            "retrieval mode. Scores are relative to this query.</p>"
        )
        self.detail_browser.setHtml("".join(parts))

    def _selected_path(self) -> Path | None:
        raw = selected_data(self.results_table)
        if raw is None:
            return None
        hit = self._hits.get(int(raw))
        return Path(str(hit.path)) if hit is not None else None

    def _open_selected(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        if not path.exists():
            QMessageBox.warning(self, "File missing", f"{path} no longer exists.")
            return
        open_file(path)

    def _reveal_selected(self) -> None:
        path = self._selected_path()
        if path is not None:
            reveal_in_folder(path)

    def focus_query(self) -> None:
        self.query_edit.setFocus()


__all__ = ["SearchPage"]
