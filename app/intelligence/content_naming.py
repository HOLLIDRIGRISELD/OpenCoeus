"""Deterministic, local naming decisions derived from document content."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.intelligence.entities import extract_document_type, extract_organisation
from app.intelligence.naming_engine import FilenameValidator, deduplicate_filename

_LABEL_PATTERN = re.compile(
    r"\b(?:company|customer|client|vendor|supplier|bill to|billed to|issued by|prepared for|from)"
    r"\s*:\s*([A-Z][^\n,;]{1,80})",
    re.IGNORECASE,
)
_BEFORE_TYPE_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,2})"
    r"\s+(invoice|statement|manual|report|receipt|contract|assignment|quotation|summary)\b",
    re.IGNORECASE,
)
_ACRONYM_PATTERN = re.compile(r"\b([A-Z]{2,6})\b")
_CORPORATE_SUFFIX = re.compile(
    r"[,]?\s+(?:Inc\.?|Ltd\.?|Limited|LLC|PLC|GmbH|Corporation|Company|Group)[.]?$",
    re.IGNORECASE,
)
_ENTITY_TOKENS = re.compile(r"[A-Za-z][A-Za-z0-9&]*")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_TYPE_ALIASES = {
    "assignment": "Assignment",
    "assignments": "Assignment",
    "contract": "Contract",
    "contracts": "Contract",
    "documentation": "Documentation",
    "invoice": "Invoice",
    "invoices": "Invoice",
    "lecture notes": "LectureNotes",
    "manual": "Manual",
    "manuals": "Manual",
    "presentation": "Presentation",
    "presentations": "Presentation",
    "receipt": "Receipt",
    "receipts": "Receipt",
    "report": "Report",
    "reports": "Report",
    "research paper": "ResearchPaper",
    "research papers": "ResearchPaper",
    "spreadsheet": "Spreadsheet",
    "spreadsheets": "Spreadsheet",
    "statement": "Statement",
    "statements": "Statement",
}
_SUBTYPE_HINTS = {
    "CreditNote": ("credit note",),
    "PurchaseOrder": ("purchase order",),
    "Remittance": ("remittance",),
    "Receipt": ("receipt",),
    "Statement": ("statement",),
    "Summary": ("summary",),
    "Quotation": ("quotation", "quote"),
}
_GENERIC_ENTITIES = {
    "account", "amount", "annual", "bill", "company", "customer", "date", "dear",
    "final", "flight", "inc", "invoice", "ltd", "llc", "local", "manual", "monthly",
    "new", "number", "payment", "plc", "please", "quarterly", "receipt", "report",
    "statement", "summary", "support", "technical", "terms", "total", "vendor",
}
_GENERIC_PARENTS = {
    "attachments", "desktop", "documents", "downloads", "files", "inbox", "library",
    "misc", "miscellaneous", "new folder", "scans", "temp", "tmp", "untitled",
}
_GENERIC_ACRONYMS = {
    "API", "CSV", "EUR", "GBP", "HTML", "HTTP", "ID", "INV", "JSON", "PDF", "USD",
    "VAT", "XML",
}
_VALIDATOR = FilenameValidator()


@dataclass(frozen=True, slots=True)
class ContentNamingDecision:
    """Resolved filename and optional grouped folder for one document."""

    filename: str
    relative_folder: str | None
    entity: str | None
    type_label: str | None
    applied: bool


def suggest_content_name(
    original_name: str,
    text: str,
    profile: Mapping[str, object],
    keywords: Iterable[str],
    existing_names: Iterable[str],
    reserved_names: Iterable[str],
    relative_parent: str | None = None,
    *,
    extension: str | None = None,
    detected_extension: str | None = None,
) -> str:
    """Return a short content-derived filename or the cleaned original."""

    resolved_extension = _extension_for(original_name, extension, detected_extension)
    current = _VALIDATOR.validate(Path(original_name).name, extension=resolved_extension).filename
    entity, _ = _extract_entity(profile, text, relative_parent)
    type_label, _ = _extract_type(profile, text, relative_parent, keywords)
    if not entity or not type_label:
        return _unique(current, existing_names, reserved_names, original_name)
    candidate = _safe_filename(f"{_pascal(entity)}{_pascal(type_label)}", resolved_extension)
    return _unique(candidate, existing_names, reserved_names, original_name)


def suggest_grouped_name(
    entity: str,
    type_label: str,
    subtype: str | None,
    document_date: str | None,
    extension: str,
    collision_index: int,
    title: str | None = None,
) -> str:
    """Return the readable filename to use inside an entity/type folder."""

    resolved_extension = _extension_for(f"document{extension}", extension, None)
    if title:
        stem = _pascal(title[:60])
    elif subtype:
        stem = _pascal(subtype)
    elif document_date and _ISO_DATE.fullmatch(document_date):
        stem = document_date
    else:
        stem = _pascal(type_label) or _pascal(entity) or "Document"
    if collision_index > 0:
        stem = f"{stem} {collision_index + 1}"
    return _safe_filename(stem, resolved_extension)


def grouping_relative_folder(
    entity: str,
    type_label: str,
    existing_folders: Iterable[str],
) -> str | None:
    """Return an existing entity/type folder that matches the content."""

    if not entity or not type_label:
        return None
    target = f"{_pascal(entity)}/{_plural(_pascal(type_label))}".lower()
    for folder in existing_folders:
        normalised = str(folder).replace("\\", "/").strip("/")
        if normalised and normalised.lower() == target:
            return normalised
    return None


def resolve_suggestion(
    *,
    original_name: str,
    text: str,
    profile: Mapping[str, object],
    keywords: Iterable[str],
    existing_names: Iterable[str],
    reserved_names: Iterable[str],
    relative_parent: str | None = None,
    existing_folders: Iterable[str] = (),
    extension: str | None = None,
    detected_extension: str | None = None,
) -> ContentNamingDecision:
    """Resolve a filename and grouped folder from local content evidence."""

    resolved_extension = _extension_for(original_name, extension, detected_extension)
    current = _VALIDATOR.validate(Path(original_name).name, extension=resolved_extension).filename
    entity, _ = _extract_entity(profile, text, relative_parent)
    type_label, _ = _extract_type(profile, text, relative_parent, keywords)
    if not entity or not type_label:
        return ContentNamingDecision(current, None, None, None, False)

    folder = grouping_relative_folder(entity, type_label, existing_folders)
    if folder is None:
        filename = suggest_content_name(
            original_name,
            text,
            profile,
            keywords,
            existing_names,
            reserved_names,
            relative_parent,
            extension=resolved_extension,
        )
        return ContentNamingDecision(filename, None, entity, type_label, True)

    subtype = _extract_subtype(text, type_label)
    document_date = str(profile.get("document_date") or "")
    title = str(profile.get("title") or "") if profile.get("title_supported") else ""
    filename = suggest_grouped_name(
        entity, type_label, subtype, document_date, resolved_extension, 0, title
    )
    filename = _unique(filename, existing_names, reserved_names, original_name)
    return ContentNamingDecision(filename, folder, entity, type_label, True)


def _extract_entity(
    profile: Mapping[str, object], text: str, relative_parent: str | None
) -> tuple[str | None, bool]:
    # Lower rank wins: configured or labelled evidence outranks loose regex matches,
    # which in turn outrank bare acronyms.
    candidates: list[tuple[int, str]] = []
    configured = _clean_entity(str(profile.get("organisation") or ""))
    if configured:
        candidates.append((0, configured))

    head = text[:6000]
    for match in _LABEL_PATTERN.finditer(head):
        cleaned = _clean_entity(match.group(1))
        if cleaned:
            candidates.append((1, cleaned))

    known_org = _clean_entity(extract_organisation(head) or "")
    if known_org:
        candidates.append((2, known_org))

    for match in _BEFORE_TYPE_PATTERN.finditer(head):
        cleaned = _clean_entity(match.group(1))
        if cleaned:
            candidates.append((3, cleaned))

    for acronym in _ACRONYM_PATTERN.findall(head[:1500]):
        if acronym not in _GENERIC_ACRONYMS and acronym.lower() not in _GENERIC_ENTITIES:
            candidates.append((4, acronym))

    if candidates:
        unique: list[tuple[int, str]] = []
        for rank, value in candidates:
            if (rank, value.lower()) not in {(item_rank, item.lower()) for item_rank, item in unique}:
                unique.append((rank, value))
        unique = [
            (rank, value)
            for rank, value in unique
            if not (rank > 0 and any(
                other_rank > rank
                and value.startswith(other_value)
                and value[len(other_value) : len(other_value) + 1].isupper()
                for other_rank, other_value in unique
            ))
        ]
        _, value = min(unique, key=lambda item: (item[0], len(item[1]), item[1].lower()))
        return value, True

    parent = _parent_entity(relative_parent)
    return parent, parent is not None


def _extract_type(
    profile: Mapping[str, object],
    text: str,
    relative_parent: str | None,
    keywords: Iterable[str],
) -> tuple[str | None, bool]:
    configured = _normalise_type(str(profile.get("document_type") or ""))
    if configured:
        return configured, True
    content_type = _normalise_type(extract_document_type(text, None) or "")
    if content_type:
        return content_type, True
    for keyword in keywords[:8]:
        normalised = _normalise_type(str(keyword))
        if normalised:
            return normalised, False
    if relative_parent:
        parts = [part for part in relative_parent.replace("\\", "/").split("/") if part]
        if parts:
            parent_type = _normalise_type(parts[-1])
            if parent_type:
                return parent_type, False
    return None, False


def _extract_subtype(text: str, type_label: str) -> str | None:
    head = text[:6000]
    found: list[tuple[int, str]] = []
    for label, hints in _SUBTYPE_HINTS.items():
        if label.lower() == type_label.lower():
            continue
        for hint in hints:
            escaped = re.escape(hint)
            pattern = re.compile(
                rf"^\s*(?:subtype|type)\s*:\s*{escaped}\b|^\s*{escaped}\s*$",
                re.IGNORECASE | re.MULTILINE,
            )
            match = pattern.search(head)
            if match:
                found.append((match.start(), label))
    if not found:
        return None
    return min(found, key=lambda item: (item[0], item[1]))[1]


def _parent_entity(relative_parent: str | None) -> str | None:
    if not relative_parent:
        return None
    for part in relative_parent.replace("\\", "/").split("/"):
        cleaned = _clean_entity(part)
        if not cleaned or cleaned.lower() in _GENERIC_PARENTS:
            continue
        if cleaned.lower() in _TYPE_ALIASES:
            continue
        return cleaned
    return None


def _clean_entity(value: str) -> str | None:
    trimmed = _CORPORATE_SUFFIX.sub("", value.strip())
    tokens = [
        token for token in _ENTITY_TOKENS.findall(trimmed)
        if token.lower() not in _GENERIC_ENTITIES and not re.search(r"\d{4,}", token)
    ]
    if not tokens:
        return None
    return "".join(token if token.isupper() else token[:1].upper() + token[1:] for token in tokens)


def _normalise_type(value: str) -> str | None:
    key = " ".join(value.strip().lower().replace("_", " ").split())
    if not key:
        return None
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    if key in _GENERIC_ENTITIES:
        return None
    if key.endswith("ies"):
        key = f"{key[:-3]}y"
    elif key.endswith("s") and not key.endswith("ss"):
        key = key[:-1]
    if key in _TYPE_ALIASES:
        return _TYPE_ALIASES[key]
    words = [word for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", key) if word]
    if not words or len(words) > 3 or any(word in _GENERIC_ENTITIES for word in words):
        return None
    return "".join(word[:1].upper() + word[1:] for word in words)


def _pascal(value: str) -> str:
    words = [word for word in re.findall(r"[A-Za-z0-9]+", value) if word]
    return "".join(word if word.isupper() else word[:1].upper() + word[1:] for word in words)


def _plural(value: str) -> str:
    if not value or value.endswith("s"):
        return value
    if value.endswith("y") and len(value) > 1 and value[-2].islower():
        return f"{value[:-1]}ies"
    return f"{value}s"


def _extension_for(
    original_name: str, extension: str | None, detected_extension: str | None
) -> str:
    if extension:
        return extension if extension.startswith(".") else f".{extension}"
    suffix = Path(original_name).suffix
    letters = suffix.lstrip(".")
    if letters.isalnum() and 1 <= len(letters) <= 5:
        return suffix
    if detected_extension:
        letters = detected_extension.lstrip(".")
        detected = f".{letters}"
        return detected.upper() if letters.isalpha() else detected
    return suffix


def _safe_filename(stem: str, extension: str) -> str:
    candidate = f"{stem}{extension}"
    probe = candidate.replace("-", "_").replace(" ", "_")
    result = _VALIDATOR.validate(probe)
    if not result.valid:
        return result.filename
    return candidate


def _unique(
    filename: str, existing_names: Iterable[str], reserved_names: Iterable[str], original_name: str
) -> str:
    taken = [
        name for name in (*existing_names, *reserved_names) if name.lower() != original_name.lower()
    ]
    return deduplicate_filename(filename, taken)[0]
