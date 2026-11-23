"""Filename generation, validation and collision avoidance."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.constants import FILENAME_SEPARATOR, MAX_FILENAME_LENGTH
from app.domain.models import ClassificationResult, DocumentProfile, NamingSuggestion
from app.intelligence.entities import clean_title_from_filename

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SYNTAX_CHARS = re.compile(r"[^\w.\-\s]", flags=re.UNICODE)
_SEPARATOR_RUN = re.compile(r"[_\-\s]+")
_TEMPLATE_TOKEN = re.compile(r"\{(\w+)\}")

_RESERVED_WINDOWS_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _is_opaque_stem(stem: str) -> bool:
    return len(stem) >= 12 and stem.isalnum() and any(character.isdigit() for character in stem)


def _clean_phrase(value: str) -> str:
    text = _INVALID_CHARS.sub(" ", value)
    text = text.replace("%", " percent ")
    text = _SYNTAX_CHARS.sub(" ", text)
    text = _SEPARATOR_RUN.sub(FILENAME_SEPARATOR, text)
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text, flags=re.UNICODE)
    return text.strip(f" {FILENAME_SEPARATOR}.-")


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    filename: str
    warnings: list[str] = field(default_factory=list)


class FilenameValidator:
    """Sanitises and validates candidate filenames.

    The validator is platform-aware in the conservative direction: it rejects
    every character that is invalid on Windows, so a suggestion created on Linux
    remains portable.
    """

    def __init__(self, *, max_length: int = MAX_FILENAME_LENGTH) -> None:
        self.max_length = max_length

    def validate(self, filename: str, *, extension: str | None = None) -> ValidationResult:
        warnings: list[str] = []
        name = filename.strip()
        if not name:
            return ValidationResult(False, "", ["The generated filename is empty."])
        if extension and not name.lower().endswith(extension.lower()):
            name = f"{name}{extension}"

        stem, suffix = Path(name).stem, Path(name).suffix
        cleaned_stem = self._clean_segment(stem)
        if cleaned_stem != stem:
            warnings.append("Invalid or redundant characters were removed from the filename.")
        if not cleaned_stem:
            cleaned_stem = "Document"
            warnings.append("No usable title was available; a generic name was used.")
        if cleaned_stem.lower() in _RESERVED_WINDOWS_NAMES:
            cleaned_stem = f"{cleaned_stem}{FILENAME_SEPARATOR}document"
            warnings.append("The name is reserved by Windows and was adjusted.")

        available = self.max_length - len(suffix)
        if len(cleaned_stem) > available:
            cleaned_stem = cleaned_stem[:available].rstrip("._- ")
            warnings.append(f"The filename was shortened to {self.max_length} characters.")

        final = f"{cleaned_stem}{suffix or (extension or '')}"
        valid = bool(cleaned_stem) and not _INVALID_CHARS.search(final)
        return ValidationResult(valid, final, warnings)

    def deduplicate(self, filename: str, existing: set[str]) -> tuple[str, str | None]:
        """Return a non-colliding filename and an optional warning."""

        return deduplicate_filename(filename, existing)

    def _clean_segment(self, segment: str) -> str:
        return _clean_phrase(segment)


def deduplicate_filename(filename: str, existing: Iterable[str]) -> tuple[str, str | None]:
    """Return a non-colliding filename using the shared ``_N`` suffix convention."""

    taken = {name.lower() for name in existing}
    if filename.lower() not in taken:
        return filename, None
    stem, suffix = Path(filename).stem, Path(filename).suffix
    for index in range(2, 1000):
        candidate = f"{stem}{FILENAME_SEPARATOR}{index}{suffix}"
        if candidate.lower() not in taken:
            return candidate, f"'{filename}' already exists; using '{candidate}' instead."
    return filename, "Could not find a free filename after 999 attempts."


class NamingEngine:
    """Builds filename recommendations from verified fields and a template.

    Supported template tokens: ``{title}``, ``{category}``, ``{subject}``,
    ``{document_type}``, ``{organisation}``, ``{date}``, ``{year}``,
    ``{original}`` and ``{project}``. Unknown or unavailable tokens are removed
    cleanly rather than producing strings such as ``None``.
    """

    def __init__(self, validator: FilenameValidator | None = None) -> None:
        self.validator = validator or FilenameValidator()

    def suggest(
        self,
        *,
        profile: DocumentProfile,
        classification: ClassificationResult,
        original_name: str,
        extension: str,
        template: str = "{title}",
        existing_names: set[str] | None = None,
    ) -> NamingSuggestion:
        original_path = Path(original_name)
        extension = extension or original_path.suffix
        fallback_title = clean_title_from_filename(original_name)
        if profile.title_supported and profile.title:
            title = _clean_phrase(profile.title)
        elif _is_opaque_stem(original_path.stem):
            title = _clean_phrase(
                profile.document_type
                or classification.secondary_category
                or classification.primary_category
                or fallback_title
            )
        else:
            title = _clean_phrase(fallback_title)
        fields = {
            "title": title,
            "category": _clean_phrase(classification.primary_category),
            "subject": _clean_phrase(
                classification.secondary_category or classification.primary_category
            ),
            "document_type": _clean_phrase(profile.document_type or ""),
            "organisation": _clean_phrase(profile.organisation or ""),
            "date": (profile.document_date or "").replace("-", FILENAME_SEPARATOR),
            "year": (profile.document_date or "")[:4],
            "original": _clean_phrase(original_path.stem),
            "project": "",
        }

        rendered = self._render(template, fields) or self._render("{title}", fields)
        validation = self.validator.validate(rendered, extension=extension)
        warnings = list(validation.warnings)
        if not profile.title_supported:
            warnings.append("The title was derived from the original filename, not the document text.")

        existing = set(existing_names or ())
        existing.discard(original_name)
        final_name, conflict_warning = self.validator.deduplicate(validation.filename, existing)
        if conflict_warning:
            warnings.append(conflict_warning)

        confidence = min(0.98, classification.confidence * 0.65 + (0.35 if profile.title_supported else 0.10))
        explanation = self._explain(template, fields, profile, classification)
        evidence = [
            f"Title: {profile.title}" if profile.title else f"Fallback title: {title}",
            f"Category: {classification.category_path}",
        ]
        if profile.document_date:
            evidence.append(f"Date found in document: {profile.document_date}")
        if profile.organisation:
            evidence.append(f"Organisation found in document: {profile.organisation}")
        evidence.extend(profile.extracted_evidence[:4])

        return NamingSuggestion(
            original_name=original_name,
            suggested_name=final_name,
            confidence=round(confidence, 3),
            explanation=explanation,
            template=template,
            evidence=evidence,
            warnings=warnings,
            changed=final_name.lower() != original_name.lower(),
        )

    @staticmethod
    def _render(template: str, fields: dict[str, str]) -> str:
        def replace(match: re.Match[str]) -> str:
            value = fields.get(match.group(1), "")
            return f" {FILENAME_SEPARATOR} {value} " if value else " "

        rendered = _TEMPLATE_TOKEN.sub(replace, template)
        rendered = _SEPARATOR_RUN.sub(FILENAME_SEPARATOR, rendered)
        return rendered.strip(f" {FILENAME_SEPARATOR}.-")

    @staticmethod
    def _explain(
        template: str,
        fields: dict[str, str],
        profile: DocumentProfile,
        classification: ClassificationResult,
    ) -> str:
        used = [name for name in _TEMPLATE_TOKEN.findall(template) if fields.get(name)]
        source = (
            "the document's own title"
            if profile.title_supported
            else "the original filename because the document provided no usable title"
        )
        parts = [f"Built from {source}"]
        if used:
            parts.append("using the fields: " + ", ".join(used))
        parts.append(f"classified as {classification.category_path} ({classification.confidence:.0%} confidence)")
        return "; ".join(parts) + "."
