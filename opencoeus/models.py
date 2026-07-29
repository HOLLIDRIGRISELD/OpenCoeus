from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BatchStatus(StrEnum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNDONE = "UNDONE"


class EntryStatus(StrEnum):
    PENDING = "PENDING"
    MOVED_TO_HOLDING = "MOVED_TO_HOLDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNDONE = "UNDONE"


class Base(DeclarativeBase):
    pass


class FileAudit(Base):
    __tablename__ = "file_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(Text, unique=True, index=True)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="scanned")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    # STAGE 2: EXTENDED COLUMNS FOR RULE MATCHING AND FOLDER DISPLAY
    relative_path: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    extension: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    folder_path: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)


class NamingHistory(Base):
    __tablename__ = "naming_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggested_title: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    # STAGE 2: SCOPE TITLES PER SCAN PROFILE
    scan_profile_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scan_profiles.id"), nullable=True)


class ScanProfile(Base):
    __tablename__ = "scan_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    root_path: Mapped[str] = mapped_column(Text, default="")
    # STAGE 2: JSON ARRAYS FOR FOLDER INCLUSION EXCLUSION LISTS
    included_folders: Mapped[str] = mapped_column(Text, default="[]")
    excluded_folders: Mapped[str] = mapped_column(Text, default="[]")
    custom_protected_patterns: Mapped[str] = mapped_column(Text, default="[]")
    document_extraction: Mapped[bool] = mapped_column(Boolean, default=True)
    # STAGE 5: NLP SETTINGS
    nlp_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.0)
    naming_strategy: Mapped[str] = mapped_column(String(16), default="nlp_enhanced")
    installer_action: Mapped[str] = mapped_column(String(16), default="skip")
    # STAGE 5: LLM ENHANCEMENT SETTINGS
    llm_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    llm_model: Mapped[str] = mapped_column(String(64), default="phi3")
    llm_temperature: Mapped[float] = mapped_column(Float, default=0.3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class FolderClassification(Base):
    __tablename__ = "folder_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_profiles.id"))
    folder_path: Mapped[str] = mapped_column(Text, index=True)
    # STAGE 2: CLASSIFICATION TYPE, RECOMMENDED ACTION, AND USER OVERRIDE
    classification: Mapped[str] = mapped_column(String(32))
    recommended_action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")
    user_override: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class OrganizationRule(Base):
    __tablename__ = "organization_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_profiles.id"))
    name: Mapped[str] = mapped_column(String(255))
    rule_type: Mapped[str] = mapped_column(String(32))
    # STAGE 2: JSON CONFIG FOR TYPE SPECIFIC RULE PARAMETERS
    rule_config: Mapped[str] = mapped_column(Text, default="{}")
    destination_template: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # STAGE 4: ACTION TYPE (MOVE, RENAME, MOVE AND RENAME) AND RENAME TEMPLATE
    action_type: Mapped[str] = mapped_column(String(32), default="move")
    rename_template: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class ProposedAction(Base):
    __tablename__ = "proposed_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_profiles.id"))
    original_path: Mapped[str] = mapped_column(Text, index=True)
    proposed_path: Mapped[str] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("organization_rules.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    # STAGE 4: ORIGINAL AND PROPOSED FILENAMES FOR RENAME ACTIONS
    original_filename: Mapped[str] = mapped_column(Text, default="")
    new_filename: Mapped[str] = mapped_column(Text, default="")
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("transaction_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class TransactionBatch(Base):
    __tablename__ = "transaction_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_profiles.id"), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TransactionEntry(Base):
    __tablename__ = "transaction_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("transaction_batches.id"), index=True)
    action_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("proposed_actions.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(32))
    source_path: Mapped[str] = mapped_column(Text)
    destination_path: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64), default="")
    destination_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    original_filename: Mapped[str] = mapped_column(Text, default="")
    new_filename: Mapped[str] = mapped_column(Text, default="")
    holding_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
