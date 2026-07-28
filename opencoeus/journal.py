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


# PREPARE EXECUTION


def prepare_execution(store: AuditStore, profile_id: int, description: str = "") -> tuple[int, int]:
    """Create batch and entries from approved proposed action rows.
    Returns (batch_id, entry_count). Uses a single session to avoid N+1 opens."""
    from .hashing import sha256_file
    from .models import EntryStatus, TransactionBatch, TransactionEntry
    actions = store.get_proposed_actions(profile_id)
    approved = [a for a in actions if a.approved]
    logger.info("Preparing execution: profile %d, %d approved actions", profile_id, len(approved))
    if not approved:
        return (0, 0)
    # COUNT MOVES AND RENAMES FOR DESCRIPTIVE BATCH NAME
    move_count = sum(1 for a in approved if a.action_type == "move")
    rename_count = sum(1 for a in approved if a.action_type in {"rename", "move+rename"})
    parts = []
    if move_count:
        parts.append(f"{move_count} move{'s' if move_count != 1 else ''}")
    if rename_count:
        parts.append(f"{rename_count} rename{'s' if rename_count != 1 else ''}")
    default_description = ", ".join(parts) if parts else f"{len(approved)} actions"
    with store.session_factory() as session:
        batch = TransactionBatch(
            scan_profile_id=profile_id,
            description=description or default_description,
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
            original_name = action.original_filename or Path(action.original_path).name
            new_name = action.new_filename or Path(action.proposed_path).name
            entry = TransactionEntry(
                batch_id=batch.id,
                action_id=action.id,
                action_type=action.action_type,
                source_path=action.original_path,
                destination_path=action.proposed_path,
                original_filename=original_name,
                new_filename=new_name,
                source_hash=source_hash,
                source_size=source_size,
                status=EntryStatus.PENDING,
            )
            session.add(entry)
        session.commit()
    return (batch.id, len(approved))


# BATCH SUMMARY


def get_batch_summary(store: AuditStore, batch_id: int) -> BatchSummary:
    """Return counts by status for a batch using SQL GROUP BY (no N+1)."""
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


# EXECUTE ORCHESTRATION


def run_execution(
    batch_id: int,
    store: AuditStore,
    progress_callback=None,
) -> ExecutionResult:
    """Execute a batch and return the result."""
    logger.info("Executing batch %d", batch_id)
    return execute_batch(batch_id, store, progress_callback)


# UNDO ORCHESTRATION


def undo_last_batch(
    store: AuditStore,
    profile_id: int | None = None,
) -> tuple[int | None, list[str]]:
    """Find most recent completed batch and reverse all entries.
    Returns (batch_id, errors)."""
    batches = store.get_undoable_batches(profile_id)
    if not batches:
        return (None, ["No completed batches to undo"])
    batch = batches[0]
    logger.info("Undoing batch %d", batch.id)
    errors = undo_batch(batch.id, store)
    return (batch.id, errors)
