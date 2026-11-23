"""Repository for opt-in user-defined organisation rules."""

from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.database import Database
from app.infrastructure.models import OrganisationRule


class OrganisationRuleRepository:
    """CRUD for richer rules, kept separate from the legacy ``rules`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[OrganisationRule]:
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(OrganisationRule).order_by(OrganisationRule.priority, OrganisationRule.id)
                ).all()
            )

    def get(self, rule_id: int) -> OrganisationRule | None:
        with self._db.session() as session:
            return session.get(OrganisationRule, rule_id)

    def enabled(self) -> list[OrganisationRule]:
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(OrganisationRule)
                    .where(OrganisationRule.enabled.is_(True))
                    .order_by(OrganisationRule.priority, OrganisationRule.id)
                ).all()
            )

    def add(
        self,
        name: str,
        match_field: str,
        match_op: str,
        match_value: str,
        folder_template: str,
        *,
        action: str = "MOVE",
        name_template: str = "",
        priority: int = 100,
        enabled: bool = True,
    ) -> int:
        rule = OrganisationRule(
            name=name,
            match_field=match_field,
            match_op=match_op,
            match_value=match_value,
            folder_template=folder_template,
            action=action,
            name_template=name_template,
            priority=priority,
            enabled=enabled,
        )
        with self._db.session() as session:
            session.add(rule)
            session.flush()
            return rule.id

    def set_enabled(self, rule_id: int, enabled: bool) -> None:
        with self._db.session() as session:
            rule = session.get(OrganisationRule, rule_id)
            if rule is not None:
                rule.enabled = enabled

    def delete(self, rule_id: int) -> None:
        with self._db.session() as session:
            rule = session.get(OrganisationRule, rule_id)
            if rule is not None:
                session.delete(rule)

    def seed_disabled_examples(self) -> None:
        if self.list():
            return
        self.add(
            "PDFs",
            "extension",
            "equals",
            ".pdf",
            "PDFs",
            enabled=False,
        )
        self.add(
            "Invoices",
            "name",
            "contains",
            "invoice",
            "Invoices",
            enabled=False,
        )
