"""Extractor interface and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.models import ExtractionResult
from app.intelligence.entities import (
    TITLE_SCAN_LINES,
    is_usable_title,
    normalise_title_candidate,
)

MAX_TEXT_CHARS = 2_000_000


class BaseExtractor(ABC):
    """Reads one family of document formats.

    Implementations must be side-effect free: they only read the file.
    """

    name: str = "base"
    version: str = "1"
    formats: tuple[str, ...] = ()

    def supports(self, detected_format: str) -> bool:
        return detected_format in self.formats

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        """Return extracted text and metadata.

        Raises:
            ExtractionError: If the document cannot be decoded.
        """

    @staticmethod
    def _truncate(text: str, warnings: list[str]) -> str:
        if len(text) <= MAX_TEXT_CHARS:
            return text
        warnings.append(
            f"Document text truncated to {MAX_TEXT_CHARS:,} characters for processing."
        )
        return text[:MAX_TEXT_CHARS]

    @staticmethod
    def _first_meaningful_line(text: str, max_length: int = 120) -> str | None:
        lines = [line for line in text.splitlines() if line.strip()][:TITLE_SCAN_LINES]
        for line in lines:
            candidate = normalise_title_candidate(line)
            if len(candidate) <= max_length and is_usable_title(candidate):
                return candidate
        return None
