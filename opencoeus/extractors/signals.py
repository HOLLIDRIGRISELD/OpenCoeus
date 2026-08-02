from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileSignals:
    text: str = ""
    metadata: dict = field(default_factory=dict)
    file_type: str = ""
    extension: str = ""
    confidence_hint: float = 0.5
    signals_present: list[str] = field(default_factory=list)
