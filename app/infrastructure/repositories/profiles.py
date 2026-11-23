"""Repository for named scan profiles."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.infrastructure.database import Database
from app.infrastructure.models import ScanProfile


class ScanProfileRepository:
    """Persist scan profiles without coupling them to application services."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> list[ScanProfile]:
        with self._db.session() as session:
            return list(session.scalars(select(ScanProfile).order_by(ScanProfile.name)).all())

    def get(self, profile_id: int) -> ScanProfile | None:
        with self._db.session() as session:
            return session.get(ScanProfile, profile_id)

    def get_by_name(self, name: str) -> ScanProfile | None:
        with self._db.session() as session:
            return session.scalar(select(ScanProfile).where(ScanProfile.name == name))

    def add(
        self,
        name: str,
        root_path: str,
        included_folders: Sequence[str],
        excluded_folders: Sequence[str],
        custom_patterns: Sequence[str],
    ) -> ScanProfile:
        profile = ScanProfile(
            name=name,
            root_path=root_path,
            included_folders=list(included_folders),
            excluded_folders=list(excluded_folders),
            custom_patterns=list(custom_patterns),
        )
        with self._db.session() as session:
            session.add(profile)
            session.flush()
            return profile

    def delete(self, profile_id: int) -> None:
        with self._db.session() as session:
            profile = session.get(ScanProfile, profile_id)
            if profile is not None:
                session.delete(profile)
