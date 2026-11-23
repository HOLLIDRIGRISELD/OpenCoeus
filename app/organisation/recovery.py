"""Safe reversal of a completed operation.

Undo restores the original path only when that path is still free and the file
has not changed since it was organised. If either condition fails the operation
is invalidated with an explanation instead of guessing, because restoring a
modified file over an unknown path would risk data loss.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.constants import (
    STATUS_ANALYSED,
    STATUS_DISCOVERED,
    SUGGESTION_ACCEPTED,
    SUGGESTION_APPLIED,
)
from app.core.exceptions import RecoveryError
from app.core.logging_config import get_logger
from app.domain.enums import ActionType
from app.domain.models import OperationResult
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.infrastructure.repositories.files import FileRepository
from app.infrastructure.repositories.operations import OperationRepository
from app.organisation.executor import path_lock
from app.organisation.fsops import move_no_overwrite
from app.processing.hashing import sha256_file
from app.search.indexer import SearchIndexer

logger = get_logger(__name__)


class RecoveryManager:
    """Reverses completed operations while preserving data integrity.

    Args:
        files: File repository updated with the restored location.
        analyses: Used to decide the restored processing status.
        operations: Source of the operation log and status transitions.
        indexer: Keeps the full-text index consistent after an undo.
    """

    def __init__(
        self,
        files: FileRepository,
        analyses: AnalysisRepository,
        operations: OperationRepository,
        indexer: SearchIndexer,
    ) -> None:
        self._files = files
        self._analyses = analyses
        self._operations = operations
        self._indexer = indexer

    def undo(self, operation_id: int) -> OperationResult:
        """Restore one completed operation.

        Raises:
            RecoveryError: If the operation cannot be reversed safely.
        """

        operation = self._operations.get_operation(operation_id)
        if operation is None:
            raise RecoveryError(f"Operation {operation_id} was not found.")
        with path_lock(Path(operation["source_path"]), Path(operation["destination_path"])):
            return self._undo_operation(operation_id)

    def _undo_operation(self, operation_id: int) -> OperationResult:
        operation = self._operations.get_operation(operation_id)
        if operation is None:
            raise RecoveryError(f"Operation {operation_id} was not found.")
        if operation["status"] != "completed":
            raise RecoveryError("Only completed operations can be undone.")
        if not operation["undoable"]:
            raise RecoveryError("This operation is no longer undoable.")

        source = Path(operation["source_path"])
        destination = Path(operation["destination_path"])
        file_id = int(operation["file_id"])

        if not destination.exists():
            self._operations.invalidate_operation(
                operation_id, "Cannot undo: the organised file no longer exists."
            )
            raise RecoveryError(
                f"Cannot undo: {destination} no longer exists. The history entry was flagged."
            )
        if source.exists():
            try:
                same_physical_path = os.path.samefile(source, destination)
            except OSError:
                same_physical_path = os.path.normcase(os.path.abspath(source)) == os.path.normcase(
                    os.path.abspath(destination)
                )
            if not same_physical_path:
                self._operations.invalidate_operation(
                    operation_id, "Cannot undo: the original location is occupied."
                )
                raise RecoveryError(
                    f"Cannot undo: {source} already exists. Nothing was changed."
                )

        recorded_hash = operation.get("destination_hash")
        if recorded_hash:
            try:
                current_hash = sha256_file(destination)
            except OSError as exc:
                raise RecoveryError(f"Cannot read {destination}: {exc}") from exc
            if current_hash != recorded_hash:
                self._operations.invalidate_operation(
                    operation_id, "Cannot undo: the file changed after it was organised."
                )
                raise RecoveryError(
                    "Cannot undo: the file has changed since it was organised. "
                    "The history entry was flagged."
                )

        try:
            os.makedirs(source.parent, exist_ok=True)
            move_no_overwrite(
                destination,
                source,
                expected_hash=str(recorded_hash) if recorded_hash else None,
                verify_copy_hash=True,
            )
        except Exception as exc:
            logger.exception("Undo of operation %s failed", operation_id)
            self._operations.invalidate_operation(operation_id, f"Undo failed: {exc}")
            raise RecoveryError(f"Undo failed: {exc}") from exc

        self._files.update_location(file_id, source)
        restored_status = (
            STATUS_ANALYSED if self._analyses.latest_analysis(file_id) else STATUS_DISCOVERED
        )
        self._files.update_status(file_id, restored_status)
        for suggestion_type, suggestion_id in self._analyses.suggestion_ids_for_file(
            file_id
        ).items():
            if (
                suggestion_type in {"filename", "destination"}
                and self._analyses.suggestion_status(suggestion_id) == SUGGESTION_APPLIED
            ):
                self._analyses.set_suggestion_status(suggestion_id, SUGGESTION_ACCEPTED)
        try:
            self._indexer.index_file(file_id)
        except Exception:  # pragma: no cover - index refresh is best effort
            logger.exception("Could not refresh the search index after undo")

        self._operations.mark_operation_rolled_back(operation_id)
        return OperationResult(
            file_id=file_id,
            action=ActionType(str(operation["operation_type"])),
            source_path=destination,
            destination_path=source,
            success=True,
            operation_id=operation_id,
            message=f"Restored {source}",
            undoable=False,
        )

    def undoable(self, limit: int = 100):
        """Return operations that can currently be reversed."""

        return self._operations.undoable_operations(limit=limit)
