from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMConfig:
    enabled: bool = False
    model: str = "phi3"
    temperature: float = 0.3
    max_tokens: int = 128
    context_length: int = 2048
    n_threads: int = 4
    batch_size: int = 16
