"""Domain enums shared by services, the database and the UI."""

from __future__ import annotations

from enum import StrEnum


class FileStatus(StrEnum):
    """Lifecycle of a discovered file."""

    DISCOVERED = "discovered"
    PENDING_EXTRACTION = "pending_extraction"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    PENDING_ANALYSIS = "pending_analysis"
    ANALYSING = "analysing"
    ANALYSED = "analysed"
    PENDING_REVIEW = "pending_review"
    ORGANISED = "organised"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"
    SUPERSEDED = "superseded"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    REVALIDATION_REQUIRED = "revalidation_required"


class OperationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class ActionType(StrEnum):
    RENAME = "rename"
    MOVE = "move"
    RENAME_AND_MOVE = "rename_and_move"
    CREATE_DIRECTORY = "create_directory"


class SuggestionType(StrEnum):
    FILENAME = "filename"
    DESTINATION = "destination"
    CATEGORY = "category"
    TAG = "tag"


class ConfidenceBand(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float, high: float = 0.85, low: float = 0.60) -> ConfidenceBand:
        if score >= high:
            return cls.HIGH
        if score >= low:
            return cls.MEDIUM
        return cls.LOW


class SearchMode(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
