"""PDF text extraction using PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.core.exceptions import ExtractionError
from app.domain.models import ExtractionResult
from app.processing.extractors.base import BaseExtractor


class PdfExtractor(BaseExtractor):
    name = "pdf"
    version = "1.0"
    formats = ("pdf",)

    def extract(self, path: Path) -> ExtractionResult:
        warnings: list[str] = []
        try:
            document = pymupdf.open(path)
        except Exception as exc:
            raise ExtractionError(f"Cannot open PDF {path.name}: {exc}") from exc

        try:
            if document.needs_pass:
                return ExtractionResult(
                    text="",
                    method=self.name,
                    success=False,
                    error="PDF is password protected",
                    warnings=["Password-protected PDFs are not processed."],
                )
            metadata = document.metadata or {}
            pages: list[str] = []
            empty_pages = 0
            for page in document:
                page_text = page.get_text("text") or ""
                if len(page_text.strip()) < 20:
                    empty_pages += 1
                pages.append(page_text)

            text = "\n\f\n".join(pages).strip()
            if empty_pages and empty_pages >= max(1, len(pages) // 2):
                warnings.append(
                    "Most pages contain little selectable text; this PDF may be scanned and require OCR."
                )
            if not text:
                warnings.append("No selectable text was found in this PDF.")

            title = (metadata.get("title") or "").strip() or self._first_meaningful_line(text)
            author = (metadata.get("author") or "").strip() or None

            return ExtractionResult(
                text=self._truncate(text, warnings),
                method=self.name,
                success=True,
                page_count=document.page_count,
                title=title,
                author=author,
                warnings=warnings,
                meta={"producer": metadata.get("producer"), "empty_pages": empty_pages},
            )
        finally:
            document.close()
