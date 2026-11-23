"""Human-in-the-loop review of filename and folder recommendations.

The service is the only place where a suggestion is accepted, rejected or
edited. Nothing here touches the filesystem: accepting a suggestion merely marks
it as ready for the organisation planner, which still requires an explicit
approval of the whole plan before any file is moved.

Every edit is validated with the same rules used by the generator, so a manually
typed filename cannot smuggle in characters or path components that the
automatic pipeline would reject.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.constants import (
    STATUS_ANALYSED,
    STATUS_PENDING_REVIEW,
    SUGGESTION_ACCEPTED,
    SUGGESTION_PENDING,
    SUGGESTION_REJECTED,
    UNCLASSIFIED,
)
from app.core.exceptions import InvalidRecommendationError
from app.core.logging_config import get_logger
from app.domain.models import SuggestionView
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.infrastructure.repositories.feedback import FeedbackRepository
from app.infrastructure.repositories.files import FileRepository
from app.intelligence.naming_engine import FilenameValidator
from app.services.settings_service import SettingsService

logger = get_logger(__name__)


@dataclass(slots=True)
class RecommendationDetail:
    """Everything the review pane needs for one file."""

    file_id: int
    filename: str
    path: str
    extension: str
    category: str | None = None
    confidence: float | None = None
    title: str | None = None
    document_type: str | None = None
    organisation: str | None = None
    document_date: str | None = None
    summary: str | None = None
    method: str | None = None
    suggested_name: str | None = None
    suggested_folder: str | None = None
    naming_explanation: str | None = None
    folder_explanation: str | None = None
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DuplicateGroup:
    """Files sharing an identical SHA-256 hash."""

    sha256: str
    files: list[dict[str, object]]

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def wasted_bytes(self) -> int:
        return sum(int(item.get("size") or 0) for item in self.files[1:])


@dataclass(slots=True)
class EditResult:
    """Outcome of a manual correction."""

    ok: bool
    value: str = ""
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


class RecommendationService:
    """Review, edit and accept suggestions.

    Args:
        files: File repository used for identity and duplicate lookups.
        analyses: Repository holding suggestions and analysis evidence.
        settings: Supplies the low-confidence review threshold.
        validator: Filename validator shared with the naming engine.
        feedback: Optional store for confirmed category decisions.
        model_name_provider: Supplies the active embedding model name.
        on_feedback: Called after a new decision is stored so caches can be rebuilt.
    """

    def __init__(
        self,
        files: FileRepository,
        analyses: AnalysisRepository,
        settings: SettingsService,
        validator: FilenameValidator | None = None,
        feedback: FeedbackRepository | None = None,
        model_name_provider: Callable[[], str] | None = None,
        on_feedback: Callable[[], None] | None = None,
    ) -> None:
        self._files = files
        self._analyses = analyses
        self._settings = settings
        self._validator = validator or FilenameValidator()
        self._feedback = feedback
        self._model_name_provider = model_name_provider
        self._on_feedback = on_feedback

    def pending(self, *, limit: int = 500) -> list[SuggestionView]:
        """Return filename suggestions awaiting review, best first."""

        return self._analyses.pending_suggestions(limit=limit)

    def detail(self, file_id: int) -> RecommendationDetail | None:
        record = self._files.get_record(file_id)
        if record is None:
            return None
        analysis = self._analyses.analysis_detail(file_id)
        bundle = self._analyses.get_suggestion_bundle(file_id) or {}
        filename_suggestion = bundle.get("filename_suggestion") or {}
        destination_suggestion = bundle.get("destination_suggestion") or {}
        evidence: list[str] = []
        warnings: list[str] = []

        for suggestion in self._analyses.suggestions_for_file(file_id).values():
            evidence.extend(suggestion.evidence or [])
            warnings.extend(suggestion.warnings or [])
        evidence.extend(analysis.get("evidence") or [])
        evidence.extend(analysis.get("extracted_evidence") or [])
        evidence.extend(analysis.get("inferred_evidence") or [])
        warnings.extend(analysis.get("uncertainties") or [])

        return RecommendationDetail(
            file_id=file_id,
            filename=str(record["name"]),
            path=str(record["path"]),
            extension=str(record["extension"] or ""),
            category=(analysis.get("category") or record.get("category")),
            confidence=analysis.get("confidence") or record.get("confidence"),
            title=analysis.get("title") or record.get("title"),
            document_type=analysis.get("document_type") or record.get("document_type"),
            organisation=analysis.get("organisation") or record.get("organisation"),
            document_date=analysis.get("document_date") or record.get("document_date"),
            summary=analysis.get("summary"),
            method=analysis.get("method"),
            suggested_name=filename_suggestion.get("value"),
            suggested_folder=destination_suggestion.get("value"),
            naming_explanation=filename_suggestion.get("explanation"),
            folder_explanation=destination_suggestion.get("explanation"),
            evidence=list(dict.fromkeys(item for item in evidence if item)),
            warnings=list(dict.fromkeys(item for item in warnings if item)),
            uncertainties=list(analysis.get("uncertainties") or []),
            tags=list(analysis.get("tags") or []),
        )

    def duplicates(self) -> list[DuplicateGroup]:
        groups: list[DuplicateGroup] = []
        sizes = {
            summary.id: summary.size
            for summary in self._files.list_summaries(limit=100_000)
        }
        for group in self._files.duplicate_groups():
            files = []
            for item in group.get("files", []):  # type: ignore[union-attr]
                file_id = int(item["id"])  # type: ignore[index]
                files.append(
                    {
                        "id": file_id,
                        "name": item["name"],  # type: ignore[index]
                        "path": item["path"],  # type: ignore[index]
                        "size": sizes.get(file_id, 0),
                    }
                )
            groups.append(DuplicateGroup(sha256=str(group["sha256"]), files=files))
        return groups

    def accept(self, file_id: int, *, mark_analysed: bool = True) -> None:
        """Accept every pending suggestion for a file."""

        self._analyses.set_suggestion_status_for_file(file_id, SUGGESTION_ACCEPTED)
        if mark_analysed:
            record = self._files.get_record(file_id)
            if record and record["status"] == STATUS_PENDING_REVIEW:
                self._files.update_status(file_id, STATUS_ANALYSED)

    def accept_many(self, file_ids: list[int]) -> int:
        accepted = 0
        for file_id in dict.fromkeys(file_ids):
            self.accept(file_id)
            accepted += 1
        return accepted

    def reject(self, file_id: int, *, reason: str | None = None) -> None:
        """Reject the suggestions and keep the file for a manual decision."""

        self._analyses.set_suggestion_status_for_file(file_id, SUGGESTION_REJECTED)
        self._files.update_status(file_id, STATUS_PENDING_REVIEW)
        if reason:
            logger.info("Suggestions rejected for file %s: %s", file_id, reason)

    def reset(self, file_id: int) -> None:
        """Return rejected or accepted suggestions to the pending state.

        Only suggestions that are currently in a terminal review state
        (accepted or rejected) are touched; ``applied`` and ``superseded``
        rows are left alone so a reset cannot resurrect stale or already-used
        advice. The file's processing status is restored to ``pending_review``
        when it was moved forward by an accept, keeping the review queue and
        the file record in agreement.
        """

        ids = self._analyses.suggestion_ids_for_file(file_id)
        changed = False
        for suggestion_type in ("filename", "destination", "category"):
            suggestion_id = ids.get(suggestion_type)
            if suggestion_id is None:
                continue
            current = self._analyses.suggestion_status(suggestion_id)
            if current not in {SUGGESTION_ACCEPTED, SUGGESTION_REJECTED}:
                continue
            if self._analyses.update_suggestion(suggestion_id, status=SUGGESTION_PENDING):
                changed = True
        if changed:
            record = self._files.get_record(file_id)
            if record is not None and record["status"] in {
                STATUS_ANALYSED,
                STATUS_PENDING_REVIEW,
            }:
                self._files.update_status(file_id, STATUS_PENDING_REVIEW)

    def set_filename(self, file_id: int, filename: str) -> EditResult:
        record = self._files.get_record(file_id)
        if record is None:
            raise InvalidRecommendationError("The file record no longer exists.")

        validation = self._validator.validate(
            filename, extension=str(record["extension"] or "")
        )
        if not validation.valid:
            return EditResult(
                False,
                validation.filename,
                warnings=validation.warnings,
                problems=["The filename is empty or contains characters that are not allowed."],
            )

        suggestion_id = self._analyses.suggestion_ids_for_file(file_id).get("filename")
        if suggestion_id is None:
            raise InvalidRecommendationError("This file has no filename suggestion to edit.")

        evidence = [
            f"Manually edited by the user on {Path(record['path']).name!r}.",
            "The filename was validated with the same rules used for generated names.",
        ]
        updated = self._analyses.update_suggestion(
            suggestion_id,
            value=validation.filename,
            status=SUGGESTION_ACCEPTED,
            explanation="The filename was edited manually and accepted by the user.",
            evidence=evidence,
            warnings=validation.warnings,
            confidence=1.0,
        )
        if updated:
            self._analyses.record_accepted_filename(file_id, validation.filename)
        return EditResult(True, validation.filename, warnings=validation.warnings)

    def set_folder(self, file_id: int, folder: str) -> EditResult:
        """Set a destination folder relative to the organisation root."""

        raw = folder.strip()
        candidate = raw.replace("\\", "/")
        relative = Path(candidate)
        problems: list[str] = []
        if not candidate:
            problems.append("The destination folder cannot be empty.")
        rooted = raw.startswith(("/", "\\")) or (len(raw) >= 2 and raw[1] == ":")
        if rooted or relative.is_absolute():
            problems.append("The destination must be relative to the organisation root.")
        if any(part == ".." for part in relative.parts):
            problems.append("The destination cannot leave the organisation root.")
        if any(part in {"", "."} for part in relative.parts) and candidate not in {"", "."}:
            relative = Path(*[part for part in relative.parts if part not in {"", "."}])
        if problems:
            return EditResult(False, candidate, problems=problems)

        suggestion_id = self._analyses.suggestion_ids_for_file(file_id).get("destination")
        if suggestion_id is None:
            raise InvalidRecommendationError("This file has no destination suggestion to edit.")
        self._analyses.update_suggestion(
            suggestion_id,
            value=relative.as_posix(),
            status=SUGGESTION_ACCEPTED,
            explanation="The destination folder was edited manually and accepted by the user.",
            evidence=["The destination is relative to the scanned organisation root."],
            warnings=[],
            confidence=1.0,
        )
        return EditResult(True, relative.as_posix())

    def set_category(self, file_id: int, category_path: str) -> None:
        """Apply a human category decision and update the suggested folder."""

        category_path = category_path.strip().strip("/") or UNCLASSIFIED
        if ".." in Path(category_path).parts:
            raise InvalidRecommendationError("The category path is not valid.")
        self._analyses.override_category(
            file_id,
            category_path,
            note=f"Category manually changed to {category_path} by the user.",
        )
        if self._feedback is not None and self._model_name_provider is not None:
            try:
                model_name = self._model_name_provider()
                vector = self._analyses.mean_document_vector(file_id, model_name)
                if vector is not None:
                    self._feedback.upsert(file_id, category_path, model_name, vector)
                    if self._on_feedback is not None:
                        self._on_feedback()
            except Exception as exc:
                logger.warning("Could not store classification feedback for %s: %s", file_id, exc)
        ids = self._analyses.suggestion_ids_for_file(file_id)
        category_id = ids.get("category")
        if category_id is not None:
            self._analyses.update_suggestion(
                category_id,
                value=category_path,
                status=SUGGESTION_ACCEPTED,
                explanation="The category was chosen by the user.",
                evidence=[f"Manually selected category: {category_path}"],
                warnings=[],
                confidence=1.0,
            )
        destination_id = ids.get("destination")
        if destination_id is not None:
            self._analyses.update_suggestion(
                destination_id,
                value=category_path,
                status=SUGGESTION_ACCEPTED,
                explanation="The folder follows the category chosen by the user.",
                evidence=[f"Manually selected category: {category_path}"],
                warnings=[],
                confidence=1.0,
            )
        self._files.update_status(file_id, STATUS_ANALYSED)

    @property
    def review_threshold(self) -> float:
        return self._settings.low_confidence


__all__ = [
    "DuplicateGroup",
    "EditResult",
    "RecommendationDetail",
    "RecommendationService",
]
