from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal


class AppState(QObject):
    state_changed = pyqtSignal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self._folder: Path | None = None
        self._folder_tree_flat: list[dict] = []
        self._excluded: set[str] = set()
        self._scan_result = None
        self._matches = []
        self._actions = []
        self._batches = []
        self._rules = []
        self._busy = False
        self._dark = True
        self.settings = None

    def _emit(self, key: str) -> None:
        self.state_changed.emit(key, getattr(self, f"_{key}", None))

    @property
    def folder(self) -> Path | None:
        return self._folder
    @folder.setter
    def folder(self, v: Path | None) -> None:
        self._folder = v
        self._emit("folder")

    @property
    def folder_tree_flat(self) -> list[dict]:
        return self._folder_tree_flat
    @folder_tree_flat.setter
    def folder_tree_flat(self, v: list[dict]) -> None:
        self._folder_tree_flat = v
        self._emit("folder_tree_flat")

    @property
    def excluded(self) -> set[str]:
        return self._excluded
    @excluded.setter
    def excluded(self, v: set[str]) -> None:
        self._excluded = v
        self._emit("excluded")

    @property
    def scan_result(self):
        return self._scan_result
    @scan_result.setter
    def scan_result(self, v) -> None:
        self._scan_result = v
        self._emit("scan_result")

    @property
    def matches(self) -> list:
        return self._matches
    @matches.setter
    def matches(self, v: list) -> None:
        self._matches = v
        self._emit("matches")

    @property
    def actions(self) -> list:
        return self._actions
    @actions.setter
    def actions(self, v: list) -> None:
        self._actions = v
        self._emit("actions")

    @property
    def batches(self) -> list:
        return self._batches
    @batches.setter
    def batches(self, v: list) -> None:
        self._batches = v
        self._emit("batches")

    @property
    def rules(self) -> list:
        return self._rules
    @rules.setter
    def rules(self, v: list) -> None:
        self._rules = v
        self._emit("rules")

    @property
    def busy(self) -> bool:
        return self._busy
    @busy.setter
    def busy(self, v: bool) -> None:
        self._busy = v
        self._emit("busy")

    @property
    def dark(self) -> bool:
        return self._dark
    @dark.setter
    def dark(self, v: bool) -> None:
        self._dark = v
        self._emit("dark")

    @property
    def scanned_count(self) -> int:
        if self._scan_result:
            return len(self._scan_result.rows)
        return 0

    @property
    def folder_count(self) -> int:
        return len(self._folder_tree_flat)

    @property
    def action_count(self) -> int:
        return len(self._actions)

    @property
    def batch_count(self) -> int:
        return len(self._batches)
