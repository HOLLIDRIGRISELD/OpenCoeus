"""Reusable widgets and small presentation helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import AMBER, FAINT, MUTED, SLATE_800, TEXT, status_badge_style


def format_size(size: int | None) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        return value.strftime("%d %b %Y, %H:%M")
    except (AttributeError, ValueError):
        return str(value)


def format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


class Card(QFrame):
    """A rounded surface with an optional title and trailing widget."""

    def __init__(
        self,
        title: str | None = None,
        *,
        subtitle: str | None = None,
        trailing: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(12)

        if title or subtitle or trailing:
            header = QHBoxLayout()
            header.setSpacing(8)
            texts = QVBoxLayout()
            texts.setSpacing(1)
            if title:
                label = QLabel(title)
                label.setProperty("role", "cardTitle")
                label.setWordWrap(True)
                texts.addWidget(label)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setProperty("role", "hint")
                sub.setWordWrap(True)
                texts.addWidget(sub)
            header.addLayout(texts, 1)
            if trailing is not None:
                header.addWidget(trailing)
            self.body.addLayout(header)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        self.body.addLayout(layout)


class StatCard(Card):
    """A large number with a caption used on the dashboard."""

    def __init__(self, caption: str, value: str = "0", hint: str = "") -> None:
        super().__init__()
        self.setMinimumHeight(104)
        self.body.setSpacing(4)
        self.value_label = QLabel(value)
        self.value_label.setProperty("role", "stat")
        self.caption_label = QLabel(caption)
        self.caption_label.setProperty("role", "muted")
        self.caption_label.setWordWrap(True)
        self.hint_label = QLabel(hint)
        self.hint_label.setProperty("role", "hint")
        self.hint_label.setWordWrap(True)
        self.body.addWidget(self.value_label)
        self.body.addWidget(self.caption_label)
        self.body.addWidget(self.hint_label)

    def set_value(self, value: int | str, hint: str | None = None) -> None:
        self.value_label.setText(str(value))
        if hint is not None:
            self.hint_label.setText(hint)


class ScrollContent(QWidget):
    """Scroll-area content that may shrink horizontally but not vertically.

    A plain ``QWidget`` reports its full size hint to ``QScrollArea``, which
    makes wide form layouts force a horizontal scrollbar even when the page is
    narrow. Reporting a zero width lets the scroll area fit the viewport, while
    the real (minimum) height keeps the page scrollable instead of clipping its
    contents when the window is short.
    """

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(0, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return QSize(0, super().minimumSizeHint().height())


class FlowLayout(QLayout):
    """A row of controls that wraps onto new lines instead of clipping text.

    Qt's box layouts force every child into a single row, so a long checkbox or
    button label is silently truncated as soon as the window narrows. This
    layout gives each child its full size hint and starts a new line when the
    current one runs out of room.
    """

    def __init__(self, spacing: int = 8) -> None:
        super().__init__()
        self._items: list[QLayoutItem] = []
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt naming
        self._items.append(item)

    def count(self) -> int:  # noqa: N802 - Qt naming
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt naming
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt naming
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:  # noqa: N802 - Qt naming
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt naming
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt naming
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt naming
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt naming
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt naming
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        line_height = 0
        for item in self._items:
            size = item.sizeHint()
            next_x = x + size.width() + self._spacing
            if next_x - self._spacing > rect.right() - margins.right() and line_height:
                x = rect.x() + margins.left()
                y += line_height + self._spacing
                line_height = 0
                next_x = x + size.width() + self._spacing
            if apply:
                item.setGeometry(QRect(QPoint(x, y), size))
            x = next_x
            line_height = max(line_height, size.height())
        return y + line_height - rect.y() + margins.bottom()


def scrollable_page(
    page: QWidget,
    *,
    spacing: int = 16,
    margin: tuple[int, int, int, int] = (24, 20, 24, 24),
) -> QVBoxLayout:
    """Install one scrolling body on a page and return its content layout.

    A page that lays its cards out directly on itself is at the mercy of the
    window height: the layout squeezes cards until labels and controls clip.
    Routing every page through this shell makes the content keep its natural
    height and scroll when the window is short.
    """

    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = ScrollContent()
    body = QVBoxLayout(content)
    body.setContentsMargins(*margin)
    body.setSpacing(spacing)
    scroll.setWidget(content)
    outer.addWidget(scroll)
    return body


class LineEdit(QLineEdit):
    """A line edit that starts at the beginning of a long value.

    Qt scrolls a field to the end when text is set programmatically, so a long
    path shows only its tail. These fields are mostly filled from the database,
    not typed one character at a time, so the start is the useful view.
    """

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        super().setText(text)
        self.setCursorPosition(0)


class Badge(QLabel):
    """A compact coloured status pill."""

    def __init__(self, text: str = "", status: str = "pending", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        self.setText(status.replace("_", " "))
        self.setStyleSheet(status_badge_style(status))


class AdaptiveTable(QTableWidget):
    """A read-only table whose columns always stay inside its viewport.

    Content-sized columns grow with their text but are capped at an equal share
    of the viewport. Long values elide with a tooltip, so a larger font or a
    narrower window shrinks columns instead of producing a horizontal
    scrollbar.
    """

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self._capping = False

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._cap_columns()

    def _cap_columns(self) -> None:
        if self._capping or self.columnCount() == 0:
            return
        width = self.viewport().width()
        if width <= 0:
            return
        header = self.horizontalHeader()
        limit = max(52, width // self.columnCount())
        self._capping = True
        try:
            if header.maximumSectionSize() != limit:
                header.setMaximumSectionSize(limit)
        finally:
            self._capping = False


def make_table(
    headers: list[str],
    *,
    stretch: int | None = None,
) -> AdaptiveTable:
    """Build a read-only table with adaptive, non-overflowing columns.

    Data columns size to their contents; the designated ``stretch`` column (or
    the last column when omitted) absorbs the remaining space. An
    :class:`AdaptiveTable` caps every column at an equal share of the viewport,
    so the grid never forces a horizontal scrollbar as fonts or widths change.
    """

    table = AdaptiveTable(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setMinimumSectionSize(52)
    stretch_index = len(headers) - 1 if stretch is None else stretch
    for column in range(table.columnCount()):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if column == stretch_index
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(column, mode)
    table.setMinimumHeight(120)
    return table


def set_cell(
    table: QTableWidget,
    row: int,
    column: int,
    text: object,
    *,
    color: str | None = None,
    tooltip: str | None = None,
    data: object | None = None,
    bold: bool = False,
) -> QTableWidgetItem:
    display = "" if text is None else str(text)
    item = QTableWidgetItem(display)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if color:
        item.setForeground(QColor(color))
    if tooltip:
        item.setToolTip(tooltip)
    elif len(display) > 40:
        item.setToolTip(display)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if bold:
        font = getattr(table, "_bold_font", None)
        if font is None:
            font = QFont()
            font.setBold(True)
            table._bold_font = font
        item.setFont(font)
    table.setItem(row, column, item)
    return item


def selected_data(table: QTableWidget) -> object | None:
    rows = table.selectionModel().selectedRows() if table.selectionModel() else []
    if not rows:
        return None
    item = table.item(rows[0].row(), 0)
    return item.data(Qt.ItemDataRole.UserRole) if item else None


def open_file(path: str | Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_folder(path: str | Path) -> bool:
    target = Path(path)
    folder = target if target.is_dir() else target.parent
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def hint_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


def muted_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(True)
    return label


def add_actions(layout: QVBoxLayout, *widgets: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    for widget in widgets:
        row.addWidget(widget)
    layout.insertLayout(0, row)
    return row


class EmptyState(QWidget):
    """A quiet placeholder shown when a table has no rows."""

    def __init__(self, title: str, detail: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 24, 12, 24)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setProperty("role", "cardTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        if detail:
            body = QLabel(detail)
            body.setProperty("role", "surface")
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.setWordWrap(True)
            layout.addWidget(body)


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background: {SLATE_800}; border: none; max-height: 1px;")
    line.setFixedHeight(1)
    return line


__all__ = [
    "add_actions",
    "AMBER",
    "AdaptiveTable",
    "Badge",
    "Card",
    "FAINT",
    "EmptyState",
    "FlowLayout",
    "LineEdit",
    "ScrollContent",
    "MUTED",
    "StatCard",
    "TEXT",
    "format_datetime",
    "format_percent",
    "format_size",
    "hint_label",
    "make_table",
    "muted_label",
    "open_file",
    "reveal_in_folder",
    "scrollable_page",
    "selected_data",
    "separator",
    "set_cell",
]
