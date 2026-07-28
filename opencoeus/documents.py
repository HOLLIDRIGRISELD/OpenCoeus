from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# DOCUMENT TYPE DETECTION: PATTERNS CHECKED IN PRIORITY ORDER (FIRST MATCH WINS)
# EACH ENTRY: (type_name, compiled_regex)
# MORE SPECIFIC TYPES CHECKED FIRST, FALLBACK TO GENERIC
_DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Invoice", re.compile(r"(invoice|inv[-#\s]?\d|amount\s+d(ue|ate)|billing|payment\s+terms)", re.IGNORECASE)),
    ("Meeting-Notes", re.compile(r"(meeting\s*(notes|minutes|log)|attendees?:|agenda|action\s+items)", re.IGNORECASE)),
    ("Specification", re.compile(r"(specification|spec[:.\s]|technical\s*(spec|requirement)|architecture\s*(overview|diagram))", re.IGNORECASE)),
    ("Report", re.compile(r"(report|summary|analysis|findings|conclusion)", re.IGNORECASE)),
    ("Budget", re.compile(r"(budget|financial|revenue|expenses?|forecast|quarterly)", re.IGNORECASE)),
    ("Contract", re.compile(r"(contract|agreement|terms?\s*(and|of)\s*(service|conditions|use)|legal)", re.IGNORECASE)),
    ("Presentation", re.compile(r"(presentation|slides?|deck)", re.IGNORECASE)),
    ("Readme", re.compile(r"(readme|getting\s+started|installation)", re.IGNORECASE)),
    ("Backup", re.compile(r"(backup|archive|restore|snapshot)", re.IGNORECASE)),
    ("Spreadsheet", re.compile(r"(spreadsheet|worksheet|tab|csv|tabular)", re.IGNORECASE)),
]

# LINES MATCHING THESE PATTERNS ARE LIKELY HEADERS, FOOTERS, OR PAGE NUMBERS
_NOISE_PATTERNS = re.compile(
    r"^(page\s+\d+|第.+页|header|footer|confidential|draft|do not distribute)$",
    re.IGNORECASE,
)

# LINES CONTAINING THESE PHRASES ARE LIKELY TITLE CANDIDATES
_TITLE_INDICATORS = re.compile(
    r"(title|subject|report|invoice|specification|summary|meeting|notes|agenda|minutes)",
    re.IGNORECASE,
)

# LINES STARTING WITH THESE ARE LIKELY HEADERS
_HEADER_PREFIXES = re.compile(
    r"^(#+\s+|[-=]+\s*$|abstract|introduction|overview|background)",
    re.IGNORECASE,
)


def detect_document_type(text: str, metadata: dict | None = None, title_candidate: str = "") -> str:
    """Analyze text and metadata to determine document type.
    Returns a type name like "Invoice", "Meeting-Notes", "Specification", or fallback "Document".
    Checks title candidate first (highest weight), then text body."""
    combined = text
    if title_candidate:
        combined = title_candidate + "\n" + text
    if metadata:
        meta_text = " ".join(str(v) for v in metadata.values() if v)
        combined = combined + "\n" + meta_text
    for doc_type_name, doc_type_pattern in _DOC_TYPE_PATTERNS:
        if doc_type_pattern.search(combined):
            return doc_type_name
    return "Document"


def _extract_pdf_text_annotations(pdf_page) -> str:
    """Fallback: extract text from PDF annotations and form fields."""
    texts: list[str] = []
    try:
        for annot in pdf_page.get("/Annots", []):
            annot_obj = annot.get_object() if hasattr(annot, "get_object") else annot
            if isinstance(annot_obj, dict):
                for key in ("/V", "/Contents", "/T"):
                    value = annot_obj.get(key)
                    if isinstance(value, str) and value.strip():
                        texts.append(value.strip())
    except Exception:
        pass
    return "\n".join(texts)


def extract_text(document_path: Path, maximum_pages: int = 2) -> str:
    logger.debug("Extracting text from %s", document_path)
    try:
        if document_path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            pdf_reader = PdfReader(str(document_path))
            text_parts: list[str] = []
            for pdf_page in pdf_reader.pages[:maximum_pages]:
                # TRY LAYOUT MODE FIRST FOR BETTER STRUCTURED TEXT
                page_text = pdf_page.extract_text(extraction_mode="layout") or ""
                # FALLBACK TO PLAIN MODE IF LAYOUT RETURNS NOTHING
                if not page_text.strip():
                    page_text = pdf_page.extract_text() or ""
                # FALLBACK TO ANNOTATION TEXT
                if not page_text.strip():
                    page_text = _extract_pdf_text_annotations(pdf_page)
                text_parts.append(page_text)
            return "\n".join(text_parts)
        if document_path.suffix.lower() == ".docx":
            from docx import Document
            word_document = Document(str(document_path))
            return "\n".join(paragraph.text for paragraph in word_document.paragraphs[:80])
        if document_path.suffix.lower() in {".txt", ".md"}:
            # READ FIRST 15 LINES FOR TITLE EXTRACTION
            lines: list[str] = []
            with open(document_path, "r", encoding="utf-8", errors="replace") as text_file:
                for line_number, line in enumerate(text_file):
                    if line_number >= 15:
                        break
                    lines.append(line)
            return "\n".join(lines)
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", document_path, exc)
        return ""
    return ""


def extract_metadata(document_path: Path) -> dict:
    """Extract metadata from documents: PDF author, creation date, keywords."""
    metadata: dict = {}
    try:
        if document_path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            pdf_reader = PdfReader(str(document_path))
            info = pdf_reader.metadata
            if info:
                metadata["author"] = info.author or ""
                metadata["title"] = info.title or ""
                metadata["subject"] = info.subject or ""
                metadata["creator"] = info.creator or ""
                if info.creation_date:
                    metadata["created_date"] = info.creation_date.strftime("%Y-%m-%d")
                    metadata["created_month"] = info.creation_date.strftime("%m")
    except Exception as exc:
        logger.debug("Metadata extraction failed for %s: %s", document_path, exc)
    return metadata


def _score_title_candidate(line: str) -> float:
    """Score a line as a title candidate; higher is better."""
    score = 0.0
    words = line.split()
    word_count = len(words)
    # PREFER 2 TO 8 WORDS
    if 2 <= word_count <= 8:
        score += 2.0
    elif 1 <= word_count <= 12:
        score += 1.0
    # PREFER MIXED CASE OVER ALL CAPS OR ALL LOWERCASE
    if any(c.isupper() for c in line) and any(c.islower() for c in line):
        score += 1.5
    elif line.isupper():
        score -= 0.5
    # PENALIZE LINES THAT LOOK LIKE NOISE
    if _NOISE_PATTERNS.match(line.strip()):
        score -= 3.0
    # PREFER LINES WITH LETTERS OVER PURE NUMBERS
    alpha_ratio = sum(c.isalpha() for c in line) / max(len(line), 1)
    if alpha_ratio > 0.5:
        score += 0.5
    # BOOST LINES CONTAINING TITLE INDICATORS LIKE INVOICE REPORT OR SUMMARY
    if _TITLE_INDICATORS.search(line):
        score += 2.0
    # PENALIZE LINES THAT LOOK LIKE MARKDOWN HEADERS OR SECTION TITLES
    if _HEADER_PREFIXES.match(line.strip()):
        score -= 1.0
    # PREFER SHORTER LINES WITHIN THE IDEAL RANGE
    if 20 <= len(line.strip()) <= 80:
        score += 0.5
    return score


def suggest_title(document_text: str, fallback_title: str) -> str:
    """Select a short, readable line from document text as a title suggestion."""
    text_lines = [re.sub(r"\s+", " ", line).strip() for line in document_text.splitlines()]
    candidate_titles = [
        line for line in text_lines
        if 5 <= len(line) <= 120 and any(character.isalpha() for character in line)
    ]
    if not candidate_titles:
        safe_filename_title = re.sub(r'[<>:"/\\|?*]', "-", fallback_title).strip(" .-")
        return safe_filename_title[:120] or "Untitled document"
    # SCORE AND SELECT THE BEST CANDIDATE
    scored_candidates = [(_score_title_candidate(line), line) for line in candidate_titles]
    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    selected_title = scored_candidates[0][1]
    safe_filename_title = re.sub(r'[<>:"/\\|?*]', "-", selected_title).strip(" .-")
    return safe_filename_title[:120] or "Untitled document"
