"""Deterministic entity extraction.

These helpers only return information that is supported by the supplied text or
metadata. When a value cannot be established the field stays ``None``; OpenCoeus
must never invent a date or organisation just to make a filename look complete.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)

_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](20\d{2})\b"),
    re.compile(
        rf"\b({_MONTHS})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b", re.IGNORECASE
    ),
    re.compile(rf"\b({_MONTHS})\s+(20\d{{2}})\b", re.IGNORECASE),
    re.compile(r"\b(20\d{2})\b"),
)

_ORG_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&.'\- ]{2,60}?"
    r"(?:University|College|Institute|School|Bank|Limited|Ltd\.?|Inc\.?|PLC|GmbH|Corporation|Company|Group))\b"
)

_DOC_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "Assignment": ("assignment", "coursework", "submission", "deadline"),
    "Lecture Notes": ("lecture", "seminar", "notes", "revision"),
    "Research Paper": ("abstract", "literature review", "methodology", "references", "doi"),
    "Presentation": ("slide", "presentation", "agenda"),
    "Invoice": ("invoice", "bill to", "vat", "subtotal", "amount due"),
    "Receipt": ("receipt", "paid", "transaction", "cashier"),
    "Statement": ("statement", "account number", "opening balance", "closing balance"),
    "Contract": ("contract", "agreement", "terms and conditions", "party", "employment"),
    "Report": ("report", "executive summary", "findings", "recommendations"),
    "Manual": ("manual", "installation", "configuration", "troubleshooting"),
    "Spreadsheet": ("worksheet", "sheet", "budget", "forecast"),
}

_GENERIC_FILENAME_WORDS = {
    "scan", "img", "image", "photo", "document", "doc", "file", "new", "final", "copy",
    "draft", "version", "v", "untitled", "download", "attachment", "screenshot", "tmp",
}

_TITLE_MARKUP_START = re.compile(
    r"^(?:<|\[|\{|//|/\*|const\b|let\b|var\b|import\b|from\b|def\b|class\b|"
    r"function\b|return\b|await\b|SELECT\b|CREATE\b|ALTER\b|DROP\b|INSERT\b|UPDATE\b|DELETE\b)",
    re.IGNORECASE,
)
_TITLE_PROPERTY = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{0,34}\s*:")
_ICS_SUMMARY = re.compile(r"^SUMMARY\s*:\s*(.+)$", re.IGNORECASE)
_EMAIL_SUBJECT = re.compile(r"^[ \t]*subject[ \t]*:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
_EMAIL_FROM = re.compile(r"^[ \t]*from[ \t]*:", re.IGNORECASE | re.MULTILINE)
_GREETING = re.compile(
    r"^(?:dear|hi|hello|good morning|good afternoon|to whom it may concern)\b",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"^(?:this file is part of|this source code form is subject to|copyright\b|"
    r"all rights reserved\b|permission is hereby granted|licensed under\b|"
    r"distributed under the terms|license,\s*v\.|if a copy of the mpl|"
    r"file, you can obtain one at|mozilla public license|"
    r"gnu (?:lesser )?general public license|apache license)",
    re.IGNORECASE,
)
_TITLE_SEPARATOR = re.compile(r"\s+[-–—|·]\s+")
_GENERIC_TITLES = {
    "page not found",
    "404 not found",
    "home",
    "home page",
    "contents",
    "table of contents",
    "abstract",
    "introduction",
    "powerpoint presentation",
    "presentation",
    "slide deck",
    "page 1",
    "untitled",
}
_GENERIC_TITLE_PATTERN = re.compile(
    r"^(?:jpg|jpeg|png|gif|svg|webp|pdf|xml|csv|html|htm|docx?|xlsx?|pptx?|txt|"
    r"zip|gzip(?:\s*\(gz\))?)\s+data\s+sets?$",
    re.IGNORECASE,
)
_GENERIC_TITLE_WORDS = {
    "agreement", "commoncrawl", "content", "contents", "creation", "data", "dataset",
    "datasets", "description", "edinburgh", "information", "license", "licence",
    "napier", "provenance", "raise", "related", "set", "sets", "university",
}
TITLE_SCAN_LINES = 8


def extract_date(text: str) -> str | None:
    """Find the most plausible date, preferring ISO and day/month/year forms."""

    for pattern in _DATE_PATTERNS[:3]:
        match = pattern.search(text)
        if not match:
            continue
        try:
            if pattern is _DATE_PATTERNS[0]:
                year, month, day = (int(part) for part in match.groups())
                return date(year, month, day).isoformat()
            if pattern is _DATE_PATTERNS[1]:
                first, second, year = (int(part) for part in match.groups())
                for month, day in ((second, first), (first, second)):
                    try:
                        return date(year, month, day).isoformat()
                    except ValueError:
                        continue
                continue
            if pattern is _DATE_PATTERNS[2]:
                month_name, day, year = match.group(1), int(match.group(2)), int(match.group(3))
                month = _MONTHS.lower().split("|").index(month_name.lower()) + 1
                return date(year, month, day).isoformat()
        except (ValueError, AttributeError):
            continue
    match = _DATE_PATTERNS[3].search(text)
    if match:
        month_name, year = match.group(1), int(match.group(2))
        month = _MONTHS.lower().split("|").index(month_name.lower()) + 1
        return f"{year:04d}-{month:02d}"
    match = _DATE_PATTERNS[4].search(text)
    return match.group(1) if match else None


def extract_organisation(text: str) -> str | None:
    match = _ORG_PATTERN.search(text)
    if not match:
        return None
    candidate = " ".join(match.group(1).split())
    return candidate if 3 <= len(candidate) <= 80 else None


def extract_document_type(text: str, category_path: str | None = None) -> str | None:
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for document_type, hints in _DOC_TYPE_HINTS.items():
        score = sum(1 for hint in hints if hint in lowered)
        if score and (best is None or score > best[0]):
            best = (score, document_type)
    if best:
        return best[1]
    if category_path:
        leaf = category_path.split("/")[-1]
        mapping = {
            "Assignments": "Assignment",
            "Lecture Notes": "Lecture Notes",
            "Research": "Research Paper",
            "Presentations": "Presentation",
            "Invoices": "Invoice",
            "Receipts": "Receipt",
            "Statements": "Statement",
            "Contracts": "Contract",
            "Reports": "Report",
            "Documentation": "Documentation",
        }
        if leaf in mapping:
            return mapping[leaf]
    return None


def normalise_title_candidate(raw: str) -> str:
    """Remove presentation markers while keeping the title's words intact."""

    candidate = " ".join(raw.split())
    candidate = re.sub(r"^[\s>*\-–—#`~_]+", "", candidate)
    candidate = candidate.strip(" -–—|#*_`~\"'")
    return candidate.rstrip(":")


def is_usable_title(candidate: str, *, max_length: int = 100) -> bool:
    """Return whether a candidate reads like a document title.

    The rule rejects syntax, markup, property lines, tabular rows, sentence
    prose, licence boilerplate, greetings and generic labels that repeat across
    unrelated files. It deliberately keeps the rule deterministic: no model call
    and no library-wide query are involved.
    """

    if not 3 <= len(candidate) <= max_length or not candidate[0].isupper():
        return False
    if candidate.endswith((".", "!", "?")):
        return False
    lowered = candidate.lower()
    if lowered in _GENERIC_TITLES or _GENERIC_TITLE_PATTERN.match(lowered):
        return False
    if any(segment.strip() in _GENERIC_TITLES for segment in _TITLE_SEPARATOR.split(lowered)):
        return False
    if _GREETING.match(candidate) or _BOILERPLATE.match(candidate):
        return False
    if _TITLE_MARKUP_START.match(candidate) or _TITLE_PROPERTY.match(candidate):
        return False
    if any(token in candidate for token in ("=", ";", "{", "}", "<", ">", "\\", "|")):
        return False
    if candidate.count(",") >= 2 or candidate.count(":") >= 2:
        return False
    words = [word.lower() for word in re.findall(r"\b[^\W\d_]+\b", candidate, re.UNICODE)]
    if len(words) < 2 or not set(words) - _GENERIC_TITLE_WORDS:
        return False
    return sum(character.isalpha() for character in candidate) >= 6


def clean_title_from_filename(filename: str) -> str:
    """Turn a poor filename into a readable fallback title.

    This is only used when the document itself provides no usable title.
    Short numeric prefixes are preserved because they often distinguish
    otherwise identical files; long ID-like prefixes are stripped.
    """

    stem = Path(filename).stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"^\d{5,}", "", stem)
    stem = re.sub(r"\b(?:19|20)\d{2}[-_ ]?\d{0,2}[-_ ]?\d{0,2}\b", " ", stem)
    words = []
    for word in stem.split():
        cleaned = word.strip(".,;:()[]{}")
        if cleaned.lower() in _GENERIC_FILENAME_WORDS:
            continue
        if cleaned:
            words.append(cleaned)
    result = " ".join(words).strip()
    return result[:120] if result else Path(filename).stem[:120]


def extract_title(text: str, filename: str, metadata_title: str | None = None) -> tuple[str, bool]:
    """Return ``(title, supported_by_document)``.

    ``supported_by_document`` is False when the title is only a cleaned filename,
    which must lower confidence in any recommendation derived from it.
    """

    if metadata_title:
        cleaned = normalise_title_candidate(metadata_title)
        if is_usable_title(cleaned, max_length=140):
            return cleaned, True
    lines = text.splitlines()
    if _EMAIL_FROM.search(text):
        subject = _EMAIL_SUBJECT.search(text)
        if subject:
            candidate = normalise_title_candidate(subject.group(1))
            if is_usable_title(candidate):
                return candidate, True
    for line in lines:
        summary = _ICS_SUMMARY.match(line.strip())
        if summary:
            candidate = normalise_title_candidate(summary.group(1)).rstrip(".")
            if is_usable_title(candidate):
                return candidate, True
    for line in [line for line in lines if line.strip()][:TITLE_SCAN_LINES]:
        candidate = normalise_title_candidate(line)
        if is_usable_title(candidate):
            return candidate, True
    return clean_title_from_filename(filename), False
