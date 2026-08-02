from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from opencoeus.config import database_url
from opencoeus.db import AuditStore

from .main_window import MainWindow


def run_ui(db_path: str | None = None) -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("OpenCoeus")

    conn_url = db_path or database_url()
    store = AuditStore(conn_url)

    window = MainWindow(store)
    window.show()

    sys.exit(app.exec())
