"""Extractor registry and dispatch."""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import ExtractionError, UnsupportedFormatError
from app.domain.models import ExtractionResult
from app.processing.extractors.base import BaseExtractor
from app.processing.extractors.docx import DocxExtractor
from app.processing.extractors.image import ImageExtractor
from app.processing.extractors.pdf import PdfExtractor
from app.processing.extractors.pptx import PptxExtractor
from app.processing.extractors.text import TextExtractor
from app.processing.extractors.xlsx import XlsxExtractor
from app.processing.file_signature import inspect_format


class ExtractorRegistry:
    """Maps a detected format to a concrete extractor."""

    def __init__(self, extractors: list[BaseExtractor] | None = None) -> None:
        self._extractors = extractors or [
            PdfExtractor(),
            DocxExtractor(),
            PptxExtractor(),
            XlsxExtractor(),
            TextExtractor(),
            ImageExtractor(enable_ocr=False),
        ]
        self._by_format: dict[str, BaseExtractor] = {}
        for extractor in self._extractors:
            for fmt in extractor.formats:
                self._by_format[fmt] = extractor

    def extractor_for(self, detected_format: str) -> BaseExtractor | None:
        return self._by_format.get(detected_format)

    def extract(self, path: Path, detected_format: str | None = None) -> ExtractionResult:
        """Dispatch to the right extractor.

        Raises:
            UnsupportedFormatError: If no extractor handles the detected format.
            ExtractionError: If the extractor fails.
        """

        fmt = detected_format or inspect_format(path)
        extractor = self._by_format.get(fmt)
        if extractor is None:
            raise UnsupportedFormatError(
                f"No extractor for {path.name} (detected format: {fmt})"
            )
        try:
            return extractor.extract(path)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Extraction failed for {path.name}: {exc}") from exc
