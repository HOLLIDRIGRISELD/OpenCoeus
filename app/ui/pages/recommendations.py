"""Recommendations page: human review of filename, folder and category proposals."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.constants import UNCLASSIFIED
from app.ui.base import BasePage
from app.ui.theme import AMBER, FAINT, GREEN, MUTED, RED, TEXT, confidence_color
from app.ui.widgets import (
    Card,
    EmptyState,
    FlowLayout,
    LineEdit,
    add_actions,
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

PAGE_SIZE = 500


class RecommendationsPage(BasePage):
    """Review one suggestion at a time, with evidence and manual overrides."""

    library_changed = Signal()
    navigate = Signal(str)

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._loading = False
        self._previous_category = ""
        self._current_id: int | None = None
        self._detail: object | None = None
        self._suggestions: dict[int, object] = {}
        self._duplicates_loaded = False
        self._last_detail_id: int | None = -1
        self._partial_suggestions = False
        self._total_suggestions = 0
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = scrollable_page(self)

        self.accept_all_button = QPushButton("Accept all")
        self.accept_all_button.clicked.connect(self._accept_all)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top = add_actions(layout, self.accept_all_button, refresh)
        top.insertWidget(
            0,
            muted_label(
                "Accepting a recommendation never moves a file. It only feeds the planner, "
                "which asks for approval again."
            ),
            1,
        )
        layout.addWidget(separator())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_suggestions_tab(), "Suggestions")
        self.tabs.addTab(self._build_duplicates_tab(), "Duplicate files")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        splitter.addWidget(self.tabs)

        review = self._build_review_panel()
        splitter.addWidget(review)
        self.tabs.setMinimumWidth(270)
        review.setMinimumWidth(240)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def _build_suggestions_tab(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(10)
        self.suggestion_table = make_table(
            ["Original file", "Proposed name", "Category", "Conf.", "Status"],
            stretch=1,
        )
        self.suggestion_table.itemSelectionChanged.connect(self._selection_changed)
        body.addWidget(self.suggestion_table, 1)
        self.suggestion_count = hint_label("")
        body.addWidget(self.suggestion_count)
        self.empty_state = EmptyState(
            "Nothing to review", "Scan and analyse a folder to generate suggestions."
        )
        self.empty_state.setVisible(False)
        body.addWidget(self.empty_state)
        return page

    def _build_duplicates_tab(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(10)
        body.addWidget(
            hint_label(
                "Identical SHA-256 hashes. OpenCoeus reports duplicates but never deletes them."
            )
        )
        self.duplicate_table = make_table(
            ["Hash", "Copies", "Redundant", "Locations"],
            stretch=3,
        )
        self.duplicate_table.doubleClicked.connect(self._reveal_duplicate)
        body.addWidget(self.duplicate_table, 1)
        return page

    def _build_review_panel(self) -> QWidget:
        card = Card("Review")
        self.detail_browser = QTextBrowser()
        self.detail_browser.setMinimumHeight(180)
        card.add(self.detail_browser)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        form.addWidget(self._field_label("Filename"), 0, 0)
        self.filename_edit = LineEdit()
        form.addWidget(self.filename_edit, 0, 1, 1, 2)

        form.addWidget(self._field_label("Folder"), 1, 0)
        self.folder_edit = LineEdit()
        self.folder_edit.setPlaceholderText("Finance/Invoices")
        form.addWidget(self.folder_edit, 1, 1, 1, 2)

        form.addWidget(self._field_label("Category"), 2, 0)
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.category_combo.setMinimumContentsLength(10)
        self.category_combo.currentTextChanged.connect(self._category_changed)
        form.addWidget(self.category_combo, 2, 1, 1, 2)
        card.add_layout(form)
        card.add(
            hint_label(
                "The folder follows the category unless you edit it. Names and folders use the "
                "same validation as generated suggestions."
            )
        )

        self.form_status = QLabel("")
        self.form_status.setWordWrap(True)
        self.form_status.setProperty("role", "hint")
        card.add(self.form_status)

        actions = FlowLayout()
        self.save_button = QPushButton("Save edits only")
        self.save_button.clicked.connect(self._save_edits)
        self.accept_button = QPushButton("Accept & save")
        self.accept_button.setProperty("primary", True)
        self.accept_button.clicked.connect(self._accept)
        self.reject_button = QPushButton("Reject")
        self.reject_button.setProperty("danger", True)
        self.reject_button.clicked.connect(self._reject)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self._reset)
        for button in (
            self.save_button,
            self.accept_button,
            self.reject_button,
            self.reset_button,
        ):
            button.setEnabled(False)
            actions.addWidget(button)
        card.add_layout(actions)

        file_actions = FlowLayout()
        self.open_button = QPushButton("Open file")
        self.open_button.setProperty("flat", True)
        self.open_button.clicked.connect(self._open_file)
        self.reveal_button = QPushButton("Reveal")
        self.reveal_button.setProperty("flat", True)
        self.reveal_button.clicked.connect(self._reveal_file)
        self.plan_button = QPushButton("Planner →")
        self.plan_button.setProperty("flat", True)
        self.plan_button.clicked.connect(lambda: self.navigate.emit("planner"))
        for button in (self.open_button, self.reveal_button):
            button.setEnabled(False)
            file_actions.addWidget(button)
        file_actions.addWidget(self.plan_button)
        card.add_layout(file_actions)

        self.detail_browser.setHtml(
            f"<p style='color:{MUTED}'>Select a suggestion to review its evidence.</p>"
        )
        return card

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "field")
        label.setWordWrap(True)
        return label

    def refresh(self) -> None:
        self._duplicates_loaded = False
        self._last_detail_id = -1
        self._refresh_suggestions()
        self._refresh_categories()

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self.load_duplicates()

    def load_duplicates(self) -> None:
        if self._duplicates_loaded:
            return
        self._duplicates_loaded = True
        self._refresh_duplicates()

    def _refresh_suggestions(self) -> None:
        previous_id = self._current_id
        try:
            suggestions = self.ctx.recommendations.pending(limit=PAGE_SIZE + 1)
            total = self.ctx.recommendations.pending_count()
            suggestions = suggestions[:PAGE_SIZE]
        except Exception as exc:
            self.message.emit(f"Could not load recommendations: {exc}")
            self._suggestions.clear()
            self._current_id = None
            self.suggestion_table.setRowCount(0)
            self.suggestion_count.setText("Suggestions could not be loaded.")
            self._partial_suggestions = False
            self._total_suggestions = 0
            self.accept_all_button.setText("Accept all")
            self.accept_all_button.setEnabled(False)
            self._clear_form()
            self.empty_state.setVisible(True)
            return
        self._suggestions = {item.file_id: item for item in suggestions}
        self.empty_state.setVisible(not suggestions)
        self.suggestion_table.setRowCount(0)
        for row, suggestion in enumerate(suggestions):
            self.suggestion_table.insertRow(row)
            set_cell(self.suggestion_table, row, 0, suggestion.filename, data=suggestion.file_id)
            set_cell(self.suggestion_table, row, 1, suggestion.suggested_value, bold=True)
            set_cell(self.suggestion_table, row, 2, suggestion.category or "—")
            set_cell(
                self.suggestion_table,
                row,
                3,
                format_percent(suggestion.confidence),
                color=confidence_color(suggestion.confidence),
            )
            set_cell(self.suggestion_table, row, 4, suggestion.status.replace("_", " "))

        self._partial_suggestions = total > len(suggestions)
        self._total_suggestions = total
        if self._partial_suggestions:
            self.suggestion_count.setText(
                f"Showing first {len(suggestions)} of {total} suggestion(s) awaiting a decision."
            )
            self.accept_all_button.setText("Accept loaded (partial)")
        else:
            self.suggestion_count.setText(
                f"{len(suggestions)} suggestion(s) awaiting a decision."
                if suggestions
                else "Nothing to review. Scan and analyse a folder to generate suggestions."
            )
            self.accept_all_button.setText("Accept all")
        self.accept_all_button.setEnabled(bool(suggestions))

        if previous_id is not None and previous_id in self._suggestions:
            self._select_row(previous_id)
        elif suggestions:
            self.suggestion_table.selectRow(0)
        else:
            self._current_id = None
            self._clear_form()

    def _refresh_duplicates(self) -> None:
        try:
            groups = self.ctx.duplicates()
        except Exception as exc:
            self.message.emit(f"Could not load duplicate groups: {exc}")
            groups = []
        self.duplicate_table.setRowCount(0)
        for row, group in enumerate(groups):
            self.duplicate_table.insertRow(row)
            paths = [str(item.get("path", "")) for item in group.files]
            set_cell(
                self.duplicate_table,
                row,
                0,
                group.sha256[:14] + "…",
                tooltip=group.sha256,
                data=paths[0] if paths else None,
            )
            set_cell(self.duplicate_table, row, 1, str(group.count))
            set_cell(self.duplicate_table, row, 2, format_size(group.wasted_bytes))
            set_cell(
                self.duplicate_table,
                row,
                3,
                " · ".join(Path(path).name for path in paths),
                tooltip="\n".join(paths),
            )

    def _refresh_categories(self) -> None:
        try:
            categories = self.ctx.analyses.category_paths()
        except Exception:
            categories = []
        current = self.category_combo.currentText()
        self._loading = True
        self.category_combo.clear()
        self.category_combo.addItems(categories)
        if current:
            self.category_combo.setCurrentText(current)
        self._loading = False

    def _select_row(self, file_id: int) -> None:
        for row in range(self.suggestion_table.rowCount()):
            item = self.suggestion_table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == file_id:
                self.suggestion_table.selectRow(row)
                return

    def _selection_changed(self) -> None:
        raw = selected_data(self.suggestion_table)
        file_id = int(raw) if raw is not None else None
        if file_id == self._last_detail_id:
            return
        self._last_detail_id = file_id
        self._current_id = file_id
        if file_id is None:
            self._clear_form()
            return
        self._load_detail(file_id)

    def _load_detail(self, file_id: int) -> None:
        try:
            detail = self.ctx.recommendations.detail(file_id)
        except Exception as exc:
            self.message.emit(f"Could not load the file: {exc}")
            self._clear_form()
            return
        if detail is None:
            self._clear_form()
            return
        self._detail = detail

        self._loading = True
        self.filename_edit.setText(detail.suggested_name or detail.filename)
        self.folder_edit.setText(detail.suggested_folder or detail.category or "")
        category = detail.category or UNCLASSIFIED
        self._previous_category = category
        if self.category_combo.findText(category) < 0:
            self.category_combo.addItem(category)
        self.category_combo.setCurrentText(category)
        self._loading = False

        for button in (
            self.save_button,
            self.accept_button,
            self.reject_button,
            self.reset_button,
        ):
            button.setEnabled(True)
        self.open_button.setEnabled(True)
        self.reveal_button.setEnabled(True)

        colour = confidence_color(detail.confidence)
        parts = [
            f"<h3 style='margin-top:0'>{html.escape(detail.filename)}</h3>",
            f"<p style='color:{MUTED}; font-family:monospace; font-size:11px'>"
            f"{html.escape(detail.path)}</p>",
        ]
        badges = [
            f"<span style='color:{colour}'>confidence {format_percent(detail.confidence)}</span>",
            f"<span style='color:{MUTED}'>{html.escape(detail.method or 'unanalysed')}</span>",
        ]
        parts.append("<p>" + " · ".join(badges) + "</p>")
        facts = [
            ("Category", detail.category),
            ("Title", detail.title),
            ("Type", detail.document_type),
            ("Organisation", detail.organisation),
            ("Date", detail.document_date),
        ]
        parts.append("<table cellspacing='0' cellpadding='3'>")
        for label, value in facts:
            if value:
                parts.append(
                    f"<tr><td style='color:{MUTED}; padding-right:10px'>{label}</td>"
                    f"<td>{html.escape(str(value))}</td></tr>"
                )
        parts.append("</table>")
        if detail.summary:
            parts.append(
                f"<p style='color:{TEXT}'>{html.escape(detail.summary)}</p>"
            )
        if detail.naming_explanation:
            parts.append(
                f"<h4>Why this filename</h4><p style='color:{TEXT}'>"
                + html.escape(detail.naming_explanation)
                + "</p>"
            )
        if detail.folder_explanation:
            parts.append(
                f"<h4>Why this folder</h4><p style='color:{TEXT}'>"
                + html.escape(detail.folder_explanation)
                + "</p>"
            )
        if detail.evidence:
            parts.append("<h4>Evidence</h4><ul>")
            for item in detail.evidence[:10]:
                parts.append(f"<li>{html.escape(str(item))}</li>")
            parts.append("</ul>")
        if detail.warnings:
            parts.append(f"<h4 style='color:{AMBER}'>Warnings</h4><ul>")
            for item in detail.warnings[:8]:
                parts.append(f"<li>{html.escape(str(item))}</li>")
            parts.append("</ul>")
        if detail.tags:
            parts.append(
                f"<p style='color:{FAINT}'>Tags: {html.escape(', '.join(detail.tags))}</p>"
            )
        self.detail_browser.setHtml("".join(parts))
        self.form_status.setText(
            "Edits are validated and saved as accepted recommendations."
        )
        self.form_status.setStyleSheet(f"color: {FAINT};")

    def _clear_form(self) -> None:
        self._detail = None
        self._loading = True
        self.filename_edit.clear()
        self.folder_edit.clear()
        self.category_combo.setCurrentText("")
        self._loading = False
        for button in (
            self.save_button,
            self.accept_button,
            self.reject_button,
            self.reset_button,
            self.open_button,
            self.reveal_button,
        ):
            button.setEnabled(False)
        self.form_status.setText("")
        self.detail_browser.setHtml(
            f"<p style='color:{MUTED}'>Select a suggestion to review its evidence.</p>"
        )

    def _category_changed(self, text: str) -> None:
        if self._loading:
            return
        if self.folder_edit.text().strip() == self._previous_category:
            self.folder_edit.setText(text)
        self._previous_category = text

    def _apply_edits(self) -> bool:
        """Persist manual edits. Returns False when validation failed."""

        if self._current_id is None or self._detail is None:
            return False
        detail = self._detail
        if getattr(detail, "file_id", None) != self._current_id:
            return False
        filename = self.filename_edit.text().strip()
        folder = self.folder_edit.text().strip().replace("\\", "/")
        category = self.category_combo.currentText().strip() or UNCLASSIFIED
        changed = False

        if not filename:
            self._show_problems(["The filename cannot be empty."])
            return False
        if folder.startswith("/") or ".." in Path(folder).parts:
            self._show_problems(["The folder must stay inside the organisation root."])
            return False

        try:
            if category != (detail.category or ""):
                self.ctx.recommendations.set_category(self._current_id, category)
                changed = True
            if folder and folder != category:
                result = self.ctx.recommendations.set_folder(self._current_id, folder)
                if not result.ok:
                    self._show_problems(result.problems)
                    return False
                changed = True
            if filename != (detail.suggested_name or detail.filename):
                result = self.ctx.recommendations.set_filename(self._current_id, filename)
                if not result.ok:
                    self._show_problems(result.problems)
                    return False
                changed = True
        except Exception as exc:
            self._show_problems([str(exc)])
            return False

        if not changed:
            self.form_status.setText("No changes to save.")
            self.form_status.setStyleSheet(f"color: {FAINT};")
            return False

        self.form_status.setText("Changes saved and marked as accepted.")
        self.form_status.setStyleSheet(f"color: {GREEN};")
        return True

    def _show_problems(self, problems: list[str]) -> None:
        text = " ".join(str(problem) for problem in problems if problem)
        self.form_status.setText(text or "The change could not be saved.")
        self.form_status.setStyleSheet(f"color: {RED};")
        self.message.emit(text or "The change could not be saved.")

    def _save_edits(self) -> None:
        if not self._apply_edits():
            return
        file_id = self._current_id
        self.refresh()
        if file_id is not None:
            self._select_row(file_id)
        self.library_changed.emit()

    def _accept(self) -> None:
        if self._current_id is None:
            return
        file_id = self._current_id
        try:
            if not self._apply_edits_if_changed(file_id):
                return
            self.ctx.recommendations.accept(file_id)
        except Exception as exc:
            self.message.emit(f"Could not accept the recommendation: {exc}")
            return
        self.message.emit("Recommendation accepted; it is ready for the planner.")
        self.refresh()
        self._select_next()
        self.library_changed.emit()

    def _apply_edits_if_changed(self, file_id: int) -> bool:
        """Apply form edits when the user typed something without pressing Save."""

        detail = self._detail
        if detail is None or file_id != getattr(detail, "file_id", None):
            return True
        if (
            self.filename_edit.text().strip() == (detail.suggested_name or detail.filename)
            and self.folder_edit.text().strip().replace("\\", "/")
            == (detail.suggested_folder or detail.category or "")
            and (self.category_combo.currentText().strip() or UNCLASSIFIED)
            == (detail.category or "")
        ):
            return True
        return self._apply_edits()

    def _reject(self) -> None:
        if self._current_id is None:
            return
        accepted = QMessageBox.question(
            self,
            "Reject recommendation",
            "Reject the suggestion for this file and keep it for manual handling?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if accepted != QMessageBox.StandardButton.Yes:
            return
        try:
            self.ctx.recommendations.reject(self._current_id)
        except Exception as exc:
            self.message.emit(f"Could not reject the recommendation: {exc}")
            return
        self.message.emit("Recommendation rejected; the file stays where it is.")
        self.refresh()
        self._select_next()
        self.library_changed.emit()

    def _reset(self) -> None:
        if self._current_id is None:
            return
        try:
            self.ctx.recommendations.reset(self._current_id)
        except Exception as exc:
            self.message.emit(f"Could not reset the recommendation: {exc}")
            return
        self.message.emit("Recommendations returned to the pending state.")
        self.refresh()
        self.library_changed.emit()

    def _accept_all(self) -> None:
        suggestions = list(self._suggestions.values()) if hasattr(self, "_suggestions") else []
        if not suggestions:
            return
        if self._partial_suggestions:
            prompt = (
                f"Accept only the {len(suggestions)} loaded suggestions "
                f"(first {len(suggestions)} of {self._total_suggestions}); the rest stay pending. "
                "You will still approve the plan before any file is moved."
            )
        else:
            prompt = (
                f"Accept all {len(suggestions)} suggestions? You will still approve the plan "
                "before any file is moved."
            )
        accepted = QMessageBox.question(
            self,
            "Accept all recommendations",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if accepted != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self.ctx.recommendations.accept_many(
                [suggestion.file_id for suggestion in suggestions]
            )
        except Exception as exc:
            self.message.emit(f"Could not accept the recommendations: {exc}")
            return
        suffix = " (partial: only loaded suggestions)" if self._partial_suggestions else ""
        self.message.emit(f"{count} recommendation(s) accepted for planning{suffix}.")
        self.refresh()
        self.library_changed.emit()

    def _select_next(self) -> None:
        if self.suggestion_table.rowCount():
            self.suggestion_table.selectRow(0)

    def _detail_path(self) -> Path | None:
        if self._detail is None:
            return None
        return Path(str(getattr(self._detail, "path", "")))

    def _open_file(self) -> None:
        path = self._detail_path()
        if path is None:
            return
        if not path.exists():
            QMessageBox.warning(self, "File missing", f"{path} no longer exists.")
            return
        open_file(path)

    def _reveal_file(self) -> None:
        path = self._detail_path()
        if path is not None:
            reveal_in_folder(path)

    def _reveal_duplicate(self) -> None:
        raw = selected_data(self.duplicate_table)
        if raw:
            reveal_in_folder(Path(str(raw)))


__all__ = ["RecommendationsPage"]
