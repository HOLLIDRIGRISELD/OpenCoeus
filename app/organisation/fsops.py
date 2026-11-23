"""Filesystem primitives with a strict no-overwrite guarantee.

The public filesystem APIs cannot promise "move only if the destination does not
exist": ``os.replace`` overwrites, and a check-then-move sequence is racy. These
helpers reserve the destination name with ``O_CREAT | O_EXCL`` first, so a
collision is detected atomically even if another process is writing at the same
time. Cross-device moves fall back to copy → fsync → verify → delete.
"""

from __future__ import annotations

import contextlib
import errno
import os
import shutil
import uuid
from pathlib import Path

from app.core.exceptions import OperationConflictError
from app.core.logging_config import get_logger
from app.processing.hashing import sha256_file

logger = get_logger(__name__)


class HashMismatchError(OSError):
    """The copied file content does not match the source."""


def reserve_path(path: Path) -> None:
    """Atomically claim ``path``.

    Raises:
        OperationConflictError: If the path already exists.
    """

    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise OperationConflictError(f"A file already exists at {path}.") from exc
    else:
        os.close(descriptor)


def release_path(path: Path) -> None:
    """Remove a reservation created by :func:`reserve_path` (best effort)."""

    with contextlib.suppress(OSError):
        path.unlink()


def _rename_case_only(source: Path, destination: Path, expected_hash: str | None) -> None:
    """Rename a file whose destination differs only by case or path spelling.

    On case-insensitive filesystems (Windows, macOS by default) ``beta.txt`` and
    ``Beta.txt`` are the same path, so the normal reserve-then-move sequence
    would report a collision. Moving through a unique temporary name in the same
    directory makes the case change real while preserving the no-overwrite rule.
    """

    temporary = source.with_name(f".opencoeus-{uuid.uuid4().hex}{source.suffix}")
    reserve_path(temporary)
    try:
        os.replace(source, temporary)
    except BaseException:
        release_path(temporary)
        raise

    destination_reserved = False
    try:
        reserve_path(destination)
        destination_reserved = True
        os.replace(temporary, destination)
    except BaseException:
        if destination_reserved:
            release_path(destination)
        os.replace(temporary, source)
        raise

    if expected_hash:
        valid, reason = verify_destination(destination, expected_hash=expected_hash)
        if not valid:
            rollback = source.with_name(f".opencoeus-{uuid.uuid4().hex}{source.suffix}")
            reserve_path(rollback)
            try:
                os.replace(destination, rollback)
            except BaseException:
                release_path(rollback)
                raise
            try:
                os.replace(rollback, source)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.replace(rollback, destination)
                raise
            raise HashMismatchError(reason or "The renamed file failed verification.")


def move_no_overwrite(
    source: Path,
    destination: Path,
    *,
    expected_hash: str | None = None,
    verify_copy_hash: bool = True,
) -> None:
    """Move ``source`` to ``destination`` without ever overwriting a file.

    The destination is reserved first. On the same filesystem the move is an
    atomic ``os.replace`` of our own empty placeholder. Across filesystems the
    file is copied, flushed, optionally hash-verified and only then removed from
    the source.

    Raises:
        OperationConflictError: If the destination exists.
        OSError: For permission errors or failed verification.
    """

    source = Path(source)
    destination = Path(destination)
    if str(source) == str(destination):
        return
    if os.path.normcase(str(source)) == os.path.normcase(str(destination)):
        _rename_case_only(source, destination, expected_hash)
        return
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")

    reserve_path(destination)
    try:
        os.replace(source, destination)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            release_path(destination)
            raise

    try:
        shutil.copy2(source, destination)
        with destination.open("rb+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        if verify_copy_hash and expected_hash:
            copied = sha256_file(destination)
            if copied != expected_hash:
                raise HashMismatchError(
                    f"Copied content of {destination.name} does not match the source."
                )
        source.unlink()
    except BaseException:
        release_path(destination)
        raise


def verify_destination(
    destination: Path,
    *,
    expected_size: int | None = None,
    expected_hash: str | None = None,
) -> tuple[bool, str | None]:
    """Check size and, when available, the hash of a moved file."""

    if not destination.is_file():
        return False, "The destination file is missing after the move."
    if expected_size is not None and destination.stat().st_size != expected_size:
        return False, "The destination file size does not match the source."
    if expected_hash:
        actual = sha256_file(destination)
        if actual != expected_hash:
            return False, "The destination content hash does not match the source."
    return True, None
