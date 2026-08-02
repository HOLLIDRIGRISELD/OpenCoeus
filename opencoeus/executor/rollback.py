from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from ..db import AuditStore, BatchStatus, EntryStatus, TransactionBatch, TransactionEntry
from .holding import cleanup_holding_area
from .types import _batch_lock
from .verification import safe_move

logger = logging.getLogger(__name__)


def rollback_partial(
    moved: list[tuple],
    store: AuditStore,
) -> list[str]:
    errors: list[str] = []
    for entry, holding_path in reversed(moved):
        source = Path(entry.source_path)
        try:
            if holding_path.exists():
                safe_move(holding_path, source)
                store.update_entry(entry.id, status=EntryStatus.PENDING, holding_path=None, error_message=None)
            else:
                errors.append(f"Holding file missing for {entry.source_path}")
                store.update_entry(entry.id, status=EntryStatus.FAILED, error_message="Holding file missing")
        except Exception as exc:
            errors.append(f"Failed to restore {holding_path} to {source}: {exc}")
            logger.error("Rollback failed for %s: %s", holding_path, exc)
    return errors


def rollback_remaining(
    all_moved: list[tuple],
    completed: list[tuple],
    store: AuditStore,
    failed_entry_id: int | None = None,
) -> list[str]:
    logger = logging.getLogger(__name__)
    errors: list[str] = []
    completed_ids = {e.id for e, _ in completed}
    for entry, holding_path in reversed(all_moved):
        if entry.id in completed_ids:
            continue
        source = Path(entry.source_path)
        try:
            if holding_path.exists():
                safe_move(holding_path, source)
                if entry.id != failed_entry_id:
                    store.update_entry(entry.id, status=EntryStatus.PENDING, holding_path=None, error_message=None)
            else:
                errors.append(f"Holding file missing for {entry.source_path}")
                if entry.id != failed_entry_id:
                    store.update_entry(entry.id, status=EntryStatus.FAILED, error_message="Holding file missing")
        except Exception as exc:
            errors.append(f"Failed to restore {holding_path} to {source}: {exc}")
            logger.error("Rollback failed for %s: %s", holding_path, exc)
    return errors


def recover_crashed_batches(store: AuditStore) -> int:
    logger = logging.getLogger(__name__)
    _batch_lock.acquire(blocking=True)
    try:
        recovered = 0
        with store.session_factory() as session:
            crashed = list(session.scalars(
                select(TransactionBatch).where(TransactionBatch.status == BatchStatus.EXECUTING)
            ).all())
            for batch in crashed:
                batch.status = BatchStatus.FAILED
                recovered += 1
                for entry in session.scalars(
                    select(TransactionEntry).where(
                        TransactionEntry.batch_id == batch.id,
                        TransactionEntry.status == EntryStatus.MOVED_TO_HOLDING,
                    )
                ).all():
                    holding_path = Path(entry.holding_path) if entry.holding_path else None
                    source_path = Path(entry.source_path)
                    if holding_path and holding_path.exists():
                        try:
                            safe_move(holding_path, source_path)
                            entry.status = EntryStatus.FAILED
                            entry.error_message = "Batch crashed — file restored to original location"
                            entry.holding_path = None
                            logger.info("Restored %s to %s after crash", holding_path, source_path)
                        except Exception as exc:
                            entry.status = EntryStatus.FAILED
                            entry.error_message = f"Batch crashed — file in holding at {holding_path}: {exc}"
                            logger.error("Failed to restore %s: %s", holding_path, exc)
                    else:
                        entry.status = EntryStatus.FAILED
                        entry.error_message = "Batch crashed — holding file missing"
            session.commit()
        for batch in crashed:
            cleanup_holding_area(batch.id)
        return recovered
    finally:
        _batch_lock.release()
