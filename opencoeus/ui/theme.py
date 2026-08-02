from __future__ import annotations

from PyQt6.QtWidgets import QPushButton


class Theme:
    def __init__(self, dark: bool = True) -> None:
        self.dark = dark
        self._rebuild()

    def _rebuild(self) -> None:
        if self.dark:
            self.bg          = "#0f1117"
            self.surface     = "#161822"
            self.surface2    = "#1c1e2e"
            self.surface3    = "#232538"
            self.border      = "#2a2d42"
            self.border_lt   = "#363a52"
            self.text        = "#e1e4ed"
            self.text2       = "#9498b0"
            self.text3       = "#5c6078"
            self.accent      = "#3b82f6"
            self.accent_hov  = "#60a5fa"
            self.accent_dim  = "#1d4ed8"
            self.green       = "#22c55e"
            self.red         = "#ef4444"
            self.yellow      = "#eab308"
            self.orange      = "#f97316"
            self.sidebar_bg  = "#0a0b12"
            self.status_bg   = "#1a1b2e"
        else:
            self.bg          = "#f5f6fa"
            self.surface     = "#ffffff"
            self.surface2    = "#f0f1f6"
            self.surface3    = "#e4e6ef"
            self.border      = "#d1d5e0"
            self.border_lt   = "#c4c8d8"
            self.text        = "#1a1b2e"
            self.text2       = "#6b7085"
            self.text3       = "#9ca0b5"
            self.accent      = "#2563eb"
            self.accent_hov  = "#3b82f6"
            self.accent_dim  = "#1d4ed8"
            self.green       = "#16a34a"
            self.red         = "#dc2626"
            self.yellow      = "#ca8a04"
            self.orange      = "#ea580c"
            self.sidebar_bg  = "#0a0b12"
            self.status_bg   = "#ffffff"

    def toggle(self) -> None:
        self.dark = not self.dark
        self._rebuild()

    def set_dark(self, dark: bool) -> None:
        if self.dark != dark:
            self.dark = dark
            self._rebuild()

    def btn_primary(self, text: str) -> QPushButton:
        return self._btn(text, self.accent, self.accent_hov, self.accent_dim)

    def btn_danger(self, text: str) -> QPushButton:
        return self._btn(text, self.red, "#f87171", "#dc2626")

    def _btn(self, text: str, bg: str, hover: str, pressed: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg}; color: #fff; border: none;
                border-radius: 6px; padding: 6px 16px;
                font-weight: 600; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {hover}; }}
            QPushButton:pressed {{ background-color: {pressed}; }}
            QPushButton:disabled {{
                background-color: {self.surface3}; color: {self.text3};
            }}
        """)
        return btn

    def global_stylesheet(self) -> str:
        t = self
        return f"""
            QMainWindow, QWidget#central {{ background-color: {t.bg}; }}
            QLabel {{ color: {t.text}; background: transparent; }}
            QLineEdit {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 6px 10px; font-size: 12px;
                selection-background-color: {t.accent}; selection-color: #fff;
            }}
            QLineEdit:focus {{ border-color: {t.accent}; }}
            QPushButton {{
                background-color: {t.surface2}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 6px 16px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {t.surface3}; border-color: {t.border_lt}; }}
            QPushButton:pressed {{ background-color: {t.border}; }}
            QPushButton:disabled {{ background-color: {t.surface}; color: {t.text3}; border-color: {t.surface3}; }}
            QComboBox {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 4px 8px; font-size: 12px; min-height: 24px;
            }}
            QComboBox:focus {{ border-color: {t.accent}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; selection-background-color: {t.surface3};
            }}
            QTableView {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 8px;
                gridline-color: {t.border}; outline: none; font-size: 13px;
                selection-background-color: {t.surface3}; selection-color: {t.accent};
            }}
            QTableView::item {{ padding: 6px 12px; }}
            QTableView::item:selected {{ background-color: {t.surface3}; color: {t.accent}; }}
            QTableView::item:hover {{ background-color: {t.surface2}; }}
            QHeaderView {{ background-color: {t.surface}; border: none; }}
            QHeaderView::section {{
                background-color: {t.surface2}; color: {t.text2};
                border: none; border-bottom: 2px solid {t.border};
                border-right: 1px solid {t.border};
                padding: 8px 12px; font-size: 11px; font-weight: 700;
            }}
            QTreeView {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 8px;
                outline: none; font-size: 13px;
                selection-background-color: {t.surface3}; selection-color: {t.accent};
            }}
            QTreeView::item {{ padding: 6px 12px; border-bottom: 1px solid {t.border}; min-height: 28px; }}
            QTreeView::item:selected {{ background-color: {t.surface3}; color: {t.accent}; }}
            QTreeView::item:hover {{ background-color: {t.surface2}; }}
            QStatusBar {{ background-color: {t.status_bg}; color: {t.text2}; font-size: 11px; border-top: 1px solid {t.border}; }}
            QScrollBar:vertical {{
                background: {t.surface}; width: 10px; margin: 0; border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{ background: {t.surface3}; min-height: 30px; border-radius: 5px; }}
            QScrollBar::handle:vertical:hover {{ background: {t.border_lt}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
            QScrollBar:horizontal {{
                background: {t.surface}; height: 10px; margin: 0; border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{ background: {t.surface3}; min-width: 30px; border-radius: 5px; }}
            QScrollBar::handle:horizontal:hover {{ background: {t.border_lt}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
            QProgressBar {{
                background-color: {t.surface}; border: 1px solid {t.border};
                border-radius: 6px; text-align: center; color: {t.text2};
                font-size: 11px; height: 14px;
            }}
            QProgressBar::chunk {{ background-color: {t.accent}; border-radius: 5px; }}
            QPlainTextEdit {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 8px; font-size: 12px;
                selection-background-color: {t.accent}; selection-color: #fff;
            }}
        """

    def dialog_stylesheet(self) -> str:
        t = self
        return f"""
            QDialog {{ background-color: {t.bg}; }}
            QLabel {{ color: {t.text}; background: transparent; }}
            QLineEdit {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 6px 10px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {t.accent}; }}
            QPushButton {{
                background-color: {t.surface2}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 6px 16px; font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {t.surface3}; border-color: {t.border_lt}; }}
            QComboBox {{
                background-color: {t.surface}; color: {t.text};
                border: 1px solid {t.border}; border-radius: 6px;
                padding: 4px 8px; font-size: 12px;
            }}
        """


THEME = Theme(dark=True)
