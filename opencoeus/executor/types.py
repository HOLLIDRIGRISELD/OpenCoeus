from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..config import default_application_data_directory

HOLDING_ROOT = default_application_data_directory() / "transactions"

_batch_lock = threading.Lock()


@dataclass
class ExecutionResult:
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    batch_id: int | None = None
