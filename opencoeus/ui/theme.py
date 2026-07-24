"""
Theme module for the OpenCoeus UI.
Provides color constants, button QSS generators, and global/dialog stylesheets.
"""

# ==============================================================================
# COLOR CONSTANTS
# ==============================================================================

COLORS = {
    "bg":          "#14151e",
    "surface":     "#1a1b2e",
    "surface2":    "#1f2038",
    "surface3":    "#252642",
    "border":      "#2e3048",
    "border_light":"#3a3c58",
    "text":        "#e2e8f0",
    "text2":       "#94a3b8",
    "text3":       "#64748b",
    "accent":      "#38bdf8",
    "accent2":     "#0284c7",
    "green":       "#4ade80",
    "green_bg":    "#14302a",
    "red":         "#f87171",
    "red_bg":      "#3b1518",
    "yellow":      "#facc15",
    "yellow_bg":   "#332e0e",
    "orange":      "#fb923c",
    "purple":      "#a78bfa",
    "sidebar_bg":  "#111219",
}


# ==============================================================================
# BUTTON QSS GENERATORS
# ==============================================================================

def accent_button_qss() -> str:
    """Return QSS for sky blue accent buttons (Discover, Save)."""
    return f"""
        QPushButton {{
            background-color: {COLORS['accent']};
            color: {COLORS['bg']};
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-weight: bold;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: #5ccdf8;
        }}
        QPushButton:disabled {{
            background-color: {COLORS['surface3']};
            color: {COLORS['text3']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['accent2']};
        }}
    """


def success_button_qss() -> str:
    """Return QSS for green success buttons (Scan & Organize, Approve, Execute)."""
    return f"""
        QPushButton {{
            background-color: {COLORS['green']};
            color: {COLORS['bg']};
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-weight: bold;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: #6ef89a;
        }}
        QPushButton:disabled {{
            background-color: {COLORS['surface3']};
            color: {COLORS['text3']};
        }}
        QPushButton:pressed {{
            background-color: #22c55e;
        }}
    """


def danger_button_qss() -> str:
    """Return QSS for red danger buttons (Delete, Remove)."""
    return f"""
        QPushButton {{
            background-color: {COLORS['red']};
            color: {COLORS['bg']};
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-weight: bold;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: #fca5a5;
        }}
        QPushButton:disabled {{
            background-color: {COLORS['surface3']};
            color: {COLORS['text3']};
        }}
        QPushButton:pressed {{
            background-color: #dc2626;
        }}
    """


def warning_button_qss() -> str:
    """Return QSS for yellow warning buttons (Undo)."""
    return f"""
        QPushButton {{
            background-color: {COLORS['yellow']};
            color: {COLORS['bg']};
            border: none;
            border-radius: 6px;
            padding: 6px 16px;
            font-weight: bold;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: #fde047;
        }}
        QPushButton:disabled {{
            background-color: {COLORS['surface3']};
            color: {COLORS['text3']};
        }}
        QPushButton:pressed {{
            background-color: #eab308;
        }}
    """


def text_button_qss() -> str:
    """Return QSS for default text buttons (Cancel, Edit, etc.)."""
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {COLORS['text2']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 16px;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background-color: {COLORS['surface3']};
            color: {COLORS['text']};
        }}
        QPushButton:disabled {{
            color: {COLORS['text3']};
            border-color: {COLORS['surface3']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['surface2']};
        }}
    """


# ==============================================================================
# GLOBAL STYLESHEET
# ==============================================================================

def global_stylesheet() -> str:
    """Return the complete QSS stylesheet for the main application window."""
    return f"""
        /* ---- MAIN WINDOW ---- */
        QMainWindow {{
            background-color: {COLORS['bg']};
        }}
        QWidget#central {{
            background-color: {COLORS['bg']};
        }}

        /* ---- STATUS BAR ---- */
        QStatusBar {{
            background-color: {COLORS['surface']};
            color: {COLORS['text2']};
            border-top: 1px solid {COLORS['border']};
            font-size: 11px;
        }}

        /* ---- LABELS ---- */
        QLabel {{
            color: {COLORS['text']};
            background: transparent;
        }}

        /* ---- LINE EDITS ---- */
        QLineEdit {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
            selection-background-color: {COLORS['accent']};
            selection-color: {COLORS['bg']};
        }}
        QLineEdit:focus {{
            border-color: {COLORS['accent']};
        }}

        /* ---- PUSH BUTTONS ---- */
        QPushButton {{
            background-color: {COLORS['surface2']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 16px;
            font-size: 12px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {COLORS['surface3']};
            border-color: {COLORS['border_light']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['border']};
        }}
        QPushButton:disabled {{
            background-color: {COLORS['surface']};
            color: {COLORS['text3']};
            border-color: {COLORS['surface3']};
        }}

        /* ---- TREE WIDGET ---- */
        QTreeWidget {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            outline: none;
            font-size: 12px;
        }}
        QTreeWidget::item {{
            padding: 4px 8px;
            border: none;
        }}
        QTreeWidget::item:selected {{
            background-color: {COLORS['surface3']};
            color: {COLORS['accent']};
        }}
        QTreeWidget::item:hover {{
            background-color: {COLORS['surface2']};
        }}
        QTreeWidget::branch {{
            background: transparent;
        }}

        /* ---- HEADER VIEWS ---- */
        QHeaderView {{
            background-color: {COLORS['surface']};
            border: none;
        }}
        QHeaderView::section {{
            background-color: {COLORS['surface2']};
            color: {COLORS['text2']};
            border: none;
            border-bottom: 1px solid {COLORS['border']};
            border-right: 1px solid {COLORS['border']};
            padding: 6px 10px;
            font-size: 11px;
            font-weight: bold;
        }}

        /* ---- TABLE WIDGET ---- */
        QTableWidget {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            gridline-color: {COLORS['border']};
            outline: none;
            font-size: 12px;
        }}
        QTableWidget::item {{
            padding: 4px 8px;
        }}
        QTableWidget::item:selected {{
            background-color: {COLORS['surface3']};
            color: {COLORS['accent']};
        }}
        QTableWidget::item:hover {{
            background-color: {COLORS['surface2']};
        }}

        /* ---- LIST WIDGET ---- */
        QListWidget {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            outline: none;
            font-size: 12px;
        }}
        QListWidget::item {{
            padding: 4px 8px;
        }}
        QListWidget::item:selected {{
            background-color: {COLORS['surface3']};
            color: {COLORS['accent']};
        }}
        QListWidget::item:hover {{
            background-color: {COLORS['surface2']};
        }}

        /* ---- TEXT EDIT ---- */
        QTextEdit {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
            selection-background-color: {COLORS['accent']};
            selection-color: {COLORS['bg']};
        }}

        /* ---- SCROLL AREA ---- */
        QScrollArea {{
            background: transparent;
            border: none;
        }}

        /* ---- SCROLL BARS ---- */
        QScrollBar:vertical {{
            background: {COLORS['surface']};
            width: 10px;
            margin: 0;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background: {COLORS['surface3']};
            min-height: 30px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {COLORS['border_light']};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: none;
        }}

        QScrollBar:horizontal {{
            background: {COLORS['surface']};
            height: 10px;
            margin: 0;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background: {COLORS['surface3']};
            min-width: 30px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {COLORS['border_light']};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0px;
        }}
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {{
            background: none;
        }}

        /* ---- PROGRESS BAR ---- */
        QProgressBar {{
            background-color: {COLORS['surface']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            text-align: center;
            color: {COLORS['text2']};
            font-size: 11px;
            height: 12px;
        }}
        QProgressBar::chunk {{
            background-color: {COLORS['accent']};
            border-radius: 5px;
        }}
    """


# ==============================================================================
# DIALOG STYLESHEET
# ==============================================================================

def dialog_stylesheet() -> str:
    """Return the QSS stylesheet for modal dialogs (ProfileEditDialog, etc.)."""
    return f"""
        /* ---- DIALOG ---- */
        QDialog {{
            background-color: {COLORS['bg']};
        }}

        /* ---- DIALOG LABELS ---- */
        QLabel {{
            color: {COLORS['text']};
            background: transparent;
        }}

        /* ---- DIALOG LINE EDITS ---- */
        QLineEdit {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
            selection-background-color: {COLORS['accent']};
            selection-color: {COLORS['bg']};
        }}
        QLineEdit:focus {{
            border-color: {COLORS['accent']};
        }}

        /* ---- DIALOG TEXT EDITS ---- */
        QTextEdit {{
            background-color: {COLORS['surface']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
            selection-background-color: {COLORS['accent']};
            selection-color: {COLORS['bg']};
        }}

        /* ---- DIALOG CHECK BOXES ---- */
        QCheckBox {{
            color: {COLORS['text']};
            background: transparent;
            spacing: 6px;
            font-size: 12px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 3px;
            border: 1px solid {COLORS['border']};
            background-color: {COLORS['surface']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {COLORS['accent']};
            border-color: {COLORS['accent']};
        }}
        QCheckBox::indicator:hover {{
            border-color: {COLORS['accent']};
        }}

        /* ---- DIALOG PUSH BUTTONS ---- */
        QPushButton {{
            background-color: {COLORS['surface2']};
            color: {COLORS['text']};
            border: 1px solid {COLORS['border']};
            border-radius: 6px;
            padding: 6px 16px;
            font-size: 12px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {COLORS['surface3']};
            border-color: {COLORS['border_light']};
        }}
        QPushButton:pressed {{
            background-color: {COLORS['border']};
        }}
        QPushButton:disabled {{
            background-color: {COLORS['surface']};
            color: {COLORS['text3']};
            border-color: {COLORS['surface3']};
        }}
    """
