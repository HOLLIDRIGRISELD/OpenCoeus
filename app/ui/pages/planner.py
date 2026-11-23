"""Organisation planner page: preview, approve and execute filesystem plans."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.domain.enums import PlanStatus
from app.ui.base import BasePage
from app.ui.theme import ACCENT, AMBER, FAINT, GREEN, MUTED, RED, confidence_color
from app.ui.widgets import (
    Card,
    EmptyState,
    FlowLayout,
    format_datetime,
    format_percent,
    hint_label,
    make_table,
    muted_label,
    scrollable_page,
    selected_data,
    separator,
    set_cell,
)


class PlannerPage(BasePage):
    """Two stages of the same safety model: preview, then explicit approval."""

    library_changed = Signal()
    navigate = Signal(str)

    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._previews = None
        self._current_plan_id: int | None = None
        self._execute_task = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = scrollable_page(self)

        top = QHBoxLayout()
        self.root_label = muted_label("")
        top.addWidget(self.root_label, 1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)
        layout.addWidget(separator())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_preview_tab(), "Preview")
        self.tabs.addTab(self._build_plans_tab(), "Saved plans")
        layout.addWidget(self.tabs, 1)

    def _build_preview_tab(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(12)

        body.addWidget(
            hint_label(
                "A preview is read-only. Saving it creates a draft plan; nothing moves until "
                "you load the plan and approve execution."
            )
        )
        counts = FlowLayout(spacing=18)
        self.summary_labels: dict[str, QLabel] = {}
        self._summary_captions: dict[str, str] = {}
        for key, caption in (
            ("total", "Actions"),
            ("renames", "Renames"),
            ("moves", "Moves"),
            ("new_folders", "New folders"),
            ("conflicts", "Blocked"),
            ("needs_review", "Below review"),
        ):
            label = QLabel(f"<span style='color:{MUTED}'>{caption}</span> 0")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            self.summary_labels[key] = label
            self._summary_captions[key] = caption
            counts.addWidget(label)
        body.addLayout(counts)

        self.preview_note = hint_label("")
        body.addWidget(self.preview_note)

        self.preview_table = make_table(
            ["File", "Action", "Destination", "Confidence", "Status"],
            stretch=2,
        )
        body.addWidget(self.preview_table, 1)
        self.empty_state = EmptyState(
            "Nothing to preview", "Scan and analyse files, then review suggestions."
        )
        self.empty_state.setVisible(False)
        body.addWidget(self.empty_state)

        buttons = QHBoxLayout()
        self.rebuild_button = QPushButton("Rebuild preview")
        self.rebuild_button.clicked.connect(self.refresh)
        self.preview_limit = QSpinBox()
        self.preview_limit.setRange(1, 5000)
        self.preview_limit.setValue(500)
        self.preview_limit.setSingleStep(100)
        self.preview_limit.setSuffix(" files")
        self.preview_limit.setToolTip(
            "Maximum suggestions used for the preview and the saved plan. "
            "Large values take longer to rebuild."
        )
        self.save_button = QPushButton("Save as draft plan")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(self._save_plan)
        buttons.addWidget(self.rebuild_button)
        buttons.addWidget(muted_label("Preview limit"))
        buttons.addWidget(self.preview_limit)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        body.addLayout(buttons)
        return page

    def _build_plans_tab(self) -> QWidget:
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(12)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        plans_card = Card("Saved plans", subtitle="newest first")
        self.plans_table = make_table(
            ["ID", "Status", "Items", "Root", "Created"],
            stretch=3,
        )
        self.plans_table.itemSelectionChanged.connect(self._plan_selected)
        plans_card.add(self.plans_table)
        splitter.addWidget(plans_card)

        detail_card = Card("Plan detail")
        self.plan_summary = QLabel("")
        self.plan_summary.setTextFormat(Qt.TextFormat.RichText)
        self.plan_summary.setWordWrap(True)
        detail_card.add(self.plan_summary)

        self.plan_items_table = make_table(
            ["File", "Action", "Destination", "Confidence", "Item status"],
            stretch=2,
        )
        detail_card.add(self.plan_items_table)

        actions = QHBoxLayout()
        self.new_plan_button = QPushButton("New plan from pending")
        self.new_plan_button.setToolTip(
            "Clear this selection and rebuild a preview from the current pending suggestions."
        )
        self.new_plan_button.clicked.connect(self._new_plan)
        self.approve_button = QPushButton("Approve plan")
        self.approve_button.clicked.connect(self._approve_plan)
        self.execute_button = QPushButton("Execute approved plan…")
        self.execute_button.setProperty("primary", True)
        self.execute_button.clicked.connect(self._execute_plan)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(
            lambda: self._execute_task and self._execute_task.cancel()
        )
        self.revalidate_button = QPushButton("Revalidate plan")
        self.revalidate_button.setToolTip(
            "Recheck an interrupted plan so it can be approved and retried."
        )
        self.revalidate_button.clicked.connect(self._revalidate_plan)
        self.approve_button.setEnabled(False)
        self.execute_button.setEnabled(False)
        self.revalidate_button.setEnabled(False)
        actions.addWidget(self.new_plan_button)
        actions.addWidget(self.approve_button)
        actions.addWidget(self.execute_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.revalidate_button)
        actions.addStretch(1)
        detail_card.add_layout(actions)

        self.execute_progress = QProgressBar()
        self.execute_progress.setRange(0, 100)
        self.execute_progress.setValue(0)
        self.execute_progress.setFixedHeight(8)
        self.execute_progress.setVisible(False)
        detail_card.add(self.execute_progress)

        self.report_browser = QTextBrowser()
        self.report_browser.setMinimumHeight(120)
        self.report_browser.setHtml(
            f"<p style='color:{MUTED}'>Select a plan to review it, or use the Preview tab "
            "to create one.</p>"
        )
        detail_card.add(self.report_browser)
        splitter.addWidget(detail_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        body.addWidget(splitter, 1)
        return page

    def refresh(self) -> None:
        self._set_busy(True)
        try:
            self._build_preview()
            self._refresh_plans()
        finally:
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        blocked = busy or self.has_running_tasks()
        self.refresh_button.setEnabled(not blocked)
        self.rebuild_button.setEnabled(not blocked)
        self.new_plan_button.setEnabled(not blocked)
        if blocked:
            self.revalidate_button.setEnabled(False)

    def _build_preview(self) -> None:
        try:
            self._previews = self.ctx.organisation.build_preview(
                limit=self.preview_limit.value()
            )
        except Exception as exc:
            self._previews = None
            self.preview_note.setText(f"Could not build a preview: {exc}")
            self.preview_table.setRowCount(0)
            self.empty_state.setVisible(True)
            return

        draft = self._previews.draft
        summary = draft.summary
        self.root_label.setText(f"Organisation root: {self.ctx.organisation.organisation_root()}")
        for key, label in self.summary_labels.items():
            value = getattr(summary, key, 0)
            caption = self._summary_captions.get(key, key)
            value_colour = RED if key == "conflicts" and value else (ACCENT if value else FAINT)
            label.setText(
                f"<span style='color:{MUTED}'>{caption}</span> "
                f"<b style='color:{value_colour}'>{value}</b>"
            )
            if key == "conflicts":
                label.setToolTip("Blocked actions are never executed.")

        notes = list(dict.fromkeys(self._previews.notes))
        self.preview_note.setText(
            " ".join(notes)
            if notes
            else "No conflicts found. Review the destinations before saving a plan."
        )

        self.preview_table.setRowCount(0)
        for row, action in enumerate(draft.actions):
            self.preview_table.insertRow(row)
            set_cell(
                self.preview_table,
                row,
                0,
                action.original_name,
                tooltip=str(action.source_path),
                data=action.file_id,
            )
            set_cell(self.preview_table, row, 1, action.action.value.replace("_", " "))
            set_cell(
                self.preview_table,
                row,
                2,
                str(action.destination_path),
                tooltip="\n".join(action.notes),
            )
            set_cell(
                self.preview_table,
                row,
                3,
                format_percent(action.confidence),
                color=confidence_color(action.confidence),
            )
            if action.conflict:
                set_cell(self.preview_table, row, 4, action.conflict, color=RED)
            else:
                set_cell(self.preview_table, row, 4, "ready", color=GREEN)

        self.empty_state.setVisible(not draft.actions)
        self.save_button.setEnabled(bool(draft.actions))

    def _refresh_plans(self) -> None:
        try:
            plans = self.ctx.organisation.list_plans(limit=50)
        except Exception as exc:
            self.message.emit(f"Could not load plans: {exc}")
            return
        self.plans_table.setRowCount(0)
        for row, plan in enumerate(plans):
            self.plans_table.insertRow(row)
            set_cell(self.plans_table, row, 0, str(plan["id"]), data=int(plan["id"]))
            set_cell(self.plans_table, row, 1, str(plan["status"]).replace("_", " "))
            set_cell(self.plans_table, row, 2, str(plan["item_count"]))
            set_cell(
                self.plans_table,
                row,
                3,
                str(plan["root_path"]),
                tooltip=str(plan["root_path"]),
            )
            set_cell(self.plans_table, row, 4, format_datetime(plan.get("created_at")))

        if self._current_plan_id is not None:
            for row in range(self.plans_table.rowCount()):
                item = self.plans_table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == self._current_plan_id:
                    self.plans_table.selectRow(row)
                    break
        elif plans:
            self.plans_table.selectRow(0)
        else:
            self._current_plan_id = None
            self.plan_items_table.setRowCount(0)
            self.plan_summary.setText(
                f"<span style='color:{MUTED}'>No saved plans yet.</span>"
            )
            self._set_plan_buttons(None)

    def _plan_selected(self) -> None:
        raw = selected_data(self.plans_table)
        if raw is None:
            self._current_plan_id = None
            self._set_plan_buttons(None)
            return
        self._current_plan_id = int(raw)
        self._load_plan(self._current_plan_id)

    def _load_plan(self, plan_id: int) -> None:
        self.plan_items_table.setRowCount(0)
        self.report_browser.setHtml(
            f"<p style='color:{MUTED}'>Select a plan to review it, or use the Preview tab "
            "to create one.</p>"
        )
        try:
            plan = self.ctx.organisation.plan(plan_id)
            items = self.ctx.organisation.items(plan_id)
            summary = self.ctx.organisation.summary(plan_id, items)
        except Exception as exc:
            self.message.emit(f"Could not load plan {plan_id}: {exc}")
            return
        if plan is None:
            return
        status = str(plan["status"])
        report = (
            f"<p style='color:{MUTED}'>Plan #{plan_id} · "
            f"{html.escape(status.replace('_', ' '))}.</p>"
        )
        if status == PlanStatus.COMPLETED.value:
            report += (
                " This plan has already been executed. "
                "See the History page to undo individual operations."
            )
        self.report_browser.setHtml(report)
        self.plan_summary.setText(
            f"<b>Plan #{plan_id}</b> · status <b>{html.escape(status.replace('_', ' '))}</b> · "
            f"{len(items)} item(s), "
            f"<span style='color:{RED if summary.conflicts else GREEN}'>"
            f"{summary.conflicts} blocked</span> · "
            f"<span style='color:{MUTED}'>{html.escape(str(plan['root_path']))}</span>"
        )
        self.plan_items_table.setRowCount(0)
        for row, item in enumerate(items):
            self.plan_items_table.insertRow(row)
            set_cell(self.plan_items_table, row, 0, item.filename)
            set_cell(self.plan_items_table, row, 1, item.action.replace("_", " "))
            set_cell(
                self.plan_items_table,
                row,
                2,
                item.destination_path,
                tooltip="\n".join(item.notes),
            )
            set_cell(
                self.plan_items_table,
                row,
                3,
                format_percent(item.confidence),
                color=confidence_color(item.confidence),
            )
            if item.conflict:
                set_cell(self.plan_items_table, row, 4, item.conflict, color=RED)
            else:
                set_cell(
                    self.plan_items_table,
                    row,
                    4,
                    item.status,
                    color=GREEN if item.status == "completed" else MUTED,
                )
        self._set_plan_buttons(status)

    def _set_plan_buttons(self, status: str | None) -> None:
        self.approve_button.setEnabled(status == PlanStatus.DRAFT.value)
        self.execute_button.setEnabled(status == PlanStatus.APPROVED.value)
        self.revalidate_button.setEnabled(
            status
            in {
                PlanStatus.EXECUTING.value,
                PlanStatus.FAILED.value,
                PlanStatus.PARTIALLY_COMPLETED.value,
                PlanStatus.REVALIDATION_REQUIRED.value,
            }
        )

    def _new_plan(self) -> None:
        self.plans_table.clearSelection()
        self._current_plan_id = None
        self._set_plan_buttons(None)
        self.tabs.setCurrentIndex(0)
        self._build_preview()

    def _save_plan(self) -> None:
        try:
            plan_id = self.ctx.organisation.create_plan(limit=self.preview_limit.value())
        except Exception as exc:
            self.message.emit(f"Could not save the plan: {exc}")
            QMessageBox.warning(self, "Nothing to plan", str(exc))
            return
        self._current_plan_id = plan_id
        self.message.emit(f"Draft plan #{plan_id} saved. Review it, then approve.")
        self.tabs.setCurrentIndex(1)
        self.refresh()
        self.library_changed.emit()

    def _approve_plan(self) -> None:
        if self._current_plan_id is None:
            return
        plan_id = self._current_plan_id
        try:
            self.ctx.organisation.approve(plan_id)
        except Exception as exc:
            self.message.emit(f"Could not approve plan {plan_id}: {exc}")
            return
        self.message.emit(f"Plan #{plan_id} approved. It can now be executed.")
        self._load_plan(plan_id)
        self._refresh_plans()

    def _revalidate_plan(self) -> None:
        if self._current_plan_id is None:
            return
        plan_id = self._current_plan_id
        answer = QMessageBox.question(
            self,
            "Revalidate this plan?",
            "Recheck every unfinished item against the current files, then return "
            "the plan to draft so it can be approved again?\n\n"
            "Completed operations are left untouched. Nothing will be moved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            summary = self.ctx.organisation.revalidate(plan_id)
        except Exception as exc:
            self.message.emit(f"Could not revalidate plan {plan_id}: {exc}")
            QMessageBox.warning(self, "Revalidation failed", str(exc))
            return
        self.message.emit(
            f"Plan #{plan_id} is a draft again: {summary.total} action(s), "
            f"{summary.conflicts} conflict(s)."
        )
        self._load_plan(plan_id)
        self._refresh_plans()

    def _execute_plan(self) -> None:
        if self._current_plan_id is None:
            return
        plan_id = self._current_plan_id
        plan = self.ctx.organisation.plan(plan_id)
        if plan is None:
            return
        summary = self.ctx.organisation.summary(plan_id)
        answer = QMessageBox.warning(
            self,
            "Apply this plan?",
            f"Apply {summary.total - summary.conflicts} action(s) to the filesystem?\n\n"
            f"Root: {plan['root_path']}\n"
            f"Blocked and conflicting items are skipped automatically.\n\n"
            "Every change is logged and can be undone from the History page.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self.approve_button.setEnabled(False)
        self.execute_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.execute_progress.setVisible(True)
        self.execute_progress.setRange(0, 0)
        self.report_browser.setHtml(
            f"<p style='color:{AMBER}'>Executing plan #{plan_id}…</p>"
        )

        def work(progress, cancel):  # type: ignore[no-untyped-def]
            return self.ctx.organisation.execute(
                plan_id, progress=progress, cancel=cancel
            )

        self._execute_task = self.run_task(
            work,
            label=f"Plan #{plan_id}",
            on_done=self._execute_done,
            on_failed=self._execute_failed,
            on_cancelled=self._execute_cancelled,
            on_progress=self._on_progress,
        )

    def _on_progress(self, event: object) -> None:
        current = getattr(event, "current", 0)
        total = getattr(event, "total", 0)
        if total:
            self.execute_progress.setRange(0, total)
            self.execute_progress.setValue(current)
        message = getattr(event, "message", "")
        if message:
            self.message.emit(message)

    def _execute_done(self, report: object) -> None:
        self._execute_task = None
        self._set_busy(False)
        self.cancel_button.setEnabled(False)
        self.execute_progress.setVisible(False)
        self.execute_progress.setRange(0, 100)
        completed = getattr(report, "completed", [])
        failed = getattr(report, "failed", [])
        skipped = getattr(report, "skipped", [])
        summary = getattr(report, "summary", "")
        duration = getattr(report, "duration_seconds", 0.0)
        parts = [
            "<h3 style='margin-top:0'>Execution finished</h3>",
            f"<p><b>{html.escape(str(summary))}</b> in {duration:.1f}s.</p>",
        ]
        if completed:
            parts.append(f"<h4 style='color:{GREEN}'>Completed</h4><ul>")
            for result in completed[:20]:
                parts.append(
                    f"<li>{html.escape(result.source_path.name)} → "
                    f"{html.escape(str(result.destination_path))}</li>"
                )
            parts.append("</ul>")
        if skipped:
            parts.append(f"<h4 style='color:{AMBER}'>Skipped</h4><ul>")
            for result in skipped[:20]:
                parts.append(
                    f"<li>{html.escape(result.source_path.name)}: "
                    f"{html.escape(str(result.message or ''))}</li>"
                )
            parts.append("</ul>")
        if failed:
            parts.append(f"<h4 style='color:{RED}'>Failed</h4><ul>")
            for result in failed[:20]:
                parts.append(
                    f"<li>{html.escape(result.source_path.name)}: "
                    f"{html.escape(str(result.message or ''))}</li>"
                )
            parts.append("</ul>")
        self.message.emit(f"Plan execution: {summary}.")
        if self._current_plan_id is not None:
            self._load_plan(self._current_plan_id)
        self._refresh_plans()
        self.report_browser.setHtml("".join(parts))
        self.library_changed.emit()

    def _execute_failed(self, error: str) -> None:
        self._execute_task = None
        self._set_busy(False)
        self.cancel_button.setEnabled(False)
        self.execute_progress.setVisible(False)
        self.execute_progress.setRange(0, 100)
        if self._current_plan_id is not None:
            self._load_plan(self._current_plan_id)
        self._refresh_plans()
        self.report_browser.setHtml(
            f"<p style='color:{RED}'>Execution failed: {html.escape(error)}</p>"
        )
        QMessageBox.critical(self, "Plan execution failed", error)
        self.library_changed.emit()

    def _execute_cancelled(self) -> None:
        self._execute_task = None
        self._set_busy(False)
        self.cancel_button.setEnabled(False)
        self.execute_progress.setVisible(False)
        self.execute_progress.setRange(0, 100)
        if self._current_plan_id is not None:
            self._load_plan(self._current_plan_id)
        self._refresh_plans()
        self.report_browser.setHtml(
            f"<p style='color:{AMBER}'>Execution cancelled. Completed operations are "
            "recorded and can be undone from History.</p>"
        )
        self.library_changed.emit()


__all__ = ["PlannerPage"]
