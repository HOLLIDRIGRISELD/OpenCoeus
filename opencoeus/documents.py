from __future__ import annotations

import re
from pathlib import Path


def extract_text(document_path: Path, maximum_pages: int = 2) -> str:
    try:
        if document_path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            pdf_reader = PdfReader(str(document_path))
            return "\n".join((pdf_page.extract_text() or "") for pdf_page in pdf_reader.pages[:maximum_pages])
        if document_path.suffix.lower() == ".docx":
            from docx import Document
            word_document = Document(str(document_path))
            return "\n".join(paragraph.text for paragraph in word_document.paragraphs[:80])
    except Exception:
        return ""
    return ""


def suggest_title(document_text: str, fallback_title: str) -> str:
    # SELECTS A SHORT, READABLE LINE FROM DOCUMENT TEXT AS A TITLE SUGGESTION.
    text_lines = [re.sub(r"\s+", " ", line).strip() for line in document_text.splitlines()]
    candidate_titles = [line for line in text_lines if 8 <= len(line) <= 100 and any(character.isalpha() for character in line)]
    selected_title = candidate_titles[0] if candidate_titles else fallback_title
    safe_filename_title = re.sub(r'[<>:"/\\|?*]', "-", selected_title).strip(" .-")
    return safe_filename_title[:120] or "Untitled document"
