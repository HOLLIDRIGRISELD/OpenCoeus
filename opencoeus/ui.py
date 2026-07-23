from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QSize, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QSpacerItem, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .config import ScanSettings
from .database import AuditStore
from .engine import ScanEngine, ScanResult, write_manifest
from .folder_tree import FolderNode, build_folder_tree, set_folder_exclusion
from .profiles import ProfileConfig, create_profile, list_profiles, load_profile_by_name
from .rules_engine import RulesEngine, RuleMatch


DEFAULT_RULES = [
    {"id": 1, "name": "Documents", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".pdf", ".docx", ".doc", ".xlsx", ".pptx", ".txt", ".rtf", ".odt"]}',
     "destination_template": "{folder}/Documents/{filename}", "action_type": "move"},
    {"id": 2, "name": "Images", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff"]}',
     "destination_template": "{folder}/Images/{filename}", "action_type": "move"},
    {"id": 3, "name": "Audio", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"]}',
     "destination_template": "{folder}/Audio/{filename}", "action_type": "move"},
    {"id": 4, "name": "Video", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"]}',
     "destination_template": "{folder}/Video/{filename}", "action_type": "move"},
    {"id": 5, "name": "Archives", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"]}',
     "destination_template": "{folder}/Archives/{filename}", "action_type": "move"},
    {"id": 6, "name": "Code", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".go", ".rs", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".toml"]}',
     "destination_template": "{folder}/Code/{filename}", "action_type": "move"},
    {"id": 7, "name": "Installers", "rule_type": "extension", "enabled": True, "priority": 10,
     "rule_config": '{"extensions": [".msi", ".exe", ".dmg", ".deb", ".rpm", ".apk"]}',
     "destination_template": "{folder}/Installers/{filename}", "action_type": "move"},
    {"id": 8, "name": "Old files archive", "rule_type": "date", "enabled": True, "priority": 50,
     "rule_config": '{"older_than_days": 365}',
     "destination_template": "{folder}/Archive/{date_year}/{filename}", "action_type": "move"},
]

COLORS = {
    "bg":          "#0d1117",
    "surface":     "#161b22",
    "surface2":    "#1c2333",
    "surface3":    "#21283b",
    "border":      "#30363d",
    "border_light":"#3d444d",
    "text":        "#e6edf3",
    "text2":       "#8b949e",
    "text3":       "#6e7681",
    "accent":      "#58a6ff",
    "accent2":     "#1f6feb",
    "green":       "#3fb950",
    "green_bg":    "#12261e",
    "red":         "#f85149",
    "red_bg":      "#2d1215",
    "yellow":      "#d29922",
    "yellow_bg":   "#2e2210",
    "orange":      "#db6d28",
    "purple":      "#bc8cff",
    "sidebar_bg":  "#0d1117",
}


def _icon_char(char: str) -> QPixmap:
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI", 16)
    p.setFont(font)
    p.setPen(QColor(COLORS["text"]))
    p.drawText(QRect(0, 0, 32, 32), Qt.AlignmentFlag.AlignCenter, char)
    p.end()
    return px


def _shadow(widget: QWidget, blur: int = 20, dy: int = 2, color: str = "#000000") -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(color))
    widget.setGraphicsEffect(effect)


class PhaseOneWorker(QThread):
    message = pyqtSignal(str)
    finished_tree = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path, custom_patterns: list[str] | None = None) -> None:
        super().__init__()
        self.selected_folder = selected_folder
        self.custom_patterns = custom_patterns

    def run(self) -> None:
        try:
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            result = engine.run_phase_one(lambda msg: self.message.emit(str(msg)), self.custom_patterns)
            tree_root = build_folder_tree(self.selected_folder, settings.protected_patterns, max_depth=5)
            self.finished_tree.emit(result, tree_root)
        except Exception as exc:
            self.failed.emit(str(exc))


class PhaseTwoWorker(QThread):
    message = pyqtSignal(str)
    finished_scan = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, selected_folder: Path, excluded_folders: set[str],
                 rules: list[dict], profile: ProfileConfig) -> None:
        super().__init__()
        self.selected_folder = selected_folder
        self.excluded_folders = excluded_folders
        self.rules = rules
        self.profile = profile

    def run(self) -> None:
        try:
            settings = ScanSettings(self.selected_folder)
            engine = ScanEngine(settings)
            scan_result = engine.run_phase_two(self.excluded_folders, lambda msg: self.message.emit(str(msg)))
            rules_engine = RulesEngine(self.profile)
            matches = rules_engine.evaluate(scan_result.rows, self.rules)
            self.finished_scan.emit(scan_result, matches)
        except Exception as exc:
            self.failed.emit(str(exc))


class SidebarButton(QToolButton):
    def __init__(self, icon_char: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(48, 48)
        self.setToolTip(tooltip)
        self.setIcon(QIcon(_icon_char(icon_char)))
        self.setIconSize(QSize(22, 22))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setAutoRaise(True)
        self.setStyleSheet(f"""
            QToolButton {{
                border: none;
                border-radius: 10px;
                background: transparent;
                padding: 0;
            }}
            QToolButton:hover {{
                background: {COLORS["surface3"]};
            }}
            QToolButton:checked {{
                background: {COLORS["accent2"]};
            }}
        """)


class StatCard(QWidget):
    def __init__(self, title: str, value: str, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = accent
        self._title_label = title
        self._value_label = value
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {COLORS['text2']}; font-size: 12px; border: none;")
        self._val = QLabel(value)
        self._val.setStyleSheet(f"color: {accent}; font-size: 28px; font-weight: bold; border: none;")
        layout.addWidget(title_lbl)
        layout.addWidget(self._val)

        self.setFixedHeight(90)
        self.setStyleSheet(f"""
            StatCard {{
                background: {COLORS["surface"]};
                border: 1px solid {COLORS["border"]};
                border-left: 3px solid {accent};
                border-radius: 10px;
            }}
        """)

    def set_value(self, value: str) -> None:
        self._val.setText(value)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OpenCoeus")
        self.setMinimumSize(900, 550)
        self.resize(1200, 750)

        self.scan_result: ScanResult | None = None
        self.folder_tree_root: FolderNode | None = None
        self.excluded_folders: set[str] = set()
        self.current_profile: ProfileConfig | None = None
        self.active_rules: list[dict] = list(DEFAULT_RULES)
        self.proposed_matches: list[RuleMatch] = []
        self.store = AuditStore()
        self.phase_one_worker: PhaseOneWorker | None = None
        self.phase_two_worker: PhaseTwoWorker | None = None
        self._nav_buttons: list[SidebarButton] = []
        self._pages: list[QWidget] = []

        self._build_ui()
        self._apply_global_style()
        self._load_profiles()
        self._switch_page(0)

    # ------------------------------------------------------------------ #
    #  GLOBAL STYLES                                                       #
    # ------------------------------------------------------------------ #
    def _apply_global_style(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow, QWidget#central {{
                background: {COLORS["bg"]};
            }}
            QStatusBar {{
                background: {COLORS["surface"]};
                color: {COLORS["text2"]};
                border-top: 1px solid {COLORS["border"]};
                font-size: 11px;
                padding: 0 10px;
            }}
            QLabel {{
                color: {COLORS["text"]};
            }}
            QLineEdit {{
                background: {COLORS["surface2"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
                selection-background-color: {COLORS["accent2"]};
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS["accent"]};
            }}
            QPushButton {{
                background: {COLORS["surface3"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: {COLORS["border"]};
                border-color: {COLORS["border_light"]};
            }}
            QPushButton:pressed {{
                background: {COLORS["accent2"]};
                border-color: {COLORS["accent"]};
            }}
            QPushButton:disabled {{
                color: {COLORS["text3"]};
                background: {COLORS["surface2"]};
                border-color: {COLORS["surface3"]};
            }}
            QTreeWidget {{
                background: {COLORS["surface"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
                padding: 4px;
                font-size: 12px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 6px;
                border: none;
                border-radius: 4px;
            }}
            QTreeWidget::item:selected {{
                background: {COLORS["accent2"]};
            }}
            QTreeWidget::item:hover {{
                background: {COLORS["surface3"]};
            }}
            QTreeWidget::branch {{
                background: {COLORS["surface"]};
            }}
            QHeaderView::section {{
                background: {COLORS["surface2"]};
                color: {COLORS["text2"]};
                border: none;
                border-bottom: 1px solid {COLORS["border"]};
                padding: 6px 10px;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
            }}
            QTableWidget {{
                background: {COLORS["surface"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
                gridline-color: {COLORS["border"]};
                font-size: 12px;
                selection-background-color: {COLORS["accent2"]};
                outline: none;
            }}
            QTableWidget::item {{
                padding: 6px 10px;
            }}
            QListWidget {{
                background: {COLORS["surface"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
                padding: 4px;
                font-size: 12px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background: {COLORS["accent2"]};
            }}
            QListWidget::item:hover {{
                background: {COLORS["surface3"]};
            }}
            QTextEdit {{
                background: {COLORS["surface"]};
                color: {COLORS["text"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 8px;
                padding: 8px;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 11px;
                selection-background-color: {COLORS["accent2"]};
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: {COLORS["surface"]};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS["border"]};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {COLORS["text3"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar:horizontal {{
                height: 8px;
            }}
            QScrollBar::handle:horizontal {{
                background: {COLORS["border"]};
                border-radius: 4px;
                min-width: 30px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0;
            }}
            QProgressBar {{
                background: {COLORS["surface2"]};
                border: none;
                border-radius: 2px;
                max-height: 3px;
                min-height: 3px;
            }}
            QProgressBar::chunk {{
                background: {COLORS["accent"]};
                border-radius: 2px;
            }}
        """)

    # ------------------------------------------------------------------ #
    #  UI BUILD                                                            #
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- SIDEBAR (icon rail) ----
        sidebar = QWidget()
        sidebar.setFixedWidth(60)
        sidebar.setStyleSheet(f"""
            QWidget {{
                background: {COLORS["sidebar_bg"]};
                border-right: 1px solid {COLORS["border"]};
            }}
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 12, 0, 12)
        sb_layout.setSpacing(4)

        app_icon = QLabel("O")
        app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_icon.setFixedHeight(40)
        app_icon.setStyleSheet(f"color: {COLORS['accent']}; font-size: 22px; font-weight: bold; border: none;")
        sb_layout.addWidget(app_icon)

        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        nav_icons = ["H", "T", "R", "A", "L"]
        nav_tips  = ["Home", "Folders", "Results", "Actions", "Log"]

        for i, (ic, tip) in enumerate(zip(nav_icons, nav_tips)):
            btn = SidebarButton(ic, tip)
            nav_group.addButton(btn, i)
            self._nav_buttons.append(btn)
            sb_layout.addWidget(btn)

        sb_layout.addStretch()
        root.addWidget(sidebar)

        # ---- MAIN CONTENT ----
        content = QWidget()
        content.setStyleSheet(f"background: {COLORS['bg']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Top header bar (stays across all pages).
        self._build_header(content_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.hide()
        content_layout.addWidget(self.progress_bar)

        # Page stack.
        self._page_container = QWidget()
        self._page_stack = QVBoxLayout(self._page_container)
        self._page_stack.setContentsMargins(0, 0, 0, 0)
        self._page_stack.setSpacing(0)

        self._pages = [
            self._build_home_page(),
            self._build_folders_page(),
            self._build_results_page(),
            self._build_actions_page(),
            self._build_log_page(),
        ]
        for page in self._pages:
            self._page_stack.addWidget(page)

        content_layout.addWidget(self._page_container, 1)
        root.addWidget(content, 1)

        # Wire nav buttons.
        nav_group.idClicked.connect(self._switch_page)

        # Status bar.
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready")

    def _build_header(self, parent_layout: QVBoxLayout) -> None:
        header = QWidget()
        header.setFixedHeight(64)
        header.setStyleSheet(f"""
            QWidget {{
                background: {COLORS["surface"]};
                border-bottom: 1px solid {COLORS["border"]};
            }}
        """)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(20, 0, 20, 0)
        hlay.setSpacing(12)

        self.folder_path_input = QLineEdit()
        self.folder_path_input.setPlaceholderText("Select a folder to scan...")
        self.folder_path_input.setMinimumWidth(280)
        hlay.addWidget(self.folder_path_input, 1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._choose_folder)
        hlay.addWidget(browse_btn)

        self.phase_one_button = QPushButton("Discover")
        self.phase_one_button.setFixedWidth(100)
        self.phase_one_button.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS["accent2"]};
                color: #ffffff;
                border: 1px solid {COLORS["accent"]};
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {COLORS["accent"]}; }}
            QPushButton:disabled {{ background: {COLORS["surface3"]}; color: {COLORS["text3"]}; border-color: {COLORS["surface3"]}; }}
        """)
        self.phase_one_button.clicked.connect(self._start_phase_one)
        hlay.addWidget(self.phase_one_button)

        self.phase_two_button = QPushButton("Scan & Organize")
        self.phase_two_button.setFixedWidth(130)
        self.phase_two_button.setEnabled(False)
        self.phase_two_button.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS["green"]};
                color: #000000;
                border: 1px solid {COLORS["green"]};
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #47cc5a; }}
            QPushButton:disabled {{ background: {COLORS["surface3"]}; color: {COLORS["text3"]}; border-color: {COLORS["surface3"]}; }}
        """)
        self.phase_two_button.clicked.connect(self._start_phase_two)
        hlay.addWidget(self.phase_two_button)

        self.export_button = QPushButton("Export")
        self.export_button.setFixedWidth(80)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_manifest)
        hlay.addWidget(self.export_button)

        parent_layout.addWidget(header)

    # ------------------------------------------------------------------ #
    #  PAGE BUILDERS                                                       #
    # ------------------------------------------------------------------ #
    def _make_page_wrapper(self, inner: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return scroll

    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text']}; font-size: 18px; font-weight: bold; padding: 0;")
        return lbl

    def _section_sub(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text2']}; font-size: 12px; padding: 0;")
        lbl.setWordWrap(True)
        return lbl

    # -- HOME PAGE -------------------------------------------------------- #
    def _build_home_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(20)

        title = QLabel("OpenCoeus")
        title.setStyleSheet(f"color: {COLORS['text']}; font-size: 32px; font-weight: bold; border: none;")
        lay.addWidget(title)

        subtitle = self._section_sub("Data Lifecycle Management — scan, classify, and organize your files.")
        lay.addWidget(subtitle)

        # Stats cards.
        self.stat_cards = QGridLayout()
        self.stat_cards.setSpacing(12)
        self.card_folders = StatCard("Folders", "—", COLORS["accent"])
        self.card_files = StatCard("Files", "—", COLORS["green"])
        self.card_duplicates = StatCard("Duplicates", "—", COLORS["yellow"])
        self.card_actions = StatCard("Actions", "—", COLORS["purple"])
        self.stat_cards.addWidget(self.card_folders, 0, 0)
        self.stat_cards.addWidget(self.card_files, 0, 1)
        self.stat_cards.addWidget(self.card_duplicates, 0, 2)
        self.stat_cards.addWidget(self.card_actions, 0, 3)
        lay.addLayout(self.stat_cards)

        # Profiles section.
        profile_header = QHBoxLayout()
        profile_header.setSpacing(8)
        profile_header.addWidget(self._section_title("Profiles"))
        add_profile_btn = QPushButton("+ New")
        add_profile_btn.setFixedWidth(70)
        add_profile_btn.clicked.connect(self._create_new_profile)
        profile_header.addWidget(add_profile_btn)
        profile_header.addStretch()
        lay.addLayout(profile_header)

        self.profile_list = QListWidget()
        self.profile_list.setMaximumHeight(120)
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        lay.addWidget(self.profile_list)

        lay.addStretch()
        return page

    # -- FOLDERS PAGE ----------------------------------------------------- #
    def _build_folders_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        lay.addWidget(self._section_title("Folder Tree"))
        lay.addWidget(self._section_sub("Uncheck folders to exclude them from scanning."))

        self.folder_tree = QTreeWidget()
        self.folder_tree.setHeaderLabels(["Folder", "Files", "Size", "Type"])
        self.folder_tree.setColumnCount(4)
        self.folder_tree.setAlternatingRowColors(False)
        self.folder_tree.itemChanged.connect(self._on_folder_toggled)
        lay.addWidget(self.folder_tree, 1)

        return page

    # -- RESULTS PAGE ----------------------------------------------------- #
    def _build_results_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        lay.addWidget(self._section_title("Scan Results"))
        lay.addWidget(self._section_sub("Files discovered during the scan phase."))

        self.results_table = self._make_table(
            ["Path", "Size", "Status", "Duplicate of", "Title", "Ext", "Folder"],
            stretch_column=0,
        )
        lay.addWidget(self.results_table, 1)

        return page

    # -- ACTIONS PAGE ----------------------------------------------------- #
    def _build_actions_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(self._section_title("Proposed Actions"))
        header.addStretch()

        self.actions_count_label = QLabel("No actions")
        self.actions_count_label.setStyleSheet(f"color: {COLORS['text2']}; font-size: 12px;")
        header.addWidget(self.actions_count_label)
        lay.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        approve_btn = QPushButton("Approve selected")
        approve_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS["green_bg"]}; color: {COLORS["green"]}; border: 1px solid {COLORS["green"]}; }}
            QPushButton:hover {{ background: {COLORS["green"]}; color: #000; }}
        """)
        approve_btn.clicked.connect(self._approve_selected)
        toolbar.addWidget(approve_btn)

        approve_all_btn = QPushButton("Approve all")
        approve_all_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS["green_bg"]}; color: {COLORS["green"]}; border: 1px solid {COLORS["green"]}; }}
            QPushButton:hover {{ background: {COLORS["green"]}; color: #000; }}
        """)
        approve_all_btn.clicked.connect(self._approve_all)
        toolbar.addWidget(approve_all_btn)

        reject_btn = QPushButton("Remove")
        reject_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLORS["red_bg"]}; color: {COLORS["red"]}; border: 1px solid {COLORS["red"]}; }}
            QPushButton:hover {{ background: {COLORS["red"]}; color: #fff; }}
        """)
        reject_btn.clicked.connect(self._reject_selected)
        toolbar.addWidget(reject_btn)

        toolbar.addStretch()
        lay.addLayout(toolbar)

        self.actions_table = self._make_table(
            ["Status", "Original Path", "Proposed Path", "Action", "Reason"],
            stretch_column=1,
            select_mode=QTableWidget.SelectionMode.ExtendedSelection,
        )
        lay.addWidget(self.actions_table, 1)

        return page

    # -- LOG PAGE --------------------------------------------------------- #
    def _build_log_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(12)

        lay.addWidget(self._section_title("Activity Log"))
        lay.addWidget(self._section_sub("Real-time log of scan operations."))

        self.audit_log = QTextEdit()
        self.audit_log.setReadOnly(True)
        lay.addWidget(self.audit_log, 1)

        return page

    # ------------------------------------------------------------------ #
    #  TABLE HELPER                                                        #
    # ------------------------------------------------------------------ #
    def _make_table(
        self,
        headers: list[str],
        stretch_column: int = 0,
        select_mode: QTableWidget.SelectionMode = QTableWidget.SelectionMode.SingleSelection,
    ) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(select_mode)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSortingEnabled(False)
        return table

    # ------------------------------------------------------------------ #
    #  PAGE NAVIGATION                                                     #
    # ------------------------------------------------------------------ #
    def _switch_page(self, index: int) -> None:
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        if index < len(self._nav_buttons):
            self._nav_buttons[index].setChecked(True)

    # ------------------------------------------------------------------ #
    #  FOLDER CHOOSER                                                      #
    # ------------------------------------------------------------------ #
    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            self.folder_path_input.setText(folder)

    # ------------------------------------------------------------------ #
    #  PHASE ONE                                                           #
    # ------------------------------------------------------------------ #
    def _start_phase_one(self) -> None:
        folder = Path(self.folder_path_input.text())
        if not folder.is_dir():
            QMessageBox.warning(self, "OpenCoeus", "Select a readable folder first.")
            return
        self.audit_log.clear()
        self.results_table.setRowCount(0)
        self.actions_table.setRowCount(0)
        self.proposed_matches.clear()
        self.excluded_folders.clear()
        self.phase_one_button.setEnabled(False)
        self.phase_two_button.setEnabled(False)
        self.progress_bar.show()
        self._status.showMessage("Discovering folders...")
        self.phase_one_worker = PhaseOneWorker(folder)
        self.phase_one_worker.message.connect(self._on_log_message)
        self.phase_one_worker.finished_tree.connect(self._phase_one_done)
        self.phase_one_worker.failed.connect(self._scan_failed)
        self.phase_one_worker.start()

    def _phase_one_done(self, scan_result: ScanResult, tree_root: FolderNode) -> None:
        self.scan_result = scan_result
        self.folder_tree_root = tree_root
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self._fill_folder_tree(tree_root)
        n = len(scan_result.classifications)
        ex = len(self.excluded_folders)
        self._status.showMessage(f"Phase 1 complete — {n} folders classified, {ex} excluded")
        self._on_log_message(f"<b>Phase 1:</b> {n} folders classified, {ex} excluded automatically.")
        self.card_folders.set_value(str(n))
        self._switch_page(1)

    def _on_log_message(self, msg: str) -> None:
        self.audit_log.append(msg)

    # ------------------------------------------------------------------ #
    #  PHASE TWO                                                           #
    # ------------------------------------------------------------------ #
    def _start_phase_two(self) -> None:
        folder = Path(self.folder_path_input.text())
        if not folder.is_dir():
            return
        self.phase_two_button.setEnabled(False)
        self.phase_one_button.setEnabled(False)
        self.progress_bar.show()
        self._status.showMessage("Scanning files and applying rules...")
        profile = self.current_profile or ProfileConfig()
        self.phase_two_worker = PhaseTwoWorker(folder, self.excluded_folders, self.active_rules, profile)
        self.phase_two_worker.message.connect(self._on_log_message)
        self.phase_two_worker.finished_scan.connect(self._phase_two_done)
        self.phase_two_worker.failed.connect(self._scan_failed)
        self.phase_two_worker.start()

    def _phase_two_done(self, scan_result: ScanResult, matches: list[RuleMatch]) -> None:
        self.scan_result = scan_result
        self.proposed_matches = matches
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self._fill_results_table(scan_result)
        self._fill_actions_table(matches)
        self._switch_page(2)

        dup = scan_result.duplicate_count
        self.card_files.set_value(str(len(scan_result.rows)))
        self.card_duplicates.set_value(str(dup))
        self.card_actions.set_value(str(len(matches)))
        self._status.showMessage(
            f"Phase 2 complete — {len(scan_result.rows)} files, {dup} duplicates, {len(matches)} actions"
        )
        self._on_log_message(
            f"<b>Phase 2:</b> {len(scan_result.rows)} files, {dup} duplicates, {len(matches)} actions proposed."
        )

    def _scan_failed(self, msg: str) -> None:
        self.progress_bar.hide()
        self.phase_one_button.setEnabled(True)
        self.phase_two_button.setEnabled(True)
        self._status.showMessage("Scan failed")
        QMessageBox.critical(self, "Scan failed", msg)

    def _export_manifest(self) -> None:
        if not self.scan_result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save manifest", "opencoeus-manifest.csv", "CSV files (*.csv)")
        if path:
            write_manifest(self.scan_result, Path(path))
            self._on_log_message(f"Manifest saved: {path}")

    # ------------------------------------------------------------------ #
    #  ACTIONS TABLE CONTROLS                                              #
    # ------------------------------------------------------------------ #
    def _approve_selected(self) -> None:
        rows = {idx.row() for idx in self.actions_table.selectedIndexes()}
        for r in rows:
            item = self.actions_table.item(r, 0)
            if item and item.text() != "APPROVED":
                item.setText("APPROVED")
                item.setForeground(QColor(COLORS["green"]))
        self._refresh_actions_count()

    def _approve_all(self) -> None:
        for r in range(self.actions_table.rowCount()):
            item = self.actions_table.item(r, 0)
            if item:
                item.setText("APPROVED")
                item.setForeground(QColor(COLORS["green"]))
        self._refresh_actions_count()

    def _reject_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.actions_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.actions_table.removeRow(r)
            if r < len(self.proposed_matches):
                self.proposed_matches.pop(r)
        self._refresh_actions_count()

    def _refresh_actions_count(self) -> None:
        approved = sum(
            1 for r in range(self.actions_table.rowCount())
            if self.actions_table.item(r, 0) and self.actions_table.item(r, 0).text() == "APPROVED"
        )
        total = self.actions_table.rowCount()
        self.actions_count_label.setText(f"{approved} / {total} approved")

    # ------------------------------------------------------------------ #
    #  PROFILES                                                            #
    # ------------------------------------------------------------------ #
    def _load_profiles(self) -> None:
        self.profile_list.clear()
        for p in list_profiles(self.store):
            self.profile_list.addItem(p.name)

    def _on_profile_selected(self, current, _prev) -> None:
        self.current_profile = load_profile_by_name(self.store, current.text()) if current else None

    def _create_new_profile(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if ok and name.strip():
            create_profile(self.store, name.strip())
            self._load_profiles()

    # ------------------------------------------------------------------ #
    #  FOLDER TREE                                                         #
    # ------------------------------------------------------------------ #
    def _fill_folder_tree(self, root: FolderNode) -> None:
        self.folder_tree.clear()
        self.folder_tree.blockSignals(True)
        root_item = QTreeWidgetItem(self.folder_tree, [
            root.name, str(root.file_count), self._fmt(root.total_size), "",
        ])
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setCheckState(0, Qt.CheckState.Checked)
        root_item.setData(0, Qt.ItemDataRole.UserRole, root.path.as_posix())
        self._add_tree_children(root, root_item)
        self.folder_tree.expandToDepth(1)
        self.folder_tree.blockSignals(False)

    def _add_tree_children(self, node: FolderNode, parent: QTreeWidgetItem) -> None:
        for child in node.children:
            item = QTreeWidgetItem(parent, [
                child.name, str(child.file_count), self._fmt(child.total_size),
                child.classification or "",
            ])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(0, Qt.ItemDataRole.UserRole, child.path.as_posix())
            if child.recommended_action == "exclude":
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setForeground(3, QColor(COLORS["red"]))
                self.excluded_folders.add(child.path.as_posix())
            else:
                item.setCheckState(0, Qt.CheckState.Checked)
                if child.classification in {"source_code", "unknown"}:
                    item.setForeground(3, QColor(COLORS["yellow"]))
            self._add_tree_children(child, item)

    def _on_folder_toggled(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0 or self.folder_tree_root is None:
            return
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if path_str is None:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        self.folder_tree.blockSignals(True)
        if checked:
            self.excluded_folders.discard(path_str)
            set_folder_exclusion(self.folder_tree_root, Path(path_str), excluded=False)
        else:
            self.excluded_folders.add(path_str)
            set_folder_exclusion(self.folder_tree_root, Path(path_str), excluded=True)
        self.folder_tree.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  POPULATE TABLES                                                     #
    # ------------------------------------------------------------------ #
    def _fill_results_table(self, result: ScanResult) -> None:
        t = self.results_table
        t.setRowCount(len(result.rows))
        for i, r in enumerate(result.rows):
            t.setItem(i, 0, QTableWidgetItem(r.path))
            t.setItem(i, 1, QTableWidgetItem(self._fmt(r.size)))
            status = QTableWidgetItem(r.status.upper())
            color_map = {
                "duplicate": COLORS["red"],
                "protected": COLORS["yellow"],
                "unique": COLORS["green"],
            }
            if r.status in color_map:
                status.setForeground(QColor(color_map[r.status]))
            t.setItem(i, 2, status)
            t.setItem(i, 3, QTableWidgetItem(r.duplicate_of))
            t.setItem(i, 4, QTableWidgetItem(r.suggested_title))
            t.setItem(i, 5, QTableWidgetItem(r.extension))
            t.setItem(i, 6, QTableWidgetItem(r.folder_path))

    def _fill_actions_table(self, matches: list[RuleMatch]) -> None:
        t = self.actions_table
        t.setRowCount(len(matches))
        for i, m in enumerate(matches):
            status = QTableWidgetItem("PENDING")
            status.setForeground(QColor(COLORS["text3"]))
            t.setItem(i, 0, status)
            t.setItem(i, 1, QTableWidgetItem(m.original_path))
            t.setItem(i, 2, QTableWidgetItem(m.proposed_path))
            t.setItem(i, 3, QTableWidgetItem(m.action_type.upper()))
            t.setItem(i, 4, QTableWidgetItem(m.reason))
        self._refresh_actions_count()

    @staticmethod
    def _fmt(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1048576:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1048576:.1f} MB"


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface2"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    app.setPalette(palette)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
