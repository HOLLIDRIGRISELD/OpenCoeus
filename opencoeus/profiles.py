from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .database import AuditStore
from .models import ScanProfile


@dataclass
class ProfileConfig:
    # IN-MEMORY REPRESENTATION OF A SCAN PROFILE FOR EASY PASSING BETWEEN MODULES.
    profile_id: int | None = None
    name: str = ""
    root_path: str = ""
    included_folders: list[str] = field(default_factory=list)
    excluded_folders: list[str] = field(default_factory=list)
    custom_protected_patterns: list[str] = field(default_factory=list)
    document_extraction: bool = True


def create_profile(
    store: AuditStore,
    name: str,
    root_path: str = "",
    included_folders: list[str] | None = None,
    excluded_folders: list[str] | None = None,
    custom_protected_patterns: list[str] | None = None,
    document_extraction: bool = True,
) -> ProfileConfig:
    # CREATES A NEW SCAN PROFILE IN THE DATABASE AND RETURNS IT AS A ProfileConfig.
    db_profile = store.create_profile(
        name=name,
        root_path=root_path,
        included_folders=included_folders,
        excluded_folders=excluded_folders,
        custom_protected_patterns=custom_protected_patterns,
        document_extraction=document_extraction,
    )
    return _db_profile_to_config(db_profile)


def load_profile(store: AuditStore, profile_id: int) -> ProfileConfig | None:
    # LOADS A SCAN PROFILE BY ID AND RETURNS IT AS A ProfileConfig, OR NONE IF NOT FOUND.
    db_profile = store.get_profile(profile_id)
    if db_profile is None:
        return None
    return _db_profile_to_config(db_profile)


def load_profile_by_name(store: AuditStore, profile_name: str) -> ProfileConfig | None:
    # LOADS A SCAN PROFILE BY NAME AND RETURNS IT AS A ProfileConfig, OR NONE IF NOT FOUND.
    db_profile = store.get_profile_by_name(profile_name)
    if db_profile is None:
        return None
    return _db_profile_to_config(db_profile)


def list_profiles(store: AuditStore) -> list[ProfileConfig]:
    # RETURNS ALL SAVED SCAN PROFILES AS ProfileConfig OBJECTS ORDERED BY NAME.
    db_profiles = store.list_profiles()
    return [_db_profile_to_config(db_profile) for db_profile in db_profiles]


def update_profile(store: AuditStore, profile_id: int, **kwargs) -> ProfileConfig | None:
    # UPDATES A SCAN PROFILE AND RETURNS THE UPDATED ProfileConfig, OR NONE IF NOT FOUND.
    # CONVERTS ProfileConfig LIST FIELDS TO PLAIN LISTS FOR THE DATABASE LAYER.
    serializable_keys = {"included_folders", "excluded_folders", "custom_protected_patterns"}
    for key in serializable_keys:
        if key in kwargs and isinstance(kwargs[key], ProfileConfig):
            continue
    db_profile = store.update_profile(profile_id, **kwargs)
    if db_profile is None:
        return None
    return _db_profile_to_config(db_profile)


def delete_profile(store: AuditStore, profile_id: int) -> bool:
    # DELETES A SCAN PROFILE AND ALL ASSOCIATED DATA, RETURNING TRUE ON SUCCESS.
    return store.delete_profile(profile_id)


def _db_profile_to_config(db_profile: ScanProfile) -> ProfileConfig:
    # CONVERTS A DATABASE ScanProfile ORM OBJECT INTO A LIGHTWEIGHT ProfileConfig DATACLASS.
    import json
    def _safe_json_list(value: str) -> list[str]:
        # PARSES JSON STRING TO LIST, RETURNING EMPTY LIST ON MALFORMED DATA.
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return ProfileConfig(
        profile_id=db_profile.id,
        name=db_profile.name,
        root_path=db_profile.root_path,
        included_folders=_safe_json_list(db_profile.included_folders),
        excluded_folders=_safe_json_list(db_profile.excluded_folders),
        custom_protected_patterns=_safe_json_list(db_profile.custom_protected_patterns),
        document_extraction=db_profile.document_extraction,
    )
