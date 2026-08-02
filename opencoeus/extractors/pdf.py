from __future__ import annotations

import logging
from pathlib import Path

from .signals import FileSignals

logger = logging.getLogger(__name__)

_MAX_PDF_PAGES = 50
_MAX_PDF_CHARS = 100_000


def _extract_pdf(file_path: Path, result: FileSignals, maximum_pages: int = _MAX_PDF_PAGES,
                 max_chars: int = _MAX_PDF_CHARS) -> None:
    from pypdf import PdfReader
    reader = PdfReader(str(file_path))
    pages = reader.pages[:maximum_pages] if maximum_pages < 999 else reader.pages
    text_parts = []
    text_len = 0
    for page in pages:
        try:
            page_text = page.extract_text(extraction_mode="layout") or ""
            if not page_text.strip():
                page_text = page.extract_text() or ""
            if not page_text.strip():
                page_text = _extract_pdf_annotations(page)
        except Exception:
            page_text = ""
        if page_text:
            text_parts.append(page_text)
            text_len += len(page_text)
            if text_len >= max_chars:
                break
    result.text = "\n".join(text_parts)
    if reader.metadata:
        info = reader.metadata
        if info.title:
            result.metadata["title"] = info.title
        if info.author:
            result.metadata["author"] = info.author
        if info.subject:
            result.metadata["subject"] = info.subject
        if info.creator:
            result.metadata["creator"] = info.creator
        if info.creation_date:
            result.metadata["created_date"] = info.creation_date.strftime("%Y-%m-%d")
    if result.text.strip():
        result.signals_present.append("text")
        result.confidence_hint = max(result.confidence_hint, 0.7)
    if result.metadata:
        result.signals_present.append("metadata")


def _extract_pdf_annotations(page) -> str:
    texts = []
    try:
        for annot in page.get("/Annots", []):
            obj = annot.get_object() if hasattr(annot, "get_object") else annot
            if isinstance(obj, dict):
                for key in ("/V", "/Contents", "/T"):
                    val = obj.get(key)
                    if isinstance(val, str) and val.strip():
                        texts.append(val.strip())
    except Exception:
        pass
    return "\n".join(texts)
