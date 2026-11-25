"""Repository for organisation plans, operations and audit events."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, select, update

from app.core.exceptions import DatabaseError
from app.domain.enums import ActionType, OperationStatus, PlanStatus
from app.domain.models import OperationView, PlanItemView, PlannedAction, PlanSummary, utcnow
from app.infrastructure.database import Database
from app.infrastructure.models import (
    File,
    Operation,
    OperationEvent,
    OrganisationPlan,
    PlanItem,
)


class OperationRepository:
    """Persists plans and the append-only history of filesystem operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create_plan(self, root_path: Path, actions: list[PlannedAction], notes: str | None = None) -> int:
        with self._db.session() as session:
            plan = OrganisationPlan(
                root_path=str(root_path),
                status=PlanStatus.DRAFT.value,
                notes=notes,
            )
            session.add(plan)
            session.flush()
            for action in actions:
                session.add(
                    PlanItem(
                        plan_id=plan.id,
                        file_id=action.file_id,
                        action=action.action.value,
                        source_path=str(action.source_path),
                        destination_path=str(action.destination_path),
                        original_name=action.original_name,
                        new_name=action.new_name,
                        confidence=action.confidence,
                        conflict=action.conflict,
                        notes=action.notes,
                        status="pending",
                    )
                )
            return plan.id

    def update_plan_status(self, plan_id: int, status: PlanStatus) -> None:
        with self._db.session() as session:
            plan = session.get(OrganisationPlan, plan_id)
            if plan is None:
                raise DatabaseError(f"Plan {plan_id} was not found.")
            plan.status = status.value
            if status is PlanStatus.APPROVED:
                plan.approved_at = utcnow()
            if status in {PlanStatus.COMPLETED, PlanStatus.PARTIALLY_COMPLETED, PlanStatus.FAILED}:
                plan.completed_at = utcnow()

    def reset_status(self, current: PlanStatus, target: PlanStatus) -> int:
        """Move stale plans to a recoverable status at startup."""

        with self._db.session() as session:
            result = session.execute(
                update(OrganisationPlan)
                .where(OrganisationPlan.status == current.value)
                .values(status=target.value)
            )
            return result.rowcount

    def claim_plan(
        self,
        plan_id: int,
        expected: PlanStatus = PlanStatus.APPROVED,
        next_status: PlanStatus = PlanStatus.EXECUTING,
    ) -> bool:
        """Atomically move a plan from ``expected`` to ``next_status``."""

        with self._db.session() as session:
            result = session.execute(
                update(OrganisationPlan)
                .where(
                    OrganisationPlan.id == plan_id,
                    OrganisationPlan.status == expected.value,
                )
                .values(status=next_status.value)
            )
            return result.rowcount > 0

    def get_plan(self, plan_id: int) -> dict[str, object] | None:
        with self._db.session() as session:
            plan = session.get(OrganisationPlan, plan_id)
            if plan is None:
                return None
            return {
                "id": plan.id,
                "root_path": plan.root_path,
                "status": plan.status,
                "notes": plan.notes,
                "created_at": plan.created_at,
                "approved_at": plan.approved_at,
                "completed_at": plan.completed_at,
            }

    def list_plans(self, limit: int = 50) -> list[dict[str, object]]:
        with self._db.session() as session:
            plans = session.scalars(
                select(OrganisationPlan).order_by(OrganisationPlan.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": plan.id,
                    "root_path": plan.root_path,
                    "status": plan.status,
                    "created_at": plan.created_at,
                    "item_count": session.scalar(
                        select(func.count(PlanItem.id)).where(PlanItem.plan_id == plan.id)
                    )
                    or 0,
                }
                for plan in plans
            ]

    def plan_items(self, plan_id: int) -> list[PlanItemView]:
        with self._db.session() as session:
            rows = session.execute(
                select(PlanItem, File.current_name)
                .join(File, File.id == PlanItem.file_id)
                .where(PlanItem.plan_id == plan_id)
                .order_by(PlanItem.destination_path, PlanItem.new_name)
            ).all()
            return [
                PlanItemView(
                    id=item.id,
                    plan_id=item.plan_id,
                    file_id=item.file_id,
                    filename=filename,
                    action=item.action,
                    source_path=item.source_path,
                    destination_path=item.destination_path,
                    confidence=item.confidence,
                    conflict=item.conflict,
                    status=item.status,
                    notes=list(item.notes or []),
                )
                for item, filename in rows
            ]

    def plan_summary(
        self, plan_id: int, items: Sequence[PlanItemView] | None = None
    ) -> PlanSummary:
        items = self.plan_items(plan_id) if items is None else list(items)
        summary = PlanSummary(total=len(items))
        folders: set[Path] = set()
        for item in items:
            if item.conflict:
                summary.conflicts += 1
            if item.action in {ActionType.MOVE.value, ActionType.RENAME_AND_MOVE.value}:
                summary.moves += 1
            if item.action in {ActionType.RENAME.value, ActionType.RENAME_AND_MOVE.value}:
                summary.renames += 1
            if item.source_path == item.destination_path:
                summary.unchanged += 1
            if item.confidence < 0.60:
                summary.needs_review += 1
            folders.add(Path(item.destination_path).parent)
        summary.new_folders = sum(1 for folder in folders if not folder.exists())
        return summary

    def set_item_status(self, item_id: int, status: str) -> None:
        with self._db.session() as session:
            item = session.get(PlanItem, item_id)
            if item is None:
                raise DatabaseError(f"Plan item {item_id} was not found.")
            item.status = status

    def update_item_conflict(self, item_id: int, conflict: str | None) -> None:
        """Refresh the validation conflict recorded on a plan item."""

        with self._db.session() as session:
            item = session.get(PlanItem, item_id)
            if item is None:
                raise DatabaseError(f"Plan item {item_id} was not found.")
            item.conflict = conflict

    def record_operation(
        self,
        *,
        file_id: int,
        operation_type: ActionType,
        source_path: Path,
        destination_path: Path,
        original_hash: str | None,
        plan_item_id: int | None = None,
    ) -> int:
        with self._db.session() as session:
            operation = Operation(
                file_id=file_id,
                plan_item_id=plan_item_id,
                operation_type=operation_type.value,
                source_path=str(source_path),
                destination_path=str(destination_path),
                original_hash=original_hash,
                status=OperationStatus.PENDING.value,
                undoable=False,
            )
            session.add(operation)
            session.flush()
            session.add(
                OperationEvent(
                    operation_id=operation.id,
                    event_type="recorded",
                    detail=f"{operation_type.value}: {source_path} -> {destination_path}",
                )
            )
            return operation.id

    def add_event(self, operation_id: int, event_type: str, detail: str | None = None) -> None:
        with self._db.session() as session:
            session.add(OperationEvent(operation_id=operation_id, event_type=event_type, detail=detail))

    def complete_operation(self, operation_id: int, *, destination_hash: str | None) -> None:
        with self._db.session() as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise DatabaseError(f"Operation {operation_id} was not found.")
            operation.status = OperationStatus.COMPLETED.value
            operation.destination_hash = destination_hash
            operation.undoable = True
            operation.completed_at = utcnow()
            session.add(
                OperationEvent(
                    operation_id=operation.id,
                    event_type="verified",
                    detail=f"sha256={destination_hash}" if destination_hash else "size verified",
                )
            )

    def fail_operation(self, operation_id: int, message: str) -> None:
        with self._db.session() as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise DatabaseError(f"Operation {operation_id} was not found.")
            operation.status = OperationStatus.FAILED.value
            operation.error_message = message
            operation.undoable = False
            session.add(
                OperationEvent(operation_id=operation.id, event_type="failed", detail=message)
            )

    def mark_operation_rolled_back(self, operation_id: int) -> None:
        with self._db.session() as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise DatabaseError(f"Operation {operation_id} was not found.")
            operation.status = OperationStatus.ROLLED_BACK.value
            operation.undoable = False
            session.add(
                OperationEvent(
                    operation_id=operation.id, event_type="rolled_back", detail="original location restored"
                )
            )

    def mark_plan_item_operations_rolled_back(self, plan_item_id: int) -> None:
        """Mark all operations recorded for a plan item as rolled back."""

        with self._db.session() as session:
            operation_ids = list(
                session.scalars(
                    select(Operation.id).where(Operation.plan_item_id == plan_item_id)
                ).all()
            )
            session.execute(
                update(Operation)
                .where(Operation.plan_item_id == plan_item_id)
                .values(status=OperationStatus.ROLLED_BACK.value, undoable=False)
            )
            for operation_id in operation_ids:
                session.add(
                    OperationEvent(
                        operation_id=operation_id,
                        event_type="rolled_back",
                        detail="original location restored",
                    )
                )

    def invalidate_operation(self, operation_id: int, reason: str) -> None:
        with self._db.session() as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                raise DatabaseError(f"Operation {operation_id} was not found.")
            operation.undoable = False
            operation.error_message = reason

    def list_operations(self, *, limit: int = 200, status: str | None = None) -> list[OperationView]:
        with self._db.session() as session:
            stmt = (
                select(Operation, File.current_name)
                .join(File, File.id == Operation.file_id)
                .order_by(Operation.id.desc())
                .limit(limit)
            )
            if status:
                stmt = stmt.where(Operation.status == status)
            rows = session.execute(stmt).all()
            return [
                OperationView(
                    id=operation.id,
                    file_id=operation.file_id,
                    filename=filename,
                    operation_type=operation.operation_type,
                    source_path=operation.source_path,
                    destination_path=operation.destination_path,
                    status=operation.status,
                    undoable=operation.undoable,
                    created_at=operation.created_at,
                    completed_at=operation.completed_at,
                    error_message=operation.error_message,
                )
                for operation, filename in rows
            ]

    def get_operation(self, operation_id: int) -> dict[str, object] | None:
        with self._db.session() as session:
            operation = session.get(Operation, operation_id)
            if operation is None:
                return None
            file = session.get(File, operation.file_id)
            return {
                "id": operation.id,
                "file_id": operation.file_id,
                "filename": file.current_name if file else "",
                "operation_type": operation.operation_type,
                "source_path": Path(operation.source_path),
                "destination_path": Path(operation.destination_path),
                "original_hash": operation.original_hash,
                "destination_hash": operation.destination_hash,
                "status": operation.status,
                "undoable": operation.undoable,
                "created_at": operation.created_at,
                "completed_at": operation.completed_at,
                "error_message": operation.error_message,
            }

    def undoable_operations(self, limit: int = 100) -> list[OperationView]:
        with self._db.session() as session:
            rows = session.execute(
                select(Operation, File.current_name)
                .join(File, File.id == Operation.file_id)
                .where(Operation.undoable.is_(True), Operation.status == OperationStatus.COMPLETED.value)
                .order_by(Operation.id.desc())
                .limit(limit)
            ).all()
            return [
                OperationView(
                    id=operation.id,
                    file_id=operation.file_id,
                    filename=filename,
                    operation_type=operation.operation_type,
                    source_path=operation.source_path,
                    destination_path=operation.destination_path,
                    status=operation.status,
                    undoable=operation.undoable,
                    created_at=operation.created_at,
                    completed_at=operation.completed_at,
                )
                for operation, filename in rows
            ]
