from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from opencoeus.db import AuditStore
from opencoeus.rules.defaults import DEFAULT_RULES


class RuleController(QObject):
    rules_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, store: AuditStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store

    def _profile_id(self) -> int:
        profiles = self._store.list_profiles()
        if profiles:
            return profiles[0].id
        from opencoeus.profiles import create_profile
        p = create_profile(self._store, "default")
        return p.profile_id

    def load(self) -> list:
        pid = self._profile_id()
        db_rules = self._store.get_rules(pid)
        if not db_rules:
            for r in DEFAULT_RULES:
                self._store.add_rule(pid, r)
            db_rules = self._store.get_rules(pid)
        self.rules_loaded.emit(db_rules)
        return db_rules

    def add(self, rule: dict) -> None:
        try:
            self._store.add_rule(self._profile_id(), rule)
            self.load()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def update(self, rule_id: int, **kwargs) -> None:
        try:
            self._store.update_rule(rule_id, **kwargs)
            self.load()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def delete(self, rule_id: int) -> None:
        try:
            self._store.delete_rule(rule_id)
            self.load()
        except Exception as e:
            self.error_occurred.emit(str(e))

    def toggle(self, rule_id: int, enabled: bool | None = None) -> bool:
        return self._store.toggle_rule(rule_id, enabled)
