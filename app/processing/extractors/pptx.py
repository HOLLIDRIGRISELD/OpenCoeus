"""PPTX extraction using python-pptx."""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from app.core.exceptions import ExtractionError
from app.domain.models import ExtractionResult
from app.processing.extractors.archive import enforce_archive_limits
from app.processing.extractors.base import BaseExtractor


class PptxExtractor(BaseExtractor):
    name = "pptx"
    version = "1.0"
    formats = ("pptx",)

    def extract(self, path: Path) -> ExtractionResult:
        warnings: list[str] = []
        enforce_archive_limits(path)
        try:
            presentation = Presentation(str(path))
        except Exception as exc:
            raise ExtractionError(f"Cannot open PPTX {path.name}: {exc}") from exc

        slides_text: list[str] = []
        first_title: str | None = None
        for index, slide in enumerate(presentation.slides, start=1):
            lines: list[str] = []
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    text = " ".join(run.text for run in paragraph.runs).strip()
                    if text:
                        lines.append(text)
            if lines and first_title is None:
                first_title = lines[0][:120]
            slides_text.append(f"[Slide {index}]\n" + "\n".join(lines))

        text = "\n\n".join(slides_text).strip()
        if not text:
            warnings.append("The presentation contains no readable slide text.")

        properties = presentation.core_properties
        title = (properties.title or "").strip() or first_title or self._first_meaningful_line(text)
        author = (properties.author or "").strip() or None

        return ExtractionResult(
            text=self._truncate(text, warnings),
            method=self.name,
            success=True,
            page_count=len(presentation.slides),
            title=title,
            author=author,
            warnings=warnings,
            meta={"slides": len(presentation.slides)},
        )
