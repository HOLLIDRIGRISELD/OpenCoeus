"""Main window: navigation shell around the independent pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import (
    QCloseEvent,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.core.constants import APP_NAME
from app.services.context import AppContext
from app.ui.pages import (
    DashboardPage,
    FilesPage,
    HistoryPage,
    PlannerPage,
    RecommendationsPage,
    ScannerPage,
    SearchPage,
    SettingsPage,
)

NAVIGATION: tuple[tuple[str, str, str, str], ...] = (
    ("dashboard", "Overview", "Overview", "The state of your library at a glance."),
    ("scanner", "Scan & analyse", "Scan & analyse", "Discover files and run the local analysis pipeline."),
    ("files", "Library", "Library", "Browse and inspect every indexed file."),
    ("recommendations", "Review", "Review", "Approve, edit or reject proposed names and folders."),
    ("planner", "Planner", "Planner", "Preview and apply approved changes safely."),
    ("search", "Search", "Search", "Find documents by words or by meaning."),
    ("history", "History", "History", "Audit trail, undo, backups and maintenance."),
    ("settings", "Settings", "Settings", "Local models, thresholds and storage."),
)


class MainWindow(QMainWindow):
    """Sidebar navigation, a header and a stack of pages."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.ctx = context
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self._current_key = "dashboard"
        self._dirty_pages: set[str] = set()

        self.setWindowTitle(f"{APP_NAME} — local-first file intelligence")
        self._size_for_screen()
        self._build()
        self._connect()
        self.navigate("dashboard", force=True)

    def _size_for_screen(self) -> None:
        """Start at a sensible size for the actual display.

        The old fixed 1340×880 window with a 1080×720 minimum simply did not fit
        on 1366×768 laptops (or a 1024×600 remote desktop). We now use a capped
        fraction of the available screen and keep a minimum that still fits.
        """

        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is None:
            self.resize(1280, 800)
            return

        width = min(1600, max(760, round(available.width() * 0.82)))
        height = min(980, max(520, round(available.height() * 0.86)))
        width = min(width, available.width())
        height = min(height, available.height())
        self.resize(width, height)
        self.setMinimumSize(min(760, available.width()), min(520, available.height()))
        self.move(available.center() - self.rect().center())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt naming
        """Apply breakpoints once real geometry is known, before first paint."""

        super().showEvent(event)
        self._update_responsive_layout()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt naming
        """Reflow the shell whenever the window or the screen changes size."""

        super().resizeEvent(event)
        self._update_responsive_layout()

    def _update_responsive_layout(self) -> None:
        """Scale the sidebar and header and drop secondary details when cramped.

        All dimensions are derived from the current window size rather than fixed
        pixels, so the same layout works on a 1024×600 remote desktop, a 1366×768
        laptop and a 4K display (including fractional scaling).
        """

        width = self.width()
        height = self.height()

        sidebar_width = max(176, min(260, round(width * 0.18)))
        if self.sidebar.width() != sidebar_width:
            self.sidebar.setFixedWidth(sidebar_width)
        self.tagline_label.setVisible(sidebar_width >= 210)

        header_height = max(64, min(92, round(height * 0.09)))
        if self.header.minimumHeight() != header_height:
            self.header.setMinimumHeight(header_height)

    def _build(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        self.sidebar = self._build_sidebar()
        root.addWidget(self.sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.header = self._build_header()
        content_layout.addWidget(self.header)

        self.stack = QStackedWidget()
        self.pages = {
            "dashboard": DashboardPage(self.ctx),
            "scanner": ScannerPage(self.ctx),
            "files": FilesPage(self.ctx),
            "recommendations": RecommendationsPage(self.ctx),
            "planner": PlannerPage(self.ctx),
            "search": SearchPage(self.ctx),
            "history": HistoryPage(self.ctx),
            "settings": SettingsPage(self.ctx),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready. All processing stays on this machine.")

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(6)

        brand_row = QHBoxLayout()
        mark = QLabel("OC")
        mark.setProperty("role", "brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(38, 38)
        brand_row.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setProperty("role", "brand")
        self.tagline_label = QLabel("local-first intelligence")
        self.tagline_label.setProperty("role", "hint")
        brand_text.addWidget(name)
        brand_text.addWidget(self.tagline_label)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for index, (key, label, _title, _subtitle) in enumerate(NAVIGATION, start=1):
            button = QPushButton(label)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setToolTip(f"{label} (Ctrl+{index})")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, target=key: self.navigate(target))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        return sidebar

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setMinimumHeight(64)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel("")
        self.title_label.setProperty("role", "pageTitle")
        self.title_label.setWordWrap(True)
        self.subtitle_label = QLabel("")
        self.subtitle_label.setProperty("role", "pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        titles.addWidget(self.title_label)
        titles.addWidget(self.subtitle_label)
        layout.addLayout(titles, 1)
        return header

    def _connect(self) -> None:
        for page in self.pages.values():
            if hasattr(page, "message"):
                page.message.connect(self._show_message)
            if hasattr(page, "navigate"):
                page.navigate.connect(self.navigate)
            if hasattr(page, "library_changed"):
                page.library_changed.connect(self._library_changed)

        settings_page = self.pages["settings"]
        settings_page.settings_changed.connect(self._settings_changed)

        for index, (key, *_rest) in enumerate(NAVIGATION, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda target=key: self.navigate(target))

        refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        refresh.activated.connect(self._refresh_current)

        search = QShortcut(QKeySequence("Ctrl+F"), self)
        search.activated.connect(self._focus_search)

    def navigate(self, key: str, *, force: bool = False) -> None:
        if key not in self.pages:
            return
        same_page = key == self._current_key and key not in self._dirty_pages
        self._current_key = key
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        for entry_key, _label, title, subtitle in NAVIGATION:
            if entry_key == key:
                self.title_label.setText(title)
                self.subtitle_label.setText(subtitle)
                break
        if same_page and not force:
            return
        self._dirty_pages.discard(key)
        try:
            page.refresh()
        except Exception as exc:
            self._show_message(f"Could not refresh this page: {exc}")

    def _focus_search(self) -> None:
        self.navigate("search")
        self.pages["search"].focus_query()

    def _refresh_current(self) -> None:
        self._dirty_pages.discard(self._current_key)
        try:
            self.pages[self._current_key].refresh()
        except Exception as exc:
            self._show_message(f"Refresh failed: {exc}")

    def _mark_dirty(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            if key == self._current_key:
                self._refresh_current()
            else:
                self._dirty_pages.add(key)

    def _library_changed(self) -> None:
        self._mark_dirty(("dashboard", "files", "recommendations", "planner", "history"))

    def _settings_changed(self) -> None:
        self._mark_dirty(
            ("dashboard", "files", "recommendations", "planner", "history", "scanner")
        )

    def _show_message(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def cancel_tasks(self) -> None:
        for page in self.pages.values():
            cancel = getattr(page, "cancel_tasks", None)
            if callable(cancel):
                cancel()

    def stop_for_restore(self) -> None:
        """Freeze the app while the on-disk database is replaced."""

        self.cancel_tasks()
        QThreadPool.globalInstance().waitForDone()
        self.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.cancel_tasks()
        event.accept()


__all__ = ["MainWindow", "NAVIGATION"]
