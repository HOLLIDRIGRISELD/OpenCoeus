from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


# HELPERS

def section_title(text: str) -> QLabel:
    from ..theme import COLORS
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {COLORS['text']}; font-size: 18px; font-weight: bold; padding: 0;"
    )
    return lbl


def section_sub(text: str) -> QLabel:
    from ..theme import COLORS
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {COLORS['text2']}; font-size: 12px; padding: 0;"
    )
    lbl.setWordWrap(True)
    return lbl


def status_badge(text: str, color: str, bg_color: str) -> QLabel:
    """Create a small colored status badge label."""
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(False)
    label.setStyleSheet(
        f"""
        color: {color};
        background-color: {bg_color};
        border-radius: 4px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: bold;
        border: none;
        """
    )
    return label


def truncate_path(path: str, max_parts: int = 3) -> str:
    if not path:
        return ""
    parts = Path(path).parts
    if len(parts) <= max_parts:
        return path
    return ".../" + "/".join(parts[-max_parts:])


def fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1048576:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1048576:.1f} MB"


# CARD TABLE

class CardRow(QFrame):
    """A single row in the card table, styled as a card."""
    clicked = pyqtSignal(int)

    def __init__(self, row_index: int, parent=None):
        super().__init__(parent)
        self.row_index = row_index
        self._selected = False
        from ..theme import COLORS
        self._COLORS = COLORS
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._base_style())

    def _base_style(self) -> str:
        c = self._COLORS
        return f"""
            CardRow {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 0px;
            }}
            CardRow:hover {{
                background-color: {c['surface2']};
                border-color: {c['border_light']};
            }}
        """

    def _selected_style(self) -> str:
        c = self._COLORS
        return f"""
            CardRow {{
                background-color: {c['surface3']};
                border: 1px solid {c['accent']};
                border-radius: 8px;
                padding: 0px;
            }}
        """

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setStyleSheet(self._selected_style() if selected else self._base_style())

    def mousePressEvent(self, event):
        self.clicked.emit(self.row_index)
        super().mousePressEvent(event)


class CardTable(QWidget):
    """A modern card-based table replacing qtablewidget.
    Each row is a styled card with proper layout and selection."""
    row_clicked = pyqtSignal(int)
    row_double_clicked = pyqtSignal(int)

    def __init__(self, headers: list[str], column_widths: list[int] | None = None,
                 parent=None):
        super().__init__(parent)
        from ..theme import COLORS
        self._COLORS = COLORS
        self._headers = headers
        self._column_widths = column_widths or []
        self._rows: list[CardRow] = []
        self._selected_index: int = -1

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # HEADER BAR.
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {self._COLORS['surface2']};
                border: 1px solid {self._COLORS['border']};
                border-radius: 8px 8px 0 0;
                border-bottom: 2px solid {self._COLORS['border']};
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(0)

        self._header_labels: list[QLabel] = []
        for i, h in enumerate(self._headers):
            lbl = QLabel(h.upper())
            lbl.setStyleSheet(f"""
                color: {self._COLORS['text2']};
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
                background: transparent;
                border: none;
            """)
            if i < len(self._column_widths):
                lbl.setMinimumWidth(self._column_widths[i])
                lbl.setMaximumWidth(self._column_widths[i])
            self._header_labels.append(lbl)
            header_layout.addWidget(lbl)

        root.addWidget(header_frame)

        # SCROLL AREA FOR ROWS.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: 1px solid {self._COLORS['border']};
                border-top: none;
                border-radius: 0 0 8px 8px;
            }}
            QScrollBar:vertical {{
                background: {self._COLORS['surface']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {self._COLORS['surface3']};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._COLORS['border_light']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self._rows_container = QWidget()
        self._rows_container.setStyleSheet(f"background-color: {self._COLORS['surface']};")
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch()

        self._scroll.setWidget(self._rows_container)
        root.addWidget(self._scroll)

    def setRowCount(self, count: int):
        """Remove all existing rows."""
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self._selected_index = -1

    def addRow(self, widgets: list[tuple[str, QWidget | None]], tooltips: list[str] | None = None):
        """
        Add a row. widgets is a list of (text, optional_widget) tuples.
        If widget is provided, it's used instead of a text label (for badges etc).
        """
        row_index = len(self._rows)
        row = CardRow(row_index)
        row.clicked.connect(self._on_row_clicked)
        row.double_clicked = self.row_double_clicked

        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)

        for i, (text, widget) in enumerate(widgets):
            if widget is not None:
                cell = widget
            else:
                cell = QLabel(text)
                cell.setStyleSheet(f"""
                    color: {self._COLORS['text']};
                    font-size: 12px;
                    padding: 0 8px;
                    background: transparent;
                    border: none;
                """)
                cell.setWordWrap(False)
                if tooltips and i < len(tooltips) and tooltips[i]:
                    cell.setToolTip(tooltips[i])

            if i < len(self._column_widths):
                cell.setMinimumWidth(self._column_widths[i])
                cell.setMaximumWidth(self._column_widths[i])

            layout.addWidget(cell)

        # CONNECT DOUBLE CLICK.
        row.mouseDoubleClickEvent = lambda e, idx=row_index: self.row_double_clicked.emit(idx)

        self._rows.append(row)
        # INSERT BEFORE THE STRETCH.
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def clear(self):
        """Remove all rows."""
        self.setRowCount(0)

    def _on_row_clicked(self, index: int):
        # DESELECT PREVIOUS.
        if 0 <= self._selected_index < len(self._rows):
            self._rows[self._selected_index].set_selected(False)
        # SELECT NEW.
        self._selected_index = index
        if 0 <= index < len(self._rows):
            self._rows[index].set_selected(True)
        self.row_clicked.emit(index)

    def selectedRows(self) -> list[int]:
        """Return list of selected row indices (single select for now)."""
        if self._selected_index >= 0:
            return [self._selected_index]
        return []

    def rowCount(self) -> int:
        return len(self._rows)

    def setRowHidden(self, row: int, hidden: bool):
        """Show or hide a row by index."""
        if 0 <= row < len(self._rows):
            self._rows[row].setVisible(not hidden)

    def cellWidget(self, row: int, col: int) -> QWidget | None:
        """Get the widget at a specific cell (for badge access)."""
        if row < 0 or row >= len(self._rows):
            return None
        row_widget = self._rows[row]
        layout = row_widget.layout()
        if layout and col < layout.count():
            item = layout.itemAt(col)
            if item and item.widget():
                return item.widget()
        return None

    def item(self, row: int, col: int) -> QLabel | None:
        """Get the label at a specific cell."""
        return self.cellWidget(row, col)

    def setCellWidget(self, row: int, col: int, widget: QWidget):
        """Replace the widget at a specific cell."""
        if row < 0 or row >= len(self._rows):
            return
        row_widget = self._rows[row]
        layout = row_widget.layout()
        if layout and col < layout.count():
            old_item = layout.itemAt(col)
            old_w = old_item.widget() if old_item else None
            if old_w is not None:
                layout.removeWidget(old_w)
                old_w.setParent(None)
                old_w.deleteLater()
            # APPLY COLUMN WIDTH CONSTRAINTS TO THE NEW WIDGET.
            if col < len(self._column_widths):
                widget.setMinimumWidth(self._column_widths[col])
                widget.setMaximumWidth(self._column_widths[col])
            layout.insertWidget(col, widget)

    def removeRow(self, row: int):
        """Remove a single row by index."""
        if row < 0 or row >= len(self._rows):
            return
        rw = self._rows.pop(row)
        rw.setParent(None)
        rw.deleteLater()
        # REINDEX REMAINING ROWS.
        for i, r in enumerate(self._rows):
            r.row_index = i


# CARD TREE

class _CardTreeRow(QFrame):
    """A single row in the card tree, styled as a card."""
    clicked = pyqtSignal(int)

    def __init__(self, row_index: int, parent=None):
        super().__init__(parent)
        self.row_index = row_index
        self._selected = False
        from ..theme import COLORS
        self._COLORS = COLORS
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._base_style())

    def _base_style(self) -> str:
        c = self._COLORS
        return f"""
            _CardTreeRow {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 0px;
            }}
            _CardTreeRow:hover {{
                background-color: {c['surface2']};
                border-color: {c['border_light']};
            }}
        """

    def _selected_style(self) -> str:
        c = self._COLORS
        return f"""
            _CardTreeRow {{
                background-color: {c['surface3']};
                border: 1px solid {c['accent']};
                border-radius: 8px;
                padding: 0px;
            }}
        """

    def set_selected(self, selected: bool):
        self._selected = selected
        self.setStyleSheet(self._selected_style() if selected else self._base_style())

    def mousePressEvent(self, event):
        self.clicked.emit(self.row_index)
        super().mousePressEvent(event)


class CardTree(QWidget):
    """
    A modern card-based tree widget.
    Each row is a styled card with hierarchy (indentation, expand/collapse)
    and tri-state checkboxes for exclusion.
    """

    row_clicked = pyqtSignal(int)
    check_changed = pyqtSignal(int, bool)  # ROW_INDEX, IS_CHECKED

    INDENT_PX = 24  # PIXELS PER DEPTH LEVEL.

    # CLASSIFICATION COLORS.
    _CLASS_COLORS = {
        "code":     ("#61afef", "#1a2332"),
        "data":     ("#e5c07b", "#2d2817"),
        "document": ("#98c379", "#1a2d1a"),
        "media":    ("#c678dd", "#2a1a2e"),
        "archive":  ("#e06c75", "#2d1a1c"),
    }

    def __init__(self, headers: list[str], column_widths: list[int] | None = None,
                 parent=None):
        super().__init__(parent)
        from ..theme import COLORS
        self._COLORS = COLORS
        self._headers = headers
        self._column_widths = column_widths or []
        self._rows: list[_CardTreeRow] = []
        self._selected_index: int = -1

        # NODE DATA: ONE ENTRY PER ROW.
        # {path, depth, has_children, expanded, child_indices, parent_index, cb_ref}
        self._node_data: list[dict] = []

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # HEADER BAR.
        header_frame = QFrame()
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {self._COLORS['surface2']};
                border: 1px solid {self._COLORS['border']};
                border-radius: 8px 8px 0 0;
                border-bottom: 2px solid {self._COLORS['border']};
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(0)

        self._header_labels: list[QLabel] = []
        for i, h in enumerate(self._headers):
            lbl = QLabel(h.upper())
            lbl.setStyleSheet(f"""
                color: {self._COLORS['text2']};
                font-size: 11px;
                font-weight: bold;
                padding: 0 8px;
                background: transparent;
                border: none;
            """)
            if i < len(self._column_widths):
                lbl.setMinimumWidth(self._column_widths[i])
                lbl.setMaximumWidth(self._column_widths[i])
            self._header_labels.append(lbl)
            header_layout.addWidget(lbl)

        root.addWidget(header_frame)

        # SCROLL AREA FOR ROWS.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: 1px solid {self._COLORS['border']};
                border-top: none;
                border-radius: 0 0 8px 8px;
            }}
            QScrollBar:vertical {{
                background: {self._COLORS['surface']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {self._COLORS['surface3']};
                min-height: 30px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self._COLORS['border_light']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        self._rows_container = QWidget()
        self._rows_container.setStyleSheet(f"background-color: {self._COLORS['surface']};")
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch()

        self._scroll.setWidget(self._rows_container)
        root.addWidget(self._scroll)

    # STYLING HELPERS

    def _checkbox_qss(self, checked: bool) -> str:
        """Return qss for a custom checkbox button."""
        if checked:
            bg = self._COLORS['accent']
            border = self._COLORS['accent']
        else:
            bg = self._COLORS['surface']
            border = self._COLORS['border_light']
        return f"""
            QPushButton {{
                background-color: {bg};
                border: 2px solid {border};
                border-radius: 4px;
                color: {self._COLORS['bg']};
                font-size: 11px;
                font-weight: bold;
                padding: 0;
            }}
            QPushButton:hover {{
                border-color: {self._COLORS['accent']};
            }}
        """

    def _arrow_qss(self) -> str:
        """Return qss for expand/collapse arrow."""
        return f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {self._COLORS['text2']};
                font-size: 10px;
                padding: 0;
            }}
            QPushButton:hover {{
                color: {self._COLORS['accent']};
            }}
        """

    # PUBLIC API

    def clear(self):
        """Remove all rows and reset state."""
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        self._node_data.clear()
        self._selected_index = -1

    def addNode(self, name: str, path: str, depth: int, file_count: int,
                total_size: int, classification: str | None, excluded: bool,
                has_children: bool) -> int:
        """Add a folder node as a row. returns the row index."""
        row_index = len(self._rows)
        row = _CardTreeRow(row_index)
        row.clicked.connect(self._on_row_clicked)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 6, 12, 6)
        layout.setSpacing(0)

        # INDENT SPACER + EXPAND/COLLAPSE ARROW.
        indent_px = depth * self.INDENT_PX
        spacer = QWidget()
        spacer.setFixedWidth(indent_px)
        spacer.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(spacer)

        arrow_btn = QPushButton()
        arrow_btn.setFixedWidth(20)
        arrow_btn.setFlat(True)
        arrow_btn.setStyleSheet(self._arrow_qss())
        if has_children:
            arrow_btn.setText("▶")
            arrow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            arrow_btn.clicked.connect(
                lambda checked, idx=row_index: self._toggle_expand(idx)
            )
        else:
            arrow_btn.setCursor(Qt.CursorShape.ArrowCursor)
        layout.addWidget(arrow_btn)

        # CHECKBOX.
        cb = QPushButton()
        cb.setCheckable(True)
        cb.setChecked(not excluded)
        cb.setFixedSize(20, 20)
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet(self._checkbox_qss(not excluded))
        cb.clicked.connect(
            lambda checked, idx=row_index: self._on_checkbox_clicked(idx, checked)
        )
        layout.addWidget(cb)

        # FOLDER NAME.
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"""
            color: {self._COLORS['text']};
            font-size: 13px;
            padding: 0 8px;
            background: transparent;
            border: none;
        """)
        name_lbl.setWordWrap(False)
        name_lbl.setToolTip(path)
        if 2 < len(self._column_widths):
            name_lbl.setMinimumWidth(self._column_widths[2])
            name_lbl.setMaximumWidth(self._column_widths[2])
        layout.addWidget(name_lbl)

        # FILE COUNT.
        count_lbl = QLabel(str(file_count) if file_count else "—")
        count_lbl.setStyleSheet(f"""
            color: {self._COLORS['text2']};
            font-size: 12px;
            padding: 0 8px;
            background: transparent;
            border: none;
        """)
        if 3 < len(self._column_widths):
            count_lbl.setMinimumWidth(self._column_widths[3])
            count_lbl.setMaximumWidth(self._column_widths[3])
        layout.addWidget(count_lbl)

        # SIZE.
        size_lbl = QLabel(fmt_size(total_size) if total_size else "—")
        size_lbl.setStyleSheet(f"""
            color: {self._COLORS['text2']};
            font-size: 12px;
            padding: 0 8px;
            background: transparent;
            border: none;
        """)
        if 4 < len(self._column_widths):
            size_lbl.setMinimumWidth(self._column_widths[4])
            size_lbl.setMaximumWidth(self._column_widths[4])
        layout.addWidget(size_lbl)

        # CLASSIFICATION BADGE.
        class_color, class_bg = self._CLASS_COLORS.get(
            classification or "", (self._COLORS['text2'], self._COLORS['surface3'])
        )
        class_badge = status_badge(
            (classification or "—").upper(), class_color, class_bg
        )
        if 5 < len(self._column_widths):
            class_badge.setMinimumWidth(self._column_widths[5])
            class_badge.setMaximumWidth(self._column_widths[5])
        layout.addWidget(class_badge)

        # EXCLUSION STATUS BADGE.
        if excluded:
            excl_badge = status_badge(
                "EXCLUDED", self._COLORS['red'], self._COLORS.get('red_bg', '#3b1518')
            )
        else:
            excl_badge = status_badge(
                "INCLUDED", self._COLORS['green'], self._COLORS.get('green_bg', '#14302a')
            )
        if 6 < len(self._column_widths):
            excl_badge.setMinimumWidth(self._column_widths[6])
            excl_badge.setMaximumWidth(self._column_widths[6])
        layout.addWidget(excl_badge)

        # STORE NODE DATA (CHILDREN COMPUTED IN finalizeHierarchy).
        self._node_data.append({
            "path": path,
            "depth": depth,
            "has_children": has_children,
            "expanded": True,
            "child_indices": [],
            "parent_index": -1,
            "cb_ref": cb,
            "arrow_ref": arrow_btn,
        })

        self._rows.append(row)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

        return row_index

    def finalizeHierarchy(self):
        """
        Call after all addnode() to compute parent/child relationships.
        Nodes must be added in tree preorder (depth-first).
        """
        depth_stack: list[int] = []
        for i, nd in enumerate(self._node_data):
            d = nd["depth"]
            # POP STACK UNTIL WE FIND THE PARENT.
            while depth_stack and self._node_data[depth_stack[-1]]["depth"] >= d:
                depth_stack.pop()
            if depth_stack:
                parent_idx = depth_stack[-1]
                nd["parent_index"] = parent_idx
                self._node_data[parent_idx]["child_indices"].append(i)
                # HIDE IF PARENT IS COLLAPSED.
                if not self._node_data[parent_idx]["expanded"]:
                    self._rows[i].setVisible(False)
            depth_stack.append(i)

    def expandAll(self):
        """Expand all nodes."""
        for i, nd in enumerate(self._node_data):
            nd["expanded"] = True
            self._rows[i].setVisible(True)
            if nd["has_children"]:
                nd["arrow_ref"].setText("▼")

    def collapseAll(self):
        """Collapse all nodes (hide all non-root rows)."""
        for i, nd in enumerate(self._node_data):
            if nd["depth"] == 0:
                nd["expanded"] = True
                nd["arrow_ref"].setText("▼")
                self._rows[i].setVisible(True)
            else:
                nd["expanded"] = False
                nd["arrow_ref"].setText("▶")
                self._rows[i].setVisible(False)

    # EXPAND / COLLAPSE

    def _toggle_expand(self, row_index: int):
        """Toggle expand/collapse for a node."""
        nd = self._node_data[row_index]
        if not nd["has_children"]:
            return

        nd["expanded"] = not nd["expanded"]
        nd["arrow_ref"].setText("▼" if nd["expanded"] else "▶")

        # SHOW/HIDE ALL DESCENDANTS RECURSIVELY.
        self._set_descendants_visible(row_index, nd["expanded"])

    def _set_descendants_visible(self, row_index: int, visible: bool):
        """Recursively show/hide all descendants."""
        for child_idx in self._node_data[row_index]["child_indices"]:
            self._rows[child_idx].setVisible(visible)
            child_nd = self._node_data[child_idx]
            # IF COLLAPSING, ALSO MARK CHILD AS COLLAPSED.
            if not visible:
                child_nd["expanded"] = False
                child_nd["arrow_ref"].setText("▶")
            # RECURSE INTO GRANDCHILDREN (ONLY IF THEY WERE EXPANDED).
            if child_nd["has_children"]:
                self._set_descendants_visible(child_idx, visible and child_nd["expanded"])

    # CHECKBOX HANDLING

    def _on_checkbox_clicked(self, row_index: int, checked: bool):
        """Handle checkbox toggle with child/parent propagation."""
        nd = self._node_data[row_index]
        cb = nd["cb_ref"]

        # UPDATE CHECKBOX STYLE.
        cb.setStyleSheet(self._checkbox_qss(checked))

        # PROPAGATE TO CHILDREN.
        self._set_children_checked(row_index, checked)

        # PROPAGATE TO PARENT.
        self._update_parent_state(row_index)

        # EMIT SIGNAL.
        self.check_changed.emit(row_index, checked)

    def _set_children_checked(self, row_index: int, checked: bool):
        """Recursively set all children checkboxes."""
        for child_idx in self._node_data[row_index]["child_indices"]:
            child_nd = self._node_data[child_idx]
            child_cb = child_nd["cb_ref"]
            child_cb.setChecked(checked)
            child_cb.setStyleSheet(self._checkbox_qss(checked))
            self._set_children_checked(child_idx, checked)

    def _update_parent_state(self, row_index: int):
        """Recursively update parent tri-state based on children."""
        parent_idx = self._node_data[row_index]["parent_index"]
        if parent_idx < 0:
            return

        parent_nd = self._node_data[parent_idx]
        parent_cb = parent_nd["cb_ref"]

        # COUNT CHECKED / UNCHECKED CHILDREN.
        checked_count = 0
        total = len(parent_nd["child_indices"])
        for child_idx in parent_nd["child_indices"]:
            if self._node_data[child_idx]["cb_ref"].isChecked():
                checked_count += 1

        if checked_count == total:
            parent_cb.setChecked(True)
            parent_cb.setStyleSheet(self._checkbox_qss(True))
        elif checked_count == 0:
            parent_cb.setChecked(False)
            parent_cb.setStyleSheet(self._checkbox_qss(False))
        else:
            # PARTIAL: SHOW AS CHECKED BUT WITH DIFFERENT STYLE.
            parent_cb.setChecked(True)
            parent_cb.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self._COLORS['accent']};
                    border: 2px solid {self._COLORS['accent']};
                    border-radius: 4px;
                    color: {self._COLORS['bg']};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 0;
                }}
                QPushButton:hover {{
                    border-color: {self._COLORS['accent']};
                }}
            """)

        # RECURSE UP.
        self._update_parent_state(parent_idx)

    # ROW SELECTION

    def _on_row_clicked(self, index: int):
        """Handle row click for selection."""
        # ONLY VISIBLE ROWS CAN BE SELECTED.
        if not self._rows[index].isVisible():
            return
        if 0 <= self._selected_index < len(self._rows):
            self._rows[self._selected_index].set_selected(False)
        self._selected_index = index
        if 0 <= index < len(self._rows):
            self._rows[index].set_selected(True)
        self.row_clicked.emit(index)

    # PUBLIC ACCESSORS

    def getExcludedPaths(self) -> set[str]:
        """Return set of all excluded folder paths."""
        excluded = set()
        for nd in self._node_data:
            if not nd["cb_ref"].isChecked():
                excluded.add(nd["path"])
        return excluded

    def getNodePath(self, row: int) -> str:
        """Return the path for a given row."""
        if 0 <= row < len(self._node_data):
            return self._node_data[row]["path"]
        return ""

    def rowCount(self) -> int:
        """Return total number of nodes."""
        return len(self._rows)


def make_container(widget) -> QFrame:
    from PyQt6.QtWidgets import QFrame, QVBoxLayout
    from ..theme import COLORS
    frame = QFrame()
    frame.setStyleSheet(
        f"""
        QFrame {{
            background: {COLORS["surface"]};
            border-radius: 12px;
            border: none;
        }}
        """
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.addWidget(widget)
    return frame
