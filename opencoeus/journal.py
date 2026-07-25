from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .database import AuditStore
from .executor import execute_batch, undo_batch, ExecutionResult
from .hashing import sha256_file
from .models import BatchStatus, EntryStatus

logger = logging.getLogger(__name__)


@dataclass
class BatchSummary:
    batch_id: int
    total: int
    completed: int
    failed: int
    pending: int
    status: str


# ------------------------------------------------------------------ #
#  PREPARE EXECUTION                                                    #
# ------------------------------------------------------------------ #


def prepare_execution(store: AuditStore, profile_id: int, description: str = "") -> tuple[int, int]:
    # CREATES A BATCH AND ENTRIES FROM APPROVED PROPOSED ACTION ROWS.
    # RETURNS (BATCH_ID, ENTRY_COUNT).
    # USES A SINGLE SESSION FOR ALL ENTRIES (AVOIDS N+1 SESSION OPENS).
    from .hashing import sha256_file
    from .models import EntryStatus, TransactionBatch, TransactionEntry
    actions = store.get_proposed_actions(profile_id)
    approved = [a for a in actions if a.approved]
    logger.info("Preparing execution: profile %d, %d approved actions", profile_id, len(approved))
    if not approved:
        return (0, 0)
    with store.session_factory() as session:
        batch = TransactionBatch(
            scan_profile_id=profile_id,
            description=description or f"{len(approved)} file moves",
            status=BatchStatus.PENDING,
        )
        session.add(batch)
        session.flush()
        for action in approved:
            source_hash = ""
            source_size = 0
            try:
                source = Path(action.original_path)
                if source.exists():
                    source_size = source.stat().st_size
                    source_hash = sha256_file(source)
            except Exception as exc:
                logger.warning("Hash computation failed for %s: %s", action.original_path, exc)
            entry = TransactionEntry(
                batch_id=batch.id,
                action_id=action.id,
                action_type=action.action_type,
                source_path=action.original_path,
                destination_path=action.proposed_path,
                source_hash=source_hash,
                source_size=source_size,
                status=EntryStatus.PENDING,
            )
            session.add(entry)
        session.commit()
    return (batch.id, len(approved))


# ------------------------------------------------------------------ #
#  BATCH SUMMARY                                                        #
# ------------------------------------------------------------------ #


def get_batch_summary(store: AuditStore, batch_id: int) -> BatchSummary:
    # RETURNS COUNTS BY STATUS FOR A BATCH USING SQL GROUP BY (NO N+1).
    from sqlalchemy import func, select
    from .models import TransactionEntry
    with store.session_factory() as session:
        rows = session.execute(
            select(TransactionEntry.status, func.count(TransactionEntry.id))
            .where(TransactionEntry.batch_id == batch_id)
            .group_by(TransactionEntry.status)
        ).all()
        status_counts = {status: count for status, count in rows}
    total = sum(status_counts.values())
    completed = status_counts.get(EntryStatus.COMPLETED, 0)
    failed = status_counts.get(EntryStatus.FAILED, 0)
    pending = status_counts.get(EntryStatus.PENDING, 0) + status_counts.get(EntryStatus.MOVED_TO_HOLDING, 0)
    status = "completed" if completed == total else "failed" if failed > 0 else "in_progress"
    return BatchSummary(
        batch_id=batch_id,
        total=total,
        completed=completed,
        failed=failed,
        pending=pending,
        status=status,
    )


# ------------------------------------------------------------------ #
#  EXECUTE ORCHESTRATION                                                #
# ------------------------------------------------------------------ #


def run_execution(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> ExecutionResult:
    # EXECUTES A BATCH AND RETURNS THE RESULT.
    logger.info("Executing batch %d", batch_id)
    return execute_batch(batch_id, store, progress_callback)


# ------------------------------------------------------------------ #
#  UNDO ORCHESTRATION                                                   #
# ------------------------------------------------------------------ #


def undo_last_batch(
    store: AuditStore,
    profile_id: int | None = None,
) -> tuple[int | None, list[str]]:
    # FINDS MOST RECENT COMPLETED BATCH AND REVERSES ALL ENTRIES.
    # RETURNS (BATCH_ID, ERRORS).
    batches = store.get_undoable_batches(profile_id)
    if not batches:
        return (None, ["No completed batches to undo"])
    batch = batches[0]
    logger.info("Undoing batch %d", batch.id)
    errors = undo_batch(batch.id, store)
    return (batch.id, errors)
