"""SQLAlchemy ORM entities.

The schema is intentionally normalised around a stable ``files.id`` identity:
a file keeps the same database identity when it is renamed or moved, while every
historical path and operation is preserved separately.

SQLite is used as a single-user local store. Foreign keys are enforced on every
connection (see ``database.py``), and timestamps are stored as timezone-aware
UTC values.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.models import utcnow


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    parent: Mapped[Category | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Category]] = relationship(back_populates="parent")

    def path_parts(self) -> list[str]:
        parts = [self.name]
        node = self.parent
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return list(reversed(parts))

    def path_string(self) -> str:
        return "/".join(self.path_parts())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Category {self.path_string()}>"


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    current_name: Mapped[str] = mapped_column(String(512), nullable=False)

    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    current_path: Mapped[str] = mapped_column(Text, nullable=False)

    extension: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    detected_format: Mapped[str | None] = mapped_column(String(40), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    processing_status: Mapped[str] = mapped_column(String(40), default="discovered", nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_record_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_record_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    metadata_record: Mapped[FileMeta | None] = relationship(
        back_populates="file", cascade="all, delete-orphan", uselist=False
    )
    content: Mapped[DocumentContent | None] = relationship(
        back_populates="file", cascade="all, delete-orphan", uselist=False
    )
    chunks: Mapped[list[DocumentChunkRecord]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    analyses: Mapped[list[DocumentAnalysis]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    suggestions: Mapped[list[Suggestion]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    tags: Mapped[list[FileTag]] = relationship(back_populates="file", cascade="all, delete-orphan")
    operations: Mapped[list[Operation]] = relationship(back_populates="file")

    __table_args__ = (
        Index("ix_files_current_path", "current_path"),
        Index("ix_files_sha256", "sha256_hash"),
        Index("ix_files_status", "processing_status"),
        Index("ix_files_extension", "extension"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<File {self.id} {self.current_name!r}>"


class FileMeta(Base):
    __tablename__ = "file_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    file: Mapped[File] = relationship(back_populates="metadata_record")


class DocumentContent(Base):
    __tablename__ = "document_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    extraction_method: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    extractor_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    quality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    file: Mapped[File] = relationship(back_populates="content")


class DocumentChunkRecord(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("file_id", "chunk_index", name="uq_chunk_file_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    file: Mapped[File] = relationship(back_populates="chunks")
    embeddings: Mapped[list[Embedding]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_name", name="uq_embedding_chunk_model"),
        Index("ix_embeddings_file_model", "file_id", "model_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True
    )
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    chunk: Mapped[DocumentChunkRecord | None] = relationship(back_populates="embeddings")


class EmbeddingBlob(Base):
    __tablename__ = "embedding_blobs"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_name", name="uq_embedding_blob_chunk_model"),
        Index("ix_embedding_blobs_file_model", "file_id", "model_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True
    )
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class EmbeddingCacheBlob(Base):
    __tablename__ = "embedding_cache_blobs"
    __table_args__ = (
        UniqueConstraint(
            "model_name", "text_hash", name="uq_embedding_cache_blob_model_hash"
        ),
        Index("ix_embedding_cache_blob_model_hash", "model_name", "text_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class EmbeddingCacheEntry(Base):
    """Reusable vector for an exact text, independent of any file/chunk row."""

    __tablename__ = "embedding_cache"
    __table_args__ = (
        UniqueConstraint("model_name", "text_hash", name="uq_embedding_cache_model_hash"),
        Index("ix_embedding_cache_model_hash", "model_name", "text_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ClassificationFeedback(Base):
    """A confirmed human category decision, kept as a reusable vector prior."""

    __tablename__ = "classification_feedback"
    __table_args__ = (
        UniqueConstraint("file_id", name="uq_classification_feedback_file"),
        Index("ix_classification_feedback_model", "model_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    category_path: Mapped[str] = mapped_column(String(120), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    files: Mapped[list[FileTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class FileTag(Base):
    __tablename__ = "file_tags"

    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)

    file: Mapped[File] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship(back_populates="files")


class DocumentAnalysis(Base):
    __tablename__ = "document_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )

    document_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    organisation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_method: Mapped[str] = mapped_column(String(60), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(60), nullable=True)

    evidence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    uncertainties: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    analysis_status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    file: Mapped[File] = relationship(back_populates="analyses")
    category: Mapped[Category | None] = relationship()


class Suggestion(Base):
    __tablename__ = "suggestions"
    __table_args__ = (Index("ix_suggestions_file_type", "file_id", "suggestion_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )

    suggestion_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_value: Mapped[str] = mapped_column(Text, nullable=False)

    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    template: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    file: Mapped[File] = relationship(back_populates="suggestions")


class OrganisationPlan(Base):
    __tablename__ = "organisation_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[PlanItem]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("organisation_plans.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)

    action: Mapped[str] = mapped_column(String(30), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    destination_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    new_name: Mapped[str] = mapped_column(String(512), nullable=False)

    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conflict: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    plan: Mapped[OrganisationPlan] = relationship(back_populates="items")


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        Index("ix_operations_status", "status"),
        Index("ix_operations_file", "file_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)
    plan_item_id: Mapped[int | None] = mapped_column(ForeignKey("plan_items.id"), nullable=True)

    operation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    destination_path: Mapped[str] = mapped_column(Text, nullable=False)

    original_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    undoable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    file: Mapped[File] = relationship(back_populates="operations")
    events: Mapped[list[OperationEvent]] = relationship(
        back_populates="operation", cascade="all, delete-orphan"
    )


class OperationEvent(Base):
    __tablename__ = "operation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[int] = mapped_column(
        ForeignKey("operations.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    operation: Mapped[Operation] = relationship(back_populates="events")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    match_field: Mapped[str] = mapped_column(String(30), nullable=False)
    match_op: Mapped[str] = mapped_column(String(20), default="contains", nullable=False)
    match_value: Mapped[str] = mapped_column(Text, nullable=False)

    target_folder: Mapped[str] = mapped_column(Text, nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class OrganisationRule(Base):
    __tablename__ = "organisation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_field: Mapped[str] = mapped_column(String(30), nullable=False)
    match_op: Mapped[str] = mapped_column(String(20), default="equals", nullable=False)
    match_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    action: Mapped[str] = mapped_column(String(20), default="MOVE", nullable=False)
    folder_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    name_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ScanProfile(Base):
    __tablename__ = "scan_profiles"
    __table_args__ = (UniqueConstraint("name", name="uq_scan_profile_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    included_folders: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    excluded_folders: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    custom_patterns: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FileFingerprint(Base):
    __tablename__ = "file_fingerprints"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class AnalysisCacheEntry(Base):
    __tablename__ = "analysis_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    vectors: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class PathText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Path | str | None, dialect: object) -> str | None:
        return str(value) if value is not None else None

    def process_result_value(self, value: str | None, dialect: object) -> Path | None:
        return Path(value) if value is not None else None


class BatchExecution(Base):
    __tablename__ = "batch_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("organisation_plans.id", ondelete="CASCADE"), nullable=False
    )
    holding_dir: Mapped[Path] = mapped_column(PathText, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    items: Mapped[list[BatchExecutionItem]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class BatchExecutionItem(Base):
    __tablename__ = "batch_execution_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batch_executions.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)
    original_path: Mapped[Path] = mapped_column(PathText, nullable=False)
    holding_path: Mapped[Path] = mapped_column(PathText, nullable=False)
    final_path: Mapped[Path] = mapped_column(PathText, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)

    batch: Mapped[BatchExecution] = relationship(back_populates="items")
