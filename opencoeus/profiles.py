from __future__ import annotations

from dataclasses import dataclass, field

from .db import AuditStore, ScanProfile


@dataclass
class ProfileConfig:
    # IN MEMORY REPRESENTATION OF A SCAN PROFILE FOR EASY PASSING BETWEEN MODULES
    profile_id: int | None = None
    name: str = ""
    root_path: str = ""
    included_folders: list[str] = field(default_factory=list)
    excluded_folders: list[str] = field(default_factory=list)
    custom_protected_patterns: list[str] = field(default_factory=list)
    document_extraction: bool = True
    # STAGE 5: NLP SETTINGS
    nlp_confidence_threshold: float = 0.0
    naming_strategy: str = "nlp_enhanced"
    installer_action: str = "skip"
    # STAGE 5: LLM SETTINGS
    llm_enabled: bool = False
    llm_model: str = "phi3"
    llm_temperature: float = 0.3


def create_profile(
    store: AuditStore,
    name: str,
    root_path: str = "",
    included_folders: list[str] | None = None,
    excluded_folders: list[str] | None = None,
    custom_protected_patterns: list[str] | None = None,
    document_extraction: bool = True,
    llm_enabled: bool = False,
    llm_model: str = "phi3",
    llm_temperature: float = 0.3,
    naming_strategy: str = "nlp_enhanced",
) -> ProfileConfig:
    """Create a new scan profile in the database and return it as a profile config."""
    db_profile = store.create_profile(
        name=name,
        root_path=root_path,
        included_folders=included_folders,
        excluded_folders=excluded_folders,
        custom_protected_patterns=custom_protected_patterns,
        document_extraction=document_extraction,
        llm_enabled=llm_enabled,
        llm_model=llm_model,
        llm_temperature=llm_temperature,
        naming_strategy=naming_strategy,
    )
    return _db_profile_to_config(db_profile)


def load_profile(store: AuditStore, profile_id: int) -> ProfileConfig | None:
    """Load a scan profile by id and return it as a profile config, or none if not found."""
    db_profile = store.get_profile(profile_id)
    if db_profile is None:
        return None
    return _db_profile_to_config(db_profile)


def load_profile_by_name(store: AuditStore, profile_name: str) -> ProfileConfig | None:
    """Load a scan profile by name and return it as a profile config, or none if not found."""
    db_profile = store.get_profile_by_name(profile_name)
    if db_profile is None:
        return None
    return _db_profile_to_config(db_profile)


def list_profiles(store: AuditStore) -> list[ProfileConfig]:
    """Return all saved scan profiles as profile config objects ordered by name."""
    db_profiles = store.list_profiles()
    return [_db_profile_to_config(db_profile) for db_profile in db_profiles]


def update_profile(store: AuditStore, profile_id: int, **kwargs) -> ProfileConfig | None:
    """Update a scan profile and return the updated profile config, or none if not found."""
    db_profile = store.update_profile(profile_id, **kwargs)
    if db_profile is None:
        return None
    return _db_profile_to_config(db_profile)


def delete_profile(store: AuditStore, profile_id: int) -> bool:
    """Delete a scan profile and all associated data, returning true on success."""
    return store.delete_profile(profile_id)


def _db_profile_to_config(db_profile: ScanProfile) -> ProfileConfig:
    """Convert a database scan profile orm object into a lightweight profile config dataclass."""
    import json
    def _safe_json_list(value: str) -> list[str]:
        """Parse json string to list, returning empty list on malformed data."""
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
        nlp_confidence_threshold=getattr(db_profile, 'nlp_confidence_threshold', 0.0),
        installer_action=getattr(db_profile, 'installer_action', 'skip'),
        llm_enabled=getattr(db_profile, 'llm_enabled', False),
        llm_model=getattr(db_profile, 'llm_model', 'phi3'),
        llm_temperature=getattr(db_profile, 'llm_temperature', 0.3),
        naming_strategy=getattr(db_profile, 'naming_strategy', 'nlp_enhanced'),
    )
