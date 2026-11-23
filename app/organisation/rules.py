"""Deterministic rule matching and template rendering for organisation plans."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.infrastructure.models import OrganisationRule

TEMPLATE_TOKENS = frozenset(
    {"title", "category", "original", "date", "year", "extension"}
)
ALLOWED_ACTIONS = frozenset({"MOVE", "RENAME", "RENAME_AND_MOVE"})
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class RuleDecision:
    """A rule's proposed folder, filename and action."""

    relative_folder: str
    new_name: str
    action: str


def validate_template(template: str) -> list[str]:
    """Return template token names that OpenCoeus cannot render."""

    return [name for name in _TOKEN.findall(template) if name not in TEMPLATE_TOKENS]


def _template_values(record: Mapping[str, object]) -> dict[str, str]:
    path = Path(str(record.get("path") or record.get("name") or ""))
    modified = record.get("modified_at")
    date = str(modified)[:10] if modified is not None else ""
    return {
        "title": str(record.get("title") or path.stem),
        "category": str(record.get("category") or "").replace("/", " - "),
        "original": path.stem,
        "date": date,
        "year": date[:4],
        "extension": str(record.get("extension") or path.suffix.lstrip(".")),
    }


def _render(template: str, record: Mapping[str, object]) -> str:
    rendered = template
    for name, value in _template_values(record).items():
        rendered = rendered.replace(f"{{{name}}}", value)
    return rendered.strip()


def _field_value(record: Mapping[str, object], field: str) -> str:
    if field == "folder":
        path = Path(str(record.get("path") or ""))
        return path.parent.name
    if field == "always":
        return ""
    return str(record.get(field) or "")


def _compare(actual: str, expected: str, op: str) -> bool:
    lowered = actual.lower()
    wanted = expected.lower()
    if op in {"equals", "=="}:
        return lowered == wanted
    if op in {"not_equals", "!="}:
        return lowered != wanted
    if op == "contains":
        return wanted in lowered
    if op == "startswith":
        return lowered.startswith(wanted)
    if op == "endswith":
        return lowered.endswith(wanted)
    if op == "fnmatch":
        return fnmatch.fnmatchcase(lowered, wanted)
    if op in {"gt", "gte", "lt", "lte"}:
        try:
            left = float(actual)
            right = float(expected)
        except ValueError:
            return False
        return {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[op]
    return False


def _action(rule: OrganisationRule, name: str, folder: str) -> str:
    if rule.action in ALLOWED_ACTIONS:
        return rule.action
    if name and folder:
        return "RENAME_AND_MOVE"
    return "RENAME" if name else "MOVE"


class RuleEvaluator:
    """Return the first matching enabled rule's proposal, ordered by priority."""

    def evaluate(
        self,
        record: Mapping[str, object],
        rules: Sequence[OrganisationRule],
    ) -> RuleDecision | None:
        for rule in sorted(rules, key=lambda item: (item.priority, item.id or 0)):
            if not rule.enabled:
                continue
            actual = _field_value(record, rule.match_field)
            if not _compare(actual, str(rule.match_value or ""), rule.match_op.lower()):
                continue
            folder = _render(str(rule.folder_template or ""), record)
            name = _render(str(rule.name_template or ""), record)
            if not name:
                name = str(record.get("name") or "")
            return RuleDecision(
                relative_folder=folder,
                new_name=name,
                action=_action(rule, name, folder),
            )
        return None
