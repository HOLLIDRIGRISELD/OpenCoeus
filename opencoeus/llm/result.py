from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMGenerationResult:
    filename: str = ""
    destination: str = ""
    success: bool = False
    error: str = ""
    raw_output: str = ""
