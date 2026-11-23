"""Detect and apply existing filename conventions without changing analysis."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_SEPARATORS = ("-", "_", " ")
_NUMBER = re.compile(r"^(\d+)$")


@dataclass(frozen=True, slots=True)
class Convention:
    """A repeated naming pattern observed in a library."""

    case_style: str
    separator: str
    prefix: str
    date_style: str
    numeric_suffix: int
    next_sequence: int


def _case_style(tokens: list[str]) -> str:
    words = [token for token in tokens if token.isalpha()]
    if not words:
        return "mixed"
    if all(word.isupper() for word in words):
        return "upper"
    if all(word.islower() for word in words):
        return "lower"
    if all(word[:1].isupper() and word[1:].islower() for word in words):
        return "title"
    return "mixed"


def _date_style(tokens: list[str]) -> str:
    return "year" if tokens and re.fullmatch(r"\d{4}", tokens[0]) else "none"


def detect_convention(names: Sequence[str]) -> Convention | None:
    """Return the strongest repeated `prefix + separator + number` pattern."""

    groups: dict[tuple[str, str, int], list[tuple[int, str]]] = defaultdict(list)
    for raw in names:
        stem = Path(str(raw)).stem
        for separator in _SEPARATORS:
            parts = stem.split(separator)
            if len(parts) < 2:
                continue
            match = _NUMBER.match(parts[-1])
            if match is None:
                continue
            prefix = f"{separator.join(parts[:-1])}{separator}"
            if not prefix.strip(separator):
                continue
            groups[(separator, prefix, len(match.group(1)))].append(
                (int(match.group(1)), stem)
            )

    if not groups:
        return None
    key, entries = max(groups.items(), key=lambda item: (len(item[1]), len(item[0][1])))
    if len(entries) < 2:
        return None
    separator, prefix, width = key
    tokens = prefix.rstrip(separator).split(separator)
    return Convention(
        case_style=_case_style(tokens),
        separator=separator,
        prefix=prefix,
        date_style=_date_style(tokens),
        numeric_suffix=width,
        next_sequence=max(number for number, _ in entries) + 1,
    )


def _apply_case(title: str, convention: Convention) -> str:
    if convention.case_style == "upper":
        return title.upper()
    if convention.case_style == "lower":
        return title.lower()
    if convention.case_style == "title":
        return convention.separator.join(word.capitalize() for word in title.split(convention.separator))
    return title


def apply_convention(name: str, convention: Convention) -> str:
    """Rewrite a suggested filename into the detected convention."""

    path = Path(name)
    stem = path.stem
    tokens = convention.prefix.rstrip(convention.separator).split(convention.separator)
    if convention.date_style == "year" and tokens and tokens[0].isdigit():
        tokens = tokens[1:]
    base = convention.separator.join(tokens) or "Document"

    remainder = stem[len(convention.prefix) :] if stem.lower().startswith(convention.prefix.lower()) else stem
    parts = remainder.split(convention.separator)
    if parts and _NUMBER.match(parts[-1]):
        parts = parts[:-1]
    title = _apply_case(convention.separator.join(part for part in parts if part), convention)
    if not title or title.lower() == base.lower():
        rewritten = f"{convention.prefix}{convention.next_sequence:0{convention.numeric_suffix}d}"
    else:
        rewritten = (
            f"{convention.prefix}{title}{convention.separator}"
            f"{convention.next_sequence:0{convention.numeric_suffix}d}"
        )
    return f"{rewritten}{path.suffix}"
