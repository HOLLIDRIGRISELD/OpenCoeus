"""DOCX extraction using python-docx."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from app.core.exceptions import ExtractionError
from app.domain.models import ExtractionResult
from app.processing.extractors.archive import enforce_archive_limits
from app.processing.extractors.base import BaseExtractor


class DocxExtractor(BaseExtractor):
    name = "docx"
    version = "1.0"
    formats = ("docx",)

    def extract(self, path: Path) -> ExtractionResult:
        warnings: list[str] = []
        enforce_archive_limits(path)
        try:
            document = Document(str(path))
        except Exception as exc:
            raise ExtractionError(f"Cannot open DOCX {path.name}: {exc}") from exc

        parts: list[str] = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower() if paragraph.style else ""
            if style.startswith("heading"):
                parts.append(f"\n{text}\n")
            else:
                parts.append(text)

        for table_index, table in enumerate(document.tables):
            rows: list[str] = []
            for row in table.rows:
                cells = [" ".join(cell.text.split()) for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                parts.append(f"\n[Table {table_index + 1}]\n" + "\n".join(rows))

        text = "\n\n".join(parts).strip()
        if not text:
            warnings.append("The document contains no readable paragraph text.")

        properties = document.core_properties
        title = (properties.title or "").strip() or self._first_meaningful_line(text)
        author = (properties.author or "").strip() or None

        return ExtractionResult(
            text=self._truncate(text, warnings),
            method=self.name,
            success=True,
            page_count=None,
            title=title,
            author=author,
            warnings=warnings,
            meta={"paragraphs": len(document.paragraphs), "tables": len(document.tables)},
        )
