"""Named scan profiles and the persisted active-profile choice."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.infrastructure.database import Database
from app.infrastructure.models import ScanProfile
from app.infrastructure.repositories.profiles import ScanProfileRepository
from app.infrastructure.repositories.settings import SettingsRepository

ACTIVE_PROFILE_KEY = "scan.active_profile_id"


@dataclass(frozen=True, slots=True)
class ScanProfileView:
    """Immutable profile data used by scanning and the read-only UI summary."""

    id: int
    name: str
    root_path: str
    included_folders: tuple[str, ...]
    excluded_folders: tuple[str, ...]
    custom_patterns: tuple[str, ...]


class ProfileService:
    """Manage scan profiles without touching analysis or classification state."""

    def __init__(self, db: Database) -> None:
        self._profiles = ScanProfileRepository(db)
        self._settings = SettingsRepository(db)

    @staticmethod
    def _view(profile: ScanProfile) -> ScanProfileView:
        return ScanProfileView(
            id=profile.id,
            name=profile.name,
            root_path=profile.root_path,
            included_folders=tuple(profile.included_folders),
            excluded_folders=tuple(profile.excluded_folders),
            custom_patterns=tuple(profile.custom_patterns),
        )

    def list(self) -> list[ScanProfileView]:
        return [self._view(profile) for profile in self._profiles.list()]

    def get(self, profile_id: int) -> ScanProfileView | None:
        profile = self._profiles.get(profile_id)
        return self._view(profile) if profile is not None else None

    def get_by_name(self, name: str) -> ScanProfileView | None:
        profile = self._profiles.get_by_name(name)
        return self._view(profile) if profile is not None else None

    def add(
        self,
        name: str,
        root: str,
        included: Sequence[str],
        excluded: Sequence[str],
        patterns: Sequence[str],
    ) -> int:
        profile = self._profiles.add(name, root, included, excluded, patterns)
        return profile.id

    def delete(self, profile_id: int) -> None:
        current = self.active()
        self._profiles.delete(profile_id)
        if current is not None and current.id == profile_id:
            self._settings.set(ACTIVE_PROFILE_KEY, "")

    def set_active(self, profile_id: int | None) -> None:
        if profile_id is not None and self.get(profile_id) is None:
            return
        self._settings.set(ACTIVE_PROFILE_KEY, "" if profile_id is None else str(profile_id))

    def active(self) -> ScanProfileView | None:
        raw = self._settings.get(ACTIVE_PROFILE_KEY)
        if not raw:
            return None
        try:
            profile_id = int(raw)
        except ValueError:
            return None
        return self.get(profile_id)
