"""Desktop entry point.

Launch with ``python main.py`` or the installed ``opencoeus-gui`` command.
The application creates its SQLite database on first use and never requires a
network connection.
"""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.constants import APP_NAME, APP_VERSION
from app.core.exceptions import OpenCoeusError
from app.intelligence.runtime import LocalRuntime
from app.services.context import AppContext
from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET


def run(argv: list[str] | None = None) -> int:
    """Start the Qt application and return its exit code."""

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    try:
        context = AppContext.create(purge=False)
    except OpenCoeusError as exc:
        QMessageBox.critical(None, f"{APP_NAME} could not start", exc.user_message)
        return 1
    except Exception as exc:
        QMessageBox.critical(None, f"{APP_NAME} could not start", str(exc))
        return 1

    window = MainWindow(context)
    window.show()
    runtime: LocalRuntime | None = None
    runtime_thread: threading.Thread | None = None
    if context.settings.enable_llm:
        runtime = LocalRuntime(context.settings.llm_base_url)
        runtime_thread = threading.Thread(target=runtime.start, daemon=True)
        QTimer.singleShot(0, runtime_thread.start)
    try:
        return app.exec()
    finally:
        QThreadPool.globalInstance().waitForDone()
        if runtime is not None:
            runtime.stop()
        if runtime_thread is not None and runtime_thread.ident is not None:
            runtime_thread.join(timeout=2)
        context.close()


__all__ = ["run"]
