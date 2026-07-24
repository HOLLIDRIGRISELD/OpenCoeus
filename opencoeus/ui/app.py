"""Application entry point for the OpenCoeus GUI."""
from __future__ import annotations

import sys

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from .theme import COLORS


def main() -> int:
    """Create and run the OpenCoeus application."""
    app = QApplication(sys.argv)
    app.setApplicationName("OpenCoeus")
    app.setApplicationVersion("0.1.0")
    app.setStyle("Fusion")

    # SET UP DARK PALETTE.
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface2"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    app.setPalette(palette)

    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()
