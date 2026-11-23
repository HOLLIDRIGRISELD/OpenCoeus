"""Framework-independent domain objects.

These dataclasses are the vocabulary shared between services, the intelligence
layer and the UI. SQLAlchemy entities live in ``app.infrastructure.models`` and
are mapped to/from these objects by repositories and services.

Keeping them separate means that the classification and naming logic can be
unit-tested without a database, and the database can change without breaking
the algorithms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.enums import ActionType, ConfidenceBand


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used consistently throughout the system."""

    return datetime.now(UTC)


@dataclass(slots=True)
class ScannedFile:
    """A file discovered by the scanner, before any content analysis."""

    path: Path
    relative_path: Path
    filename: str
    extension: str
    size: int
    modified_at: datetime
    created_at: datetime | None = None
    mime_type: str | None = None
    detected_format: str | None = None
    sha256: str | None = None
    supported: bool = True
    error: str | None = None

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass(slots=True)
class ExtractionResult:
    """Outcome of reading a document's content."""

    text: str
    method: str
    success: bool = True
    page_count: int | None = None
    title: str | None = None
    author: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def quality(self) -> str:
        """Coarse extraction-quality indicator.

        This is deliberately simple: it is an indicator for triage, not a
        validated measure of document readability.
        """

        if not self.success or not self.text.strip():
            return "none"
        text = self.text.strip()
        controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
        printable_ratio = 1 - (controls / max(len(text), 1))
        if len(text) > 800 and printable_ratio > 0.98:
            return "high"
        if len(text) > 150 and printable_ratio > 0.9:
            return "medium"
        return "low"


@dataclass(slots=True)
class DocumentChunk:
    """A section of extracted text used for embedding and evidence."""

    index: int
    text: str
    page: int | None = None
    heading: str | None = None

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


@dataclass(slots=True)
class DocumentProfile:
    """Structured understanding of a document.

    ``extracted_*`` fields are directly supported by the document; the
    classification fields are inferences. The UI and database preserve this
    distinction so users can tell facts from AI suggestions.
    """

    file_id: int
    title: str | None = None
    document_type: str | None = None
    organisation: str | None = None
    document_date: str | None = None
    language: str = "en"
    keywords: list[str] = field(default_factory=list)
    summary: str | None = None
    extracted_evidence: list[str] = field(default_factory=list)
    inferred_evidence: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    title_supported: bool = False


@dataclass(slots=True)
class ClassificationResult:
    """Hybrid classification output for one document."""

    primary_category: str
    secondary_category: str | None
    category_path: str
    confidence: float
    method: str
    margin: float = 0.0
    tags: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    model_name: str | None = None
    model_version: str | None = None
    needs_review: bool = False

    def band(self, high: float = 0.85, low: float = 0.60) -> ConfidenceBand:
        """Return the confidence band using the caller's configured thresholds."""

        return ConfidenceBand.from_score(self.confidence, high, low)


@dataclass(slots=True)
class NamingSuggestion:
    """Proposed filename with the evidence used to build it."""

    original_name: str
    suggested_name: str
    confidence: float
    explanation: str
    template: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changed: bool = True


@dataclass(slots=True)
class FolderSuggestion:
    """Proposed destination directory relative to the scan root."""

    relative_destination: Path
    absolute_destination: Path
    confidence: float
    explanation: str
    evidence: list[str] = field(default_factory=list)
    is_new: bool = False


@dataclass(slots=True)
class PlannedAction:
    """One file operation inside an organisation plan."""

    file_id: int
    action: ActionType
    source_path: Path
    destination_path: Path
    original_name: str
    new_name: str
    confidence: float
    suggestion_id: int | None = None
    conflict: str | None = None
    notes: list[str] = field(default_factory=list)
    plan_item_id: int | None = None
    expected_hash: str | None = None


@dataclass(slots=True)
class PlanSummary:
    """Aggregate counts shown in the organisation planner."""

    total: int = 0
    renames: int = 0
    moves: int = 0
    new_folders: int = 0
    unchanged: int = 0
    conflicts: int = 0
    needs_review: int = 0


@dataclass(slots=True)
class SearchHit:
    """A single retrieval result."""

    file_id: int
    filename: str
    path: Path
    score: float
    mode: str
    snippet: str | None = None
    explanation: str | None = None
    category: str | None = None

    @property
    def match_percent(self) -> int:
        return max(0, min(100, round(self.score * 100)))


@dataclass(slots=True)
class SearchResponse:
    """Results plus metadata about how they were produced."""

    query: str
    mode: str
    hits: list[SearchHit] = field(default_factory=list)
    took_ms: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OperationResult:
    """Result of executing one planned filesystem action."""

    file_id: int
    action: ActionType
    source_path: Path
    destination_path: Path
    success: bool
    operation_id: int | None = None
    message: str | None = None
    undoable: bool = False




@dataclass(slots=True)
class FileSummary:
    """A file as presented in lists and detail panes."""

    id: int
    name: str
    path: str
    extension: str
    size: int
    modified_at: datetime | None
    status: str
    category: str | None = None
    confidence: float | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    is_available: bool = True


@dataclass(slots=True)
class ManifestRow:
    """A read-only audit record for one file in the CSV manifest."""

    path: str
    name: str
    size_bytes: int
    sha256: str
    status: str
    category: str
    modified_at: str
    last_planned_action: str
    last_operation_status: str


@dataclass(slots=True)
class SuggestionView:
    """A suggestion joined with the file it belongs to."""

    id: int
    file_id: int
    filename: str
    path: str
    suggestion_type: str
    original_value: str | None
    suggested_value: str
    confidence: float | None
    explanation: str | None
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "pending"
    category: str | None = None
    destination: str | None = None


@dataclass(slots=True)
class OperationView:
    """An executed operation as shown in the history page."""

    id: int
    file_id: int
    filename: str
    operation_type: str
    source_path: str
    destination_path: str
    status: str
    undoable: bool
    created_at: datetime | None
    completed_at: datetime | None
    error_message: str | None = None


@dataclass(slots=True)
class PlanItemView:
    """A persisted plan item with the information needed for review."""

    id: int
    plan_id: int
    file_id: int
    filename: str
    action: str
    source_path: str
    destination_path: str
    confidence: float
    conflict: str | None
    status: str
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DashboardStats:
    """Aggregate figures for the dashboard."""

    total_files: int = 0
    total_bytes: int = 0
    analysed: int = 0
    pending_review: int = 0
    duplicates: int = 0
    organised: int = 0
    failed: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    recent_operations: list[OperationView] = field(default_factory=list)
