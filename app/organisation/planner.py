"""Builds a reviewable, validated organisation plan.

The planner is a pure transformation: it receives file records plus proposed
names and folders and returns :class:`PlannedAction` objects with conflicts
attached. It never touches the filesystem beyond read-only checks, which makes
it cheap to preview and straightforward to unit-test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.constants import ACTION_MKDIR
from app.domain.enums import ActionType
from app.domain.models import PlannedAction, PlanSummary
from app.organisation.validator import PathGuard, path_key


@dataclass(slots=True)
class PlanEntry:
    """A proposed change before validation.

    Args:
        file_id: Database identity of the file.
        source_path: Current absolute path.
        original_name: Current filename.
        new_name: Proposed filename (single path component).
        relative_folder: Destination folder relative to the organisation root.
        confidence: Combined confidence of the name and folder suggestions.
        suggestion_id: Filename suggestion row, when the entry came from one.
        notes: Human-readable reasons carried into the plan.
    """

    file_id: int
    source_path: Path
    original_name: str
    new_name: str
    relative_folder: Path
    confidence: float = 0.0
    suggestion_id: int | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlanDraft:
    """Validated plan ready for review or persistence."""

    root: Path
    actions: list[PlannedAction] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def summary(self) -> PlanSummary:
        summary = PlanSummary(total=len(self.actions), unchanged=len(self.unchanged))
        folders: set[Path] = set()
        for action in self.actions:
            same_path = os.path.normcase(os.path.abspath(action.source_path)) == os.path.normcase(
                os.path.abspath(action.destination_path)
            )
            if action.conflict and not same_path:
                summary.conflicts += 1
            if action.action in {ActionType.MOVE, ActionType.RENAME_AND_MOVE}:
                summary.moves += 1
            if action.action in {ActionType.RENAME, ActionType.RENAME_AND_MOVE}:
                summary.renames += 1
            if action.confidence < 0.60:
                summary.needs_review += 1
            folders.add(action.destination_path.parent)
        summary.new_folders = sum(1 for folder in folders if not folder.exists())
        return summary

    @property
    def executable(self) -> list[PlannedAction]:
        return [action for action in self.actions if action.conflict is None]

    @property
    def blocked(self) -> list[PlannedAction]:
        return [action for action in self.actions if action.conflict is not None]


def order_vacating_first(actions: list[PlannedAction]) -> list[PlannedAction]:
    """Order actions so a source freed by one action is available to the next."""

    by_source: dict[str, list[int]] = {}
    for index, action in enumerate(actions):
        by_source.setdefault(path_key(action.source_path), []).append(index)

    def prerequisites(index: int, visiting: frozenset[int]) -> set[int]:
        if index in visiting:
            return set()
        destination = path_key(actions[index].destination_path)
        result: set[int] = set()
        for earlier in by_source.get(destination, []):
            if earlier == index:
                continue
            result.add(earlier)
            result |= prerequisites(earlier, visiting | {index})
        return result

    def sort_key(item: tuple[int, PlannedAction]) -> tuple:
        index, action = item
        return (
            action.conflict is not None,
            len(prerequisites(index, frozenset())),
            str(action.destination_path),
        )

    return [action for _, action in sorted(enumerate(actions), key=sort_key)]


class OrganisationPlanner:
    """Validates proposed changes and assigns action types.

    Args:
        low_confidence: Entries below this threshold are annotated for review.
        max_filename_length: Passed to the path guard.
    """

    def __init__(
        self,
        *,
        low_confidence: float = 0.60,
        max_filename_length: int = 120,
    ) -> None:
        self.low_confidence = low_confidence
        self.max_filename_length = max_filename_length

    def plan(self, root: Path, entries: list[PlanEntry]) -> PlanDraft:
        root = Path(root).expanduser().resolve(strict=False)
        guard = PathGuard(root, max_filename_length=self.max_filename_length)
        draft = PlanDraft(root=root)

        if not root.exists():
            draft.warnings.append(
                f"The organisation root {root} does not exist yet; it will be created."
            )

        seen_files: set[int] = set()
        claimed: set[str] = set()
        candidates: list[tuple[PlanEntry, Path, bool]] = []

        for entry in entries:
            if entry.file_id in seen_files:
                draft.skipped.append((entry.file_id, "Duplicate plan entry for this file."))
                continue
            seen_files.add(entry.file_id)

            name = (entry.new_name or "").strip()
            folder = Path(entry.relative_folder)
            if not name:
                draft.skipped.append((entry.file_id, "No filename was proposed."))
                continue

            destination = root / folder / name
            same_path = os.path.normpath(os.path.abspath(destination)) == os.path.normpath(
                os.path.abspath(entry.source_path)
            )
            if same_path:
                draft.unchanged.append(entry.file_id)
                continue
            candidates.append((entry, destination, False))

        vacating = {path_key(entry.source_path) for entry, _, _ in candidates}
        for entry, destination, _ in candidates:
            source = Path(entry.source_path)
            key = str(destination.resolve(strict=False)).lower()
            check = guard.check_destination(
                destination, source=source, occupied=claimed, vacating=vacating
            )
            claimed.add(key)

            issues = list(check.issues)
            issues.extend(guard.check_source(source))

            conflicts = [issue for issue in issues if issue.is_error]
            notes = list(entry.notes)
            notes.extend(issue.message for issue in issues if issue.is_error)
            notes.extend(issue.message for issue in issues if not issue.is_error)

            confidence = round(float(entry.confidence), 3)
            if confidence < self.low_confidence:
                notes.append(
                    f"Confidence {confidence:.0%} is below the review threshold "
                    f"({self.low_confidence:.0%})."
                )

            new_name = destination.name
            if new_name == source.name:
                action_type = ActionType.MOVE
            elif destination.parent == source.parent:
                action_type = ActionType.RENAME
            else:
                action_type = ActionType.RENAME_AND_MOVE

            draft.actions.append(
                PlannedAction(
                    file_id=entry.file_id,
                    action=action_type,
                    source_path=source,
                    destination_path=destination,
                    original_name=entry.original_name,
                    new_name=new_name,
                    confidence=confidence,
                    suggestion_id=entry.suggestion_id,
                    conflict=conflicts[0].message if conflicts else None,
                    notes=list(dict.fromkeys(note for note in notes if note)),
                )
            )

        draft.actions = order_vacating_first(draft.actions)
        folders = {str(action.destination_path.parent) for action in draft.actions}
        if folders:
            draft.warnings.append(
                f"{len(folders)} destination folder(s); "
                f"{draft.summary.new_folders} will be created."
            )
        draft.warnings.append(f"{ACTION_MKDIR.replace('_', ' ')} is implicit and logged per operation.")
        return draft
