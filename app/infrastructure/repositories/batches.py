"""Tracks staged batch executions and their holding-area items."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.logging_config import get_logger
from app.infrastructure.database import Database
from app.infrastructure.models import BatchExecution, BatchExecutionItem

logger = get_logger(__name__)

PENDING = "PENDING"
HELD = "HELD"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
ROLLED_BACK = "ROLLED_BACK"
UNAVAILABLE = "UNAVAILABLE"
UNFINISHED = (PENDING, HELD, FAILED)


@dataclass(slots=True, frozen=True)
class HeldBatchItem:
    batch_id: int
    file_id: int
    original_path: Path
    holding_path: Path


@dataclass(slots=True, frozen=True)
class BatchItemRecord(HeldBatchItem):
    final_path: Path
    state: str


class BatchRepository:
    """Persists the holding-area state of a staged organisation batch."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, plan_id: int, holding_root: Path) -> int:
        root = Path(holding_root)
        with self._db.session() as session:
            batch = BatchExecution(plan_id=plan_id, holding_dir=root, state=PENDING)
            session.add(batch)
            session.flush()
            path = root / f"batch-{batch.id}"
            path.mkdir(parents=True, exist_ok=True)
            batch.holding_dir = path
            return batch.id

    def set_state(self, batch_id: int, state: str) -> None:
        with self._db.session() as session:
            batch = session.get(BatchExecution, batch_id)
            if batch is not None:
                batch.state = state

    def record_item(
        self,
        batch_id: int,
        file_id: int,
        original_path: Path,
        holding_path: Path,
        final_path: Path,
    ) -> None:
        with self._db.session() as session:
            session.add(
                BatchExecutionItem(
                    batch_id=batch_id,
                    file_id=file_id,
                    original_path=Path(original_path),
                    holding_path=Path(holding_path),
                    final_path=Path(final_path),
                    state=PENDING,
                )
            )

    def set_item_state(self, batch_id: int, file_id: int, state: str) -> None:
        with self._db.session() as session:
            item = session.scalars(
                select(BatchExecutionItem)
                .where(
                    BatchExecutionItem.batch_id == batch_id,
                    BatchExecutionItem.file_id == file_id,
                )
                .order_by(BatchExecutionItem.id.desc())
            ).first()
            if item is not None:
                item.state = state

    def get(self, batch_id: int) -> BatchExecution:
        with self._db.session() as session:
            batch = session.get(BatchExecution, batch_id)
            if batch is None:
                raise KeyError(f"Batch {batch_id} was not found.")
            return batch

    def unfinished(self) -> list[BatchExecution]:
        with self._db.session() as session:
            return list(
                session.scalars(
                    select(BatchExecution)
                    .where(BatchExecution.state.in_(UNFINISHED))
                    .order_by(BatchExecution.id)
                ).all()
            )

    def held_items(
        self, *, batch_id: int | None = None, plan_id: int | None = None
    ) -> list[HeldBatchItem]:
        with self._db.session() as session:
            stmt = (
                select(BatchExecutionItem)
                .join(BatchExecution)
                .where(BatchExecutionItem.state.in_((PENDING, HELD)))
            )
            if batch_id is not None:
                stmt = stmt.where(BatchExecution.id == batch_id)
            if plan_id is not None:
                stmt = stmt.where(BatchExecution.plan_id == plan_id)
            return [
                HeldBatchItem(
                    batch_id=item.batch_id,
                    file_id=item.file_id,
                    original_path=item.original_path,
                    holding_path=item.holding_path,
                )
                for item in session.scalars(stmt).all()
            ]

    def held_sources(self, plan_id: int) -> dict[int, Path]:
        return {item.file_id: item.holding_path for item in self.held_items(plan_id=plan_id)}

    def items_for_batch(self, batch_id: int) -> list[BatchItemRecord]:
        with self._db.session() as session:
            return [
                BatchItemRecord(
                    batch_id=item.batch_id,
                    file_id=item.file_id,
                    original_path=item.original_path,
                    holding_path=item.holding_path,
                    final_path=item.final_path,
                    state=item.state,
                )
                for item in session.scalars(
                    select(BatchExecutionItem)
                    .where(BatchExecutionItem.batch_id == batch_id)
                    .order_by(BatchExecutionItem.id)
                ).all()
            ]


def cleanup_stale_batches(db: Database) -> None:
    """Reconcile batch items against the filesystem after an interrupted run."""

    repo = BatchRepository(db)
    for batch in repo.unfinished():
        for item in repo.items_for_batch(batch.id):
            if item.state in (COMPLETED, ROLLED_BACK, UNAVAILABLE):
                continue
            if item.holding_path.is_file():
                if item.original_path.exists():
                    logger.warning(
                        "Batch %s left %s in holding: original path is occupied",
                        batch.id,
                        item.holding_path,
                    )
                repo.set_item_state(batch.id, item.file_id, HELD)
            elif item.final_path.is_file():
                repo.set_item_state(batch.id, item.file_id, COMPLETED)
            elif item.original_path.is_file():
                repo.set_item_state(batch.id, item.file_id, ROLLED_BACK)
            else:
                repo.set_item_state(batch.id, item.file_id, UNAVAILABLE)
                logger.warning(
                    "Batch %s cannot locate item %s: original, holding and final paths are missing",
                    batch.id,
                    item.file_id,
                )

        states = {item.state for item in repo.items_for_batch(batch.id)}
        if UNAVAILABLE in states:
            repo.set_state(batch.id, UNAVAILABLE)
        elif HELD in states or PENDING in states:
            repo.set_state(batch.id, HELD)
        elif COMPLETED in states:
            repo.set_state(batch.id, COMPLETED)
        else:
            repo.set_state(batch.id, ROLLED_BACK)
