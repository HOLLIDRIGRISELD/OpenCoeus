"""Organisation plans: preview, persist, approve and execute.

Two safety invariants are implemented here:

1. A plan is always built from *accepted or pending* suggestions and is shown as
   a preview before anything is written to the plan tables.
2. Execution requires an explicit :meth:`approve` call. The executor is the only
   component that moves files, and it enforces no-overwrite semantics.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from app.core.constants import (
    STATUS_ANALYSED,
    STATUS_ORGANISED,
    SUGGESTION_ACCEPTED,
    SUGGESTION_APPLIED,
)
from app.core.exceptions import InvalidRecommendationError, OperationConflictError
from app.core.logging_config import get_logger
from app.core.process_lock import DATA_LOCK_NAME, ProcessLock
from app.core.progress import (
    CancellationToken,
    OperationCancelled,
    ProgressCallback,
    ProgressEvent,
)
from app.domain.enums import PlanStatus
from app.domain.models import OperationResult, PlanItemView, PlannedAction, PlanSummary
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.infrastructure.repositories.batches import (
    COMPLETED,
    FAILED,
    HELD,
    PENDING,
    ROLLED_BACK,
    BatchRepository,
)
from app.infrastructure.repositories.files import FileRepository
from app.infrastructure.repositories.operations import OperationRepository
from app.organisation.executor import ExecutionReport, FileOperationExecutor
from app.organisation.fsops import move_no_overwrite, verify_destination
from app.organisation.planner import OrganisationPlanner, PlanDraft, PlanEntry, order_vacating_first
from app.organisation.validator import PathGuard, path_key
from app.processing.hashing import sha256_file
from app.search.indexer import SearchIndexer
from app.services.recommendation_service import RecommendationService
from app.services.settings_service import SettingsService

logger = get_logger(__name__)
_BATCH_LOCK = threading.Lock()


@dataclass(slots=True)
class BatchResult:
    """Outcome of a staged batch execution."""

    state: str
    completed: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    operation_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class OrganisationPreviews:
    """A preview plus the root it was calculated against."""

    draft: PlanDraft
    considered: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def summary(self) -> PlanSummary:
        return self.draft.summary


class OrganisationService:
    """Turns accepted recommendations into an auditable filesystem plan."""

    def __init__(
        self,
        files: FileRepository,
        analyses: AnalysisRepository,
        operations: OperationRepository,
        recommendations: RecommendationService,
        executor: FileOperationExecutor,
        settings: SettingsService,
        indexer: SearchIndexer,
        batches: BatchRepository,
        holding_root: Path,
    ) -> None:
        self._files = files
        self._analyses = analyses
        self._operations = operations
        self._recommendations = recommendations
        self._executor = executor
        self._settings = settings
        self._indexer = indexer
        self._batches = batches
        self._holding_root = holding_root
        self._lock = ProcessLock(holding_root.parent / DATA_LOCK_NAME)

    def organisation_root(self) -> Path:
        """Return the root that relative suggestions are resolved against.

        Preference order: the root recorded by the scanner, then the most
        common parent directory of known files, then a safe default.
        """

        configured = self._settings.organisation_root
        if configured is not None:
            return configured.expanduser().resolve(strict=False)
        candidates = self._files.root_candidates()
        if candidates:
            try:
                return Path(os.path.commonpath(candidates)).resolve(strict=False)
            except ValueError:
                return Path(candidates[0]).resolve(strict=False)
        return (Path.home() / "OpenCoeus Library").resolve(strict=False)

    def _validate_plan_paths(
        self, plan_id: int, items: Sequence[PlanItemView], root: Path
    ) -> None:
        guard = PathGuard(root)
        for item in items:
            check = guard.check_destination(
                Path(item.destination_path), source=Path(item.source_path)
            )
            errors = [issue for issue in check.errors if issue.code != "destination_exists"]
            if errors:
                raise InvalidRecommendationError(
                    f"Plan {plan_id} has an unsafe destination: {errors[0].message}"
                )

    def build_preview(
        self,
        *,
        limit: int = 500,
        accepted_only: bool = False,
    ) -> OrganisationPreviews:
        """Build a validated plan draft without writing to the database."""

        previews = OrganisationPreviews(draft=PlanDraft(root=self.organisation_root()))
        suggestions = self._recommendations.pending(limit=limit)
        if accepted_only:
            suggestions = [
                suggestion
                for suggestion in suggestions
                if suggestion.status == SUGGESTION_ACCEPTED
            ]
        previews.considered = len(suggestions)
        if not suggestions:
            previews.notes.append(
                "No suggestions are ready. Scan and analyse a folder first."
            )
            return previews

        entries: list[PlanEntry] = []
        records: dict[int, dict[str, object]] = {}
        for suggestion in suggestions:
            if not suggestion.suggested_value:
                continue
            bundle = self._analyses.get_suggestion_bundle(suggestion.file_id)
            if bundle is None:
                continue
            record = bundle.get("file") or {}
            records[suggestion.file_id] = record
            destination = bundle.get("destination_suggestion") or {}
            confidence = _combine_confidence(
                suggestion.confidence, destination.get("confidence")
            )
            folder = self._relative_folder(
                destination.get("value"),
                record,
                fallback_category=suggestion.category or record.get("category"),
            )
            notes = []
            if suggestion.explanation:
                notes.append(suggestion.explanation)
            if destination.get("explanation"):
                notes.append(str(destination["explanation"]))
            entries.append(
                PlanEntry(
                    file_id=suggestion.file_id,
                    source_path=Path(str(record.get("path") or suggestion.path)),
                    original_name=str(record.get("name") or suggestion.filename),
                    new_name=suggestion.suggested_value,
                    relative_folder=folder,
                    confidence=confidence,
                    suggestion_id=suggestion.id,
                    notes=notes,
                )
            )

        previews.draft = OrganisationPlanner(
            low_confidence=self._settings.low_confidence,
        ).plan(self.organisation_root(), entries)
        previews.notes.extend(previews.draft.warnings)
        if previews.draft.skipped:
            previews.notes.append(
                f"{len(previews.draft.skipped)} suggestion(s) were skipped during validation."
            )
        return previews

    def create_plan(self, *, limit: int = 500, accepted_only: bool = False) -> int:
        """Persist the current preview as a draft plan and return its id."""

        previews = self.build_preview(limit=limit, accepted_only=accepted_only)
        if not previews.draft.actions:
            raise InvalidRecommendationError(
                "There is nothing to plan: no file would change. "
                "Accept or review some recommendations first."
            )
        notes = " ".join(previews.notes) or None
        plan_id = self._operations.create_plan(
            previews.draft.root, previews.draft.actions, notes=notes
        )
        if previews.draft.blocked:
            logger.info(
                "Plan %s contains %d blocked action(s)", plan_id, len(previews.draft.blocked)
            )
        return plan_id

    def list_plans(self, limit: int = 50) -> list[dict[str, object]]:
        return self._operations.list_plans(limit=limit)

    def plan(self, plan_id: int) -> dict[str, object] | None:
        return self._operations.get_plan(plan_id)

    def items(self, plan_id: int) -> list[PlanItemView]:
        return self._operations.plan_items(plan_id)

    def summary(
        self, plan_id: int, items: Sequence[PlanItemView] | None = None
    ) -> PlanSummary:
        return self._operations.plan_summary(plan_id, items)

    def approve(self, plan_id: int) -> None:
        plan = self._operations.get_plan(plan_id)
        if plan is None:
            raise InvalidRecommendationError(f"Plan {plan_id} was not found.")
        if plan["status"] != PlanStatus.DRAFT.value:
            raise InvalidRecommendationError(
                f"Only draft plans can be approved (plan is {plan['status']})."
            )
        self._operations.update_plan_status(plan_id, PlanStatus.APPROVED)

    def execute(
        self,
        plan_id: int,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancellationToken | None = None,
        require_approval: bool = True,
    ) -> ExecutionReport:
        """Execute an approved plan through the no-overwrite executor.

        Args:
            plan_id: Persisted plan to execute.
            progress: Optional UI callback.
            cancel: Cooperative cancellation token.
            require_approval: When True (the default) a draft plan is refused.
        """

        with self._lock.locked():
            return self._execute_unlocked(
                plan_id,
                progress=progress,
                cancel=cancel,
                require_approval=require_approval,
            )

    def _execute_unlocked(
        self,
        plan_id: int,
        *,
        progress: ProgressCallback | None,
        cancel: CancellationToken | None,
        require_approval: bool,
    ) -> ExecutionReport:
        plan = self._operations.get_plan(plan_id)
        if plan is None:
            raise InvalidRecommendationError(f"Plan {plan_id} was not found.")
        status = str(plan["status"])
        if status == PlanStatus.EXECUTING.value:
            self._operations.update_plan_status(plan_id, PlanStatus.REVALIDATION_REQUIRED)
            raise InvalidRecommendationError(
                "This plan was interrupted during a previous run. Revalidate it before retrying."
            )
        if status in {
            PlanStatus.COMPLETED.value,
            PlanStatus.PARTIALLY_COMPLETED.value,
            PlanStatus.FAILED.value,
            PlanStatus.REVALIDATION_REQUIRED.value,
        }:
            raise InvalidRecommendationError(
                "This plan has already been executed. Revalidate it to try again."
            )
        if require_approval and status != PlanStatus.APPROVED.value:
            raise InvalidRecommendationError("Approve the plan before executing it.")

        root = Path(str(plan["root_path"]))
        plan_items = self._operations.plan_items(plan_id)
        self._validate_plan_paths(plan_id, plan_items, root)
        held_sources = self._batches.held_sources(plan_id)
        conflicts = self._recompute_conflicts(plan_items, root, held_sources)
        eligible = [
            item
            for item in plan_items
            if item.status != "completed" and conflicts[item.id] is None
        ]
        blocked = [
            item
            for item in plan_items
            if item.status != "completed" and conflicts[item.id] is not None
        ]
        records = self._files.light_records([item.file_id for item in eligible])
        actions: list[PlannedAction] = []
        for item in eligible:
            record = records.get(item.file_id, {})
            actions.append(
                PlannedAction(
                    file_id=item.file_id,
                    action=_action(item.action),
                    source_path=Path(item.source_path),
                    destination_path=Path(item.destination_path),
                    original_name=Path(item.source_path).name,
                    new_name=Path(item.destination_path).name,
                    confidence=item.confidence,
                    conflict=conflicts[item.id],
                    notes=item.notes,
                    plan_item_id=item.id,
                    expected_hash=str(record["hash"]) if record.get("hash") else None,
                )
            )
        actions = order_vacating_first(actions)
        if not actions:
            raise InvalidRecommendationError("This plan has no actions to execute.")

        for action in actions:
            record = records.get(action.file_id, {})
            size = record.get("size")
            source = held_sources.get(action.file_id, action.source_path)
            if not source.is_file() or (
                isinstance(size, int) and source.stat().st_size != size
            ):
                raise InvalidRecommendationError(
                    f"Source changed since it was scanned: {source}"
                )

        if not self._operations.claim_plan(
            plan_id, expected=PlanStatus.APPROVED if require_approval else PlanStatus(status)
        ):
            raise InvalidRecommendationError(
                f"Plan {plan_id} was claimed by another run. Revalidate it before retrying."
            )

        started = time.perf_counter()
        try:
            report = self._executor.execute(
                Path(str(plan["root_path"])),
                actions,
                plan_id=plan_id,
                progress=progress,
                cancel=cancel,
                sources=held_sources,
            )

            completed_ids = {result.file_id for result in report.completed}
            for held in self._batches.held_items(plan_id=plan_id):
                if held.file_id in completed_ids:
                    self._batches.set_item_state(held.batch_id, held.file_id, COMPLETED)

            for item in blocked:
                report.skipped.append(
                    OperationResult(
                        file_id=item.file_id,
                        action=_action(item.action),
                        source_path=Path(item.source_path),
                        destination_path=Path(item.destination_path),
                        success=False,
                        message=f"Skipped: {conflicts[item.id]}",
                    )
                )

            for result in report.completed:
                self._files.update_status(result.file_id, STATUS_ORGANISED)
                self._analyses.set_suggestion_status_for_file(result.file_id, SUGGESTION_APPLIED)

            if report.failed or report.skipped:
                final = (
                    PlanStatus.PARTIALLY_COMPLETED if report.completed else PlanStatus.FAILED
                )
            else:
                final = PlanStatus.COMPLETED
        except OperationCancelled:
            moved = any(item.status == "completed" for item in self._operations.plan_items(plan_id))
            self._operations.update_plan_status(
                plan_id,
                PlanStatus.PARTIALLY_COMPLETED if moved else PlanStatus.APPROVED,
            )
            raise
        except Exception:
            self._operations.update_plan_status(plan_id, PlanStatus.REVALIDATION_REQUIRED)
            raise

        self._operations.update_plan_status(plan_id, final)
        report.duration_seconds = round(time.perf_counter() - started, 3)
        logger.info("Plan %s finished: %s (%s)", plan_id, final.value, report.summary)
        return report

    def _recompute_conflicts(
        self,
        plan_items: Sequence[PlanItemView],
        root: Path,
        held_sources: dict[int, Path],
    ) -> dict[int, str | None]:
        """Recheck every item against the filesystem with chain-aware vacancy.

        Sources that another item will vacate are not treated as occupied, so
        rename chains survive both execution and revalidation.
        """
        guard = PathGuard(root)
        vacating: set[str] = set()
        for item in plan_items:
            source_key = path_key(Path(item.source_path))
            if (
                item.status != "completed"
                and item.conflict is None
                and source_key != path_key(Path(item.destination_path))
            ):
                vacating.add(source_key)
        conflicts: dict[int, str | None] = {}
        claimed: set[str] = set()
        for item in plan_items:
            if item.status == "completed":
                conflicts[item.id] = None
            else:
                source = held_sources.get(item.file_id, Path(item.source_path))
                destination = Path(item.destination_path)
                if path_key(source) == path_key(destination):
                    conflict = None
                else:
                    check = guard.check_destination(
                        destination, source=source, occupied=claimed, vacating=vacating
                    )
                    claimed.add(str(destination.resolve(strict=False)).lower())
                    source_errors = [
                        issue for issue in guard.check_source(source) if issue.is_error
                    ]
                    conflict = check.message or (
                        source_errors[0].message if source_errors else None
                    )
                conflicts[item.id] = conflict
            if conflicts[item.id] != item.conflict:
                self._operations.update_item_conflict(item.id, conflicts[item.id])
        return conflicts

    def execute_batch(
        self,
        plan_id: int,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancellationToken | None = None,
    ) -> BatchResult:
        """Execute a plan through a holding area with whole-batch rollback."""

        with self._lock.locked():
            if not _BATCH_LOCK.acquire(blocking=False):
                raise OperationConflictError("A batch execution is already running.")
            try:
                return self._execute_batch(plan_id, progress=progress, cancel=cancel)
            finally:
                _BATCH_LOCK.release()

    def _execute_batch(
        self,
        plan_id: int,
        *,
        progress: ProgressCallback | None,
        cancel: CancellationToken | None,
    ) -> BatchResult:
        plan = self._operations.get_plan(plan_id)
        if plan is None:
            raise InvalidRecommendationError(f"Plan {plan_id} was not found.")
        status = str(plan["status"])
        if status == PlanStatus.EXECUTING.value:
            self._operations.update_plan_status(plan_id, PlanStatus.REVALIDATION_REQUIRED)
            raise InvalidRecommendationError(
                "This plan was interrupted during a previous run. Revalidate it before retrying."
            )
        if status in {
            PlanStatus.COMPLETED.value,
            PlanStatus.PARTIALLY_COMPLETED.value,
            PlanStatus.FAILED.value,
            PlanStatus.REVALIDATION_REQUIRED.value,
        }:
            raise InvalidRecommendationError(
                "This plan has already been executed. Revalidate it to try again."
            )
        if status != PlanStatus.APPROVED.value:
            raise InvalidRecommendationError("Approve the plan before executing it.")

        root = Path(str(plan["root_path"]))
        plan_items = self._operations.plan_items(plan_id)
        self._validate_plan_paths(plan_id, plan_items, root)
        held_sources = self._batches.held_sources(plan_id)
        conflicts = self._recompute_conflicts(plan_items, root, held_sources)
        items = [
            item
            for item in plan_items
            if conflicts[item.id] is None and item.status != "completed"
        ]
        items_by_id = {item.id: item for item in items}
        actions = order_vacating_first(
            [
                PlannedAction(
                    file_id=item.file_id,
                    action=_action(item.action),
                    source_path=Path(item.source_path),
                    destination_path=Path(item.destination_path),
                    original_name=Path(item.source_path).name,
                    new_name=Path(item.destination_path).name,
                    confidence=item.confidence,
                    plan_item_id=item.id,
                )
                for item in items
            ]
        )
        items = [
            items_by_id[action.plan_item_id]
            for action in actions
            if action.plan_item_id in items_by_id and action.conflict is None
        ]
        if not items:
            batch_id = self._batches.create(plan_id, self._holding_root)
            self._batches.set_state(batch_id, COMPLETED)
            self._operations.update_plan_status(plan_id, PlanStatus.COMPLETED)
            return BatchResult(COMPLETED)

        records = self._files.light_records([item.file_id for item in items])
        for item in items:
            source = held_sources.get(item.file_id, Path(item.source_path))
            record = records.get(item.file_id, {})
            size = record.get("size")
            expected = record.get("hash")
            if not source.is_file() or (
                isinstance(size, int) and source.stat().st_size != size
            ) or (expected and sha256_file(source) != expected):
                raise OSError(f"Source changed since it was scanned: {source}")

        if not self._operations.claim_plan(plan_id):
            raise InvalidRecommendationError(
                f"Plan {plan_id} was claimed by another run. Revalidate it before retrying."
            )
        batch_id = self._batches.create(plan_id, self._holding_root)
        holding_dir = self._holding_root / f"batch-{batch_id}"
        self._batches.set_state(batch_id, PENDING)
        plan_item_ids = {item.file_id: item.id for item in items}
        completed: list[int] = []
        failed: list[int] = []
        operation_ids: list[int] = []
        operation_hashes: dict[int, str | None] = {}
        operation_ids_by_file: dict[int, int] = {}
        final_state = COMPLETED

        try:
            for index, item in enumerate(items, start=1):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                if progress:
                    progress(
                        ProgressEvent(
                            phase="execute",
                            current=index - 1,
                            total=len(items),
                            message=f"Staging {item.filename}",
                            item=item.source_path,
                        )
                    )
                original = Path(item.source_path)
                source = held_sources.get(item.file_id, original)
                final = Path(item.destination_path)
                holding = holding_dir / f"{item.file_id}{source.suffix}"
                record = records.get(item.file_id, {})
                size = record.get("size")
                expected = str(record["hash"]) if record.get("hash") else None
                operation_id = self._operations.record_operation(
                    file_id=item.file_id,
                    operation_type=_action(item.action),
                    source_path=original,
                    destination_path=final,
                    original_hash=expected,
                    plan_item_id=item.id,
                )
                operation_ids.append(operation_id)
                operation_hashes[item.file_id] = expected
                operation_ids_by_file[item.file_id] = operation_id
                try:
                    self._batches.record_item(batch_id, item.file_id, original, holding, final)
                    move_no_overwrite(source, holding, expected_hash=expected)
                    self._batches.set_item_state(batch_id, item.file_id, HELD)
                    self._batches.set_state(batch_id, HELD)
                    ok, reason = verify_destination(holding, expected_hash=expected)
                    if not ok:
                        raise OSError(reason or "The staged file failed verification.")
                    final.parent.mkdir(parents=True, exist_ok=True)
                    move_no_overwrite(holding, final, expected_hash=expected)
                    ok, reason = verify_destination(
                        final, expected_size=int(size) if isinstance(size, int) else None,
                        expected_hash=expected,
                    )
                    if not ok:
                        raise OSError(reason or "The organised file failed verification.")
                    self._batches.set_item_state(batch_id, item.file_id, COMPLETED)
                    self._files.update_location(item.file_id, final)
                    self._files.update_status(item.file_id, STATUS_ORGANISED)
                    self._analyses.set_suggestion_status_for_file(
                        item.file_id, SUGGESTION_APPLIED
                    )
                    try:
                        self._indexer.index_file(item.file_id)
                    except Exception:
                        logger.exception("Could not refresh the search index for %s", final.name)
                    self._operations.complete_operation(
                        operation_id, destination_hash=expected
                    )
                    self._operations.set_item_status(item.id, "completed")
                    completed.append(item.file_id)
                except Exception as exc:
                    failed.append(item.file_id)
                    self._operations.fail_operation(operation_id, str(exc))
                    self._operations.set_item_status(item.id, "failed")
                    raise
        except Exception as exc:
            final_state = FAILED
            logger.exception("Batch %s failed: %s", batch_id, exc)
            for record in reversed(self._batches.items_for_batch(batch_id)):
                reached_final = record.state == COMPLETED
                if reached_final:
                    source = record.final_path
                elif record.state in (PENDING, HELD):
                    source = record.holding_path
                    if not source.is_file() and record.final_path.is_file():
                        source = record.final_path
                        reached_final = True
                else:
                    continue
                if not source.is_file():
                    continue
                expected_hash = operation_hashes.get(record.file_id)
                if expected_hash:
                    ok, reason = verify_destination(source, expected_hash=expected_hash)
                    if not ok:
                        detail = f"Batch {batch_id} left {source} in place: {reason}"
                        logger.error(detail)
                        operation_id = operation_ids_by_file.get(record.file_id)
                        if operation_id is not None:
                            self._operations.add_event(operation_id, "rollback_failed", detail)
                        continue
                if record.original_path.exists():
                    logger.warning(
                        "Batch %s left %s in the holding area: original path is occupied",
                        batch_id,
                        source,
                    )
                    continue
                try:
                    move_no_overwrite(source, record.original_path)
                except Exception as restore_exc:
                    logger.warning(
                        "Batch %s could not restore %s: %s",
                        batch_id,
                        source,
                        restore_exc,
                    )
                    continue
                self._batches.set_item_state(batch_id, record.file_id, ROLLED_BACK)
                plan_item_id = plan_item_ids.get(record.file_id)
                if plan_item_id is not None:
                    self._operations.mark_plan_item_operations_rolled_back(plan_item_id)
                if reached_final:
                    self._files.update_location(record.file_id, record.original_path)
                    self._files.update_status(record.file_id, STATUS_ANALYSED)
                    self._analyses.set_suggestion_status_for_file(
                        record.file_id, SUGGESTION_ACCEPTED
                    )
                    if plan_item_id is not None:
                        self._operations.set_item_status(plan_item_id, "pending")
            self._operations.update_plan_status(plan_id, PlanStatus.FAILED)
        else:
            self._operations.update_plan_status(plan_id, PlanStatus.COMPLETED)

        self._batches.set_state(batch_id, final_state)
        return BatchResult(final_state, completed, failed, operation_ids)

    def revalidate(self, plan_id: int) -> PlanSummary:
        """Recheck an interrupted plan so it can be approved and retried.

        Items already completed are left untouched. Every other item is checked
        against the current filesystem; stale conflicts are cleared and newly
        discovered ones are recorded. The plan returns to ``draft`` so that a
        fresh, explicit approval is always required before another attempt.

        Raises:
            InvalidRecommendationError: If the plan cannot be revalidated.
        """

        with self._lock.locked():
            return self._revalidate_unlocked(plan_id)

    def _revalidate_unlocked(self, plan_id: int) -> PlanSummary:
        plan = self._operations.get_plan(plan_id)
        if plan is None:
            raise InvalidRecommendationError(f"Plan {plan_id} was not found.")
        status = str(plan["status"])
        if status == PlanStatus.COMPLETED.value:
            raise InvalidRecommendationError("A completed plan cannot be revalidated.")
        if status == PlanStatus.EXECUTING.value:
            raise InvalidRecommendationError(
                "An EXECUTING plan cannot be revalidated. Restart OpenCoeus if it was interrupted."
            )
        if status not in {
            PlanStatus.APPROVED.value,
            PlanStatus.FAILED.value,
            PlanStatus.PARTIALLY_COMPLETED.value,
            PlanStatus.REVALIDATION_REQUIRED.value,
        }:
            raise InvalidRecommendationError(
                f"Only approved or interrupted plans can be revalidated (plan is {status})."
            )

        held_sources = self._batches.held_sources(plan_id)
        plan_items = self._operations.plan_items(plan_id)
        conflicts = self._recompute_conflicts(
            plan_items, Path(str(plan["root_path"])), held_sources
        )
        for item in plan_items:
            same_path = path_key(Path(item.source_path)) == path_key(Path(item.destination_path))
            if not conflicts[item.id] and not same_path and item.status != "pending":
                self._operations.set_item_status(item.id, "pending")

        self._operations.update_plan_status(plan_id, PlanStatus.DRAFT)
        return self._operations.plan_summary(plan_id)

    def approve_and_execute(
        self,
        plan_id: int,
        *,
        progress: ProgressCallback | None = None,
        cancel: CancellationToken | None = None,
    ) -> ExecutionReport:
        """Convenience for the CLI: approve then execute immediately."""

        plan = self._operations.get_plan(plan_id)
        if plan is not None and plan["status"] == PlanStatus.DRAFT.value:
            self.approve(plan_id)
        return self.execute(plan_id, progress=progress, cancel=cancel)

    def _relative_folder(
        self,
        raw_destination: object,
        record: dict[str, object],
        *,
        fallback_category: object = None,
    ) -> Path:
        root = self.organisation_root()
        if isinstance(raw_destination, str) and raw_destination.strip():
            candidate = Path(raw_destination.strip().replace("\\", "/"))
            if candidate.is_absolute():
                try:
                    return candidate.resolve(strict=False).relative_to(root)
                except (OSError, ValueError):
                    pass
            elif ".." not in candidate.parts:
                return candidate
        if isinstance(fallback_category, str) and fallback_category.strip():
            parts = [part for part in fallback_category.split("/") if part]
            if parts:
                return Path(*parts)
        parent = Path(str(record.get("path") or "")).parent
        try:
            return parent.resolve(strict=False).relative_to(root)
        except (OSError, ValueError):
            return Path("Unclassified")


def _combine_confidence(name: object, folder: object) -> float:
    values: list[float] = []
    for raw in (name, folder):
        try:
            values.append(float(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _action(value: str):  # type: ignore[no-untyped-def]
    from app.domain.enums import ActionType

    try:
        return ActionType(value)
    except ValueError:
        return ActionType.RENAME_AND_MOVE


__all__ = ["OrganisationPreviews", "OrganisationService"]
