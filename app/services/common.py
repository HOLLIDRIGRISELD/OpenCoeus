"""Shared service-layer types and helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.progress import (
    CancellationToken,
    OperationCancelled,
    ProgressCallback,
    ProgressEvent,
    emit,
)


@dataclass(slots=True)
class ServiceReport:
    """Common counters returned by scanning and analysis pipelines."""

    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.processed}/{self.total} processed, {self.skipped} skipped, "
            f"{self.failed} failed in {self.duration_seconds:.1f}s"
        )


__all__ = [
    "CancellationToken",
    "OperationCancelled",
    "ProgressCallback",
    "ProgressEvent",
    "ServiceReport",
    "emit",
]
