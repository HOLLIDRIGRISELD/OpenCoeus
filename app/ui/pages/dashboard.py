"""Dashboard: aggregate health and recent activity."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from app.ui.base import BasePage
from app.ui.theme import AMBER, FAINT, GREEN, RED
from app.ui.widgets import (
    Badge,
    Card,
    StatCard,
    add_actions,
    format_datetime,
    format_size,
    make_table,
    muted_label,
    scrollable_page,
    set_cell,
)


class DashboardPage(BasePage):
    def __init__(self, context) -> None:  # type: ignore[no-untyped-def]
        super().__init__(context)
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = scrollable_page(self)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top = add_actions(layout, refresh)
        top.insertWidget(
            0,
            muted_label("A local, private view of everything OpenCoeus has indexed."),
            1,
        )

        self.stats_grid = QGridLayout()
        self.stats_grid.setSpacing(12)
        self.cards: dict[str, StatCard] = {}
        self._stat_cards: list[StatCard] = []
        self._stat_columns: int | None = None
        specs = [
            ("total", "Files indexed", ""),
            ("analysed", "Analysed", ""),
            ("review", "Pending review", ""),
            ("organised", "Organised", ""),
            ("duplicates", "Duplicate sets", ""),
            ("failed", "Failed", ""),
        ]
        for key, caption, hint in specs:
            card = StatCard(caption, "0", hint)
            self.cards[key] = card
            self._stat_cards.append(card)
        layout.addLayout(self.stats_grid)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        categories_card = Card("Categories", subtitle="files by top-level category")
        self.category_table = make_table(["Category", "Files", "Share"], stretch=0)
        categories_card.add(self.category_table)
        columns.addWidget(categories_card, 2)

        activity_card = Card("Recent operations", subtitle="newest first")
        self.operation_table = make_table(
            ["#", "File", "Type", "Status", "When"],
            stretch=1,
        )
        activity_card.add(self.operation_table)
        columns.addWidget(activity_card, 3)
        layout.addLayout(columns, 1)

        self.capability_badge = Badge("ready", "completed")
        capability_card = Card(
            "Local capabilities",
            subtitle="optional components degrade gracefully",
            trailing=self.capability_badge,
        )
        self.capability_label = QLabel("")
        self.capability_label.setProperty("role", "surface")
        self.capability_label.setWordWrap(True)
        self.capability_label.setTextFormat(Qt.TextFormat.RichText)
        capability_card.add(self.capability_label)
        layout.addWidget(capability_card)

        self.empty_hint = QLabel(
            "Each session starts empty. On the Scanner page, choose a folder, scan it, "
            "then analyse the files."
        )
        self.empty_hint.setProperty("role", "surface")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._relayout_stats()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._relayout_stats()

    def _relayout_stats(self) -> None:
        """Wrap the six stat cards into 6/3/2/1 columns as space allows."""

        width = self.width()
        if width >= 1180:
            columns = 6
        elif width >= 820:
            columns = 3
        elif width >= 520:
            columns = 2
        else:
            columns = 1
        if columns == self._stat_columns:
            return
        self._stat_columns = columns
        while self.stats_grid.count():
            self.stats_grid.takeAt(0)
        for index, card in enumerate(self._stat_cards):
            self.stats_grid.addWidget(card, index // columns, index % columns)

    def refresh(self) -> None:
        stats = self.ctx.stats()
        counts = self.ctx.analyses.active_file_counts()
        stats.total_files = counts["total"]
        stats.total_bytes = counts["total_bytes"]
        stats.analysed = counts["analysed"]
        stats.pending_review = counts["pending_review"]
        stats.organised = counts["organised"]
        stats.duplicates = counts["duplicates"]
        stats.failed = counts["failed"]
        self.empty_hint.setVisible(stats.total_files == 0)
        self.cards["total"].set_value(stats.total_files, format_size(stats.total_bytes))
        analysed_pct = (
            f"{stats.analysed * 100 / stats.total_files:.0f}% of library"
            if stats.total_files
            else "no files yet"
        )
        self.cards["analysed"].set_value(stats.analysed, analysed_pct)
        self.cards["review"].set_value(stats.pending_review, "needs a human decision")
        self.cards["organised"].set_value(stats.organised, "approved and applied")
        self.cards["duplicates"].set_value(stats.duplicates, "identical SHA-256 groups")
        self.cards["failed"].set_value(stats.failed, "see logs for details")

        self.category_table.setRowCount(0)
        categories = sorted(stats.categories.items(), key=lambda item: item[1], reverse=True)
        total = max(1, sum(count for _, count in categories))
        for row, (category, count) in enumerate(categories):
            self.category_table.insertRow(row)
            set_cell(self.category_table, row, 0, category)
            set_cell(self.category_table, row, 1, str(count))
            set_cell(self.category_table, row, 2, f"{count * 100 / total:.0f}%")

        self.operation_table.setRowCount(0)
        for row, operation in enumerate(stats.recent_operations):
            self.operation_table.insertRow(row)
            set_cell(self.operation_table, row, 0, str(operation.id))
            set_cell(self.operation_table, row, 1, operation.filename)
            set_cell(self.operation_table, row, 2, operation.operation_type.replace("_", " "))
            set_cell(self.operation_table, row, 3, operation.status.replace("_", " "))
            self.operation_table.item(row, 3).setForeground(
                _qcolor(operation.status)
            )
            set_cell(self.operation_table, row, 4, format_datetime(operation.completed_at or operation.created_at))

        self._refresh_capabilities()

    def _refresh_capabilities(self) -> None:
        capabilities = list(self.ctx.capabilities(probe=False))
        parts: list[str] = []
        for capability in capabilities:
            colour = GREEN if capability.available else (RED if capability.required else AMBER)
            state = "ready" if capability.available else (
                "required" if capability.required else "optional, not configured"
            )
            label = html.escape(capability.label)
            detail = html.escape(capability.detail)
            parts.append(
                f'<span style="color:{colour};">● {label} — {state}</span>'
                f'<span style="color:{FAINT};"> ({detail})</span>'
            )
        missing_required = any(not item.available and item.required for item in capabilities)
        missing_optional = any(not item.available and not item.required for item in capabilities)
        status = "failed" if missing_required else ("pending" if missing_optional else "completed")
        summary = (
            "required missing"
            if missing_required
            else ("optional missing" if missing_optional else "all ready")
        )
        self.capability_badge.set_status(status)
        self.capability_badge.setText(summary)
        self.capability_label.setText("&nbsp;&nbsp;&nbsp;".join(parts))


def _qcolor(status: str):  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QColor

    from app.ui.theme import status_color

    return QColor(status_color(status))
