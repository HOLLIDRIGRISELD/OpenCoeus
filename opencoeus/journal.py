from __future__ import annotations

from dataclasses import dataclass

from .database import AuditStore
from .executor import execute_batch, undo_batch, ExecutionResult


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
    actions = store.get_proposed_actions(profile_id)
    approved = [a for a in actions if a.approved]
    if not approved:
        return (0, 0)
    batch = store.create_batch(profile_id, description or f"{len(approved)} file moves")
    for action in approved:
        # COMPUTE SOURCE HASH FOR PRE-EXECUTION VERIFICATION.
        source_hash = ""
        source_size = 0
        try:
            from pathlib import Path
            source = Path(action.original_path)
            if source.exists():
                source_size = source.stat().st_size
                from .hashing import sha256_file
                source_hash = sha256_file(source)
        except Exception:
            pass
        store.add_entry(
            batch.id,
            action.id,
            action.action_type,
            action.original_path,
            action.proposed_path,
            source_hash=source_hash,
            source_size=source_size,
        )
    return (batch.id, len(approved))


# ------------------------------------------------------------------ #
#  BATCH SUMMARY                                                        #
# ------------------------------------------------------------------ #


def get_batch_summary(store: AuditStore, batch_id: int) -> BatchSummary:
    # RETURNS COUNTS BY STATUS FOR A BATCH.
    all_entries = store.get_entries_by_batch(batch_id)
    completed = sum(1 for e in all_entries if e.status == "completed")
    failed = sum(1 for e in all_entries if e.status == "failed")
    pending = sum(1 for e in all_entries if e.status in {"pending", "moved_to_holding"})
    status = "completed" if completed == len(all_entries) else "failed" if failed > 0 else "in_progress"
    return BatchSummary(
        batch_id=batch_id,
        total=len(all_entries),
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
    errors = undo_batch(batch.id, store)
    return (batch.id, errors)
