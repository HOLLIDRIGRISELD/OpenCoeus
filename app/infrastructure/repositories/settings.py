"""Repository for application settings, organisation rules and scan sessions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import select

from app.domain.models import utcnow
from app.infrastructure.database import Database
from app.infrastructure.models import Rule, ScanSession, Setting


class SettingsRepository:
    """Key/value settings with typed accessors."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._db.session() as session:
            setting = session.get(Setting, key)
            return setting.value if setting else default

    def get_float(self, key: str, default: float) -> float:
        raw = self.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def get_int(self, key: str, default: int) -> int:
        raw = self.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def set(self, key: str, value: str) -> None:
        with self._db.session() as session:
            setting = session.get(Setting, key)
            if setting is None:
                session.add(Setting(key=key, value=value))
            else:
                setting.value = value
                setting.updated_at = utcnow()

    def set_many(self, values: Mapping[str, str]) -> None:
        """Persist several keys in a single transaction.

        Either every key is written or none is, so a partially-applied settings
        update cannot leave the database out of sync with the in-memory config.
        """

        with self._db.session() as session:
            for key, value in values.items():
                setting = session.get(Setting, key)
                if setting is None:
                    session.add(Setting(key=key, value=value))
                else:
                    setting.value = value
                    setting.updated_at = utcnow()

    def all(self) -> dict[str, str]:
        with self._db.session() as session:
            return {setting.key: setting.value for setting in session.scalars(select(Setting)).all()}


class RuleRepository:
    """User-defined deterministic organisation rules."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_rules(self, *, enabled_only: bool = False) -> list[dict[str, object]]:
        with self._db.session() as session:
            stmt = select(Rule).order_by(Rule.priority, Rule.id)
            if enabled_only:
                stmt = stmt.where(Rule.enabled.is_(True))
            return [
                {
                    "id": rule.id,
                    "name": rule.name,
                    "priority": rule.priority,
                    "match_field": rule.match_field,
                    "match_op": rule.match_op,
                    "match_value": rule.match_value,
                    "target_folder": rule.target_folder,
                    "enabled": rule.enabled,
                }
                for rule in session.scalars(stmt).all()
            ]

    def add_rule(
        self,
        *,
        name: str,
        match_field: str,
        match_op: str,
        match_value: str,
        target_folder: str,
        priority: int = 100,
    ) -> int:
        with self._db.session() as session:
            rule = Rule(
                name=name,
                match_field=match_field,
                match_op=match_op,
                match_value=match_value,
                target_folder=target_folder,
                priority=priority,
            )
            session.add(rule)
            session.flush()
            return rule.id

    def set_enabled(self, rule_id: int, enabled: bool) -> None:
        with self._db.session() as session:
            rule = session.get(Rule, rule_id)
            if rule:
                rule.enabled = enabled

    def delete_rule(self, rule_id: int) -> None:
        with self._db.session() as session:
            rule = session.get(Rule, rule_id)
            if rule:
                session.delete(rule)


class ScanSessionRepository:
    """Records scan runs for the dashboard and diagnostics."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, root_path: Path) -> int:
        with self._db.session() as session:
            record = ScanSession(root_path=str(root_path), status="running")
            session.add(record)
            session.flush()
            return record.id

    def finish(
        self,
        session_id: int,
        *,
        discovered: int,
        processed: int,
        failed: int,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        with self._db.session() as session:
            record = session.get(ScanSession, session_id)
            if record is None:
                return
            record.discovered = discovered
            record.processed = processed
            record.failed = failed
            record.status = status
            record.error = error
            record.finished_at = utcnow()

    def recent(self, limit: int = 10) -> list[dict[str, object]]:
        with self._db.session() as session:
            records = session.scalars(
                select(ScanSession).order_by(ScanSession.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": record.id,
                    "root_path": record.root_path,
                    "status": record.status,
                    "discovered": record.discovered,
                    "processed": record.processed,
                    "failed": record.failed,
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                    "error": record.error,
                }
                for record in records
            ]
