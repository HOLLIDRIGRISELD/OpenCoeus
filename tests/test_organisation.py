"""Planning, safe execution, filesystem primitives and recovery."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.constants import STATUS_ORGANISED
from app.core.exceptions import OperationConflictError, RecoveryError
from app.domain.enums import ActionType
from app.domain.models import PlannedAction
from app.organisation import fsops
from app.organisation.executor import move_no_overwrite as executor_move
from app.organisation.fsops import move_no_overwrite, reserve_path
from app.organisation.planner import OrganisationPlanner, PlanEntry
from app.processing.hashing import sha256_file
from app.services.context import AppContext
from tests.conftest import file_id_for


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _case_insensitive(directory: Path) -> bool:
    """Return True when the filesystem treats names differing only by case alike."""

    probe = directory / "CaseProbe"
    probe.write_text("x", encoding="utf-8")
    same = (directory / "caseprobe").exists()
    probe.unlink()
    return same




def test_planner_disambiguates_duplicate_targets(tmp_path: Path) -> None:
    root = tmp_path / "library"
    first = _write(root / "Downloads" / "a.txt", "alpha")
    second = _write(root / "Downloads" / "b.txt", "beta")

    draft = OrganisationPlanner(low_confidence=0.6).plan(
        root,
        [
            PlanEntry(
                file_id=1,
                source_path=first,
                original_name="a.txt",
                new_name="Alpha.txt",
                relative_folder=Path("Finance"),
                confidence=0.9,
            ),
            PlanEntry(
                file_id=2,
                source_path=second,
                original_name="b.txt",
                new_name="Alpha.txt",
                relative_folder=Path("Finance"),
                confidence=0.4,
            ),
        ],
    )

    assert sorted(action.new_name for action in draft.actions) == ["Alpha 2.txt", "Alpha.txt"]
    assert all(action.conflict is None for action in draft.actions)
    assert draft.summary.conflicts == 0
    assert draft.summary.needs_review == 1
    assert draft.summary.renames == 2
    assert draft.summary.moves == 2
    assert any("2" in " ".join(action.notes) for action in draft.actions)


def test_planner_keeps_existing_destination_conflict(tmp_path: Path) -> None:
    root = tmp_path / "library"
    _write(root / "Finance" / "Alpha.txt", "occupied")
    source = _write(root / "Downloads" / "b.txt", "beta")

    draft = OrganisationPlanner(low_confidence=0.6).plan(
        root,
        [
            PlanEntry(
                file_id=2,
                source_path=source,
                original_name="b.txt",
                new_name="Alpha.txt",
                relative_folder=Path("Finance"),
                confidence=0.9,
            ),
        ],
    )

    assert draft.actions[0].conflict is not None


def test_planner_marks_unchanged_entries(tmp_path: Path) -> None:
    root = tmp_path / "library"
    current = _write(root / "Finance" / "Keep.txt", "keep")

    draft = OrganisationPlanner().plan(
        root,
        [
            PlanEntry(
                file_id=7,
                source_path=current,
                original_name="Keep.txt",
                new_name="Keep.txt",
                relative_folder=Path("Finance"),
                confidence=0.9,
            )
        ],
    )

    assert draft.actions == []
    assert draft.unchanged == [7]
    assert draft.summary.unchanged == 1


def test_planner_keeps_case_only_rename(tmp_path: Path) -> None:
    """A genuine case-only rename must not be silently dropped as unchanged."""

    if not _case_insensitive(tmp_path):
        pytest.skip("requires a case-insensitive filesystem")

    root = tmp_path / "library"
    current = _write(root / "Downloads" / "beta.txt", "beta content")

    draft = OrganisationPlanner().plan(
        root,
        [
            PlanEntry(
                file_id=7,
                source_path=current,
                original_name="beta.txt",
                new_name="Beta.txt",
                relative_folder=Path("Downloads"),
                confidence=0.9,
            )
        ],
    )

    assert draft.unchanged == []
    assert len(draft.actions) == 1
    assert draft.actions[0].action is ActionType.RENAME
    assert draft.actions[0].new_name == "Beta.txt"


def test_planner_blocks_path_traversal_and_missing_sources(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    existing = _write(root / "a.txt", "alpha")

    draft = OrganisationPlanner().plan(
        root,
        [
            PlanEntry(
                file_id=1,
                source_path=existing,
                original_name="a.txt",
                new_name="Alpha.txt",
                relative_folder=Path("../outside"),
                confidence=0.9,
            ),
            PlanEntry(
                file_id=2,
                source_path=root / "missing.txt",
                original_name="missing.txt",
                new_name="Missing.txt",
                relative_folder=Path("Finance"),
                confidence=0.9,
            ),
        ],
    )

    messages = " ".join(action.conflict or "" for action in draft.actions)
    assert "escape" in messages or "outside" in messages
    assert "no longer exists" in messages
    assert len(draft.blocked) == 2


def test_planner_skips_duplicate_and_empty_entries(tmp_path: Path) -> None:
    root = tmp_path / "library"
    file = _write(root / "a.txt", "alpha")
    entry = PlanEntry(
        file_id=1,
        source_path=file,
        original_name="a.txt",
        new_name="Alpha.txt",
        relative_folder=Path("Finance"),
    )

    draft = OrganisationPlanner().plan(
        root,
        [
            entry,
            entry,
            PlanEntry(
                file_id=2,
                source_path=file,
                original_name="a.txt",
                new_name="",
                relative_folder=Path("Finance"),
            ),
        ],
    )

    assert draft.skipped == [(1, "Duplicate plan entry for this file."), (2, "No filename was proposed.")]
    assert len(draft.actions) == 1




def _rename_plan(context: AppContext, root: Path) -> tuple[int, dict[str, Path]]:
    paths = {
        "alpha": root / "Downloads" / "alpha.txt",
        "beta": root / "Downloads" / "beta.txt",
    }
    _write(paths["alpha"], "alpha content")
    _write(paths["beta"], "beta content")
    context.scanning.scan(root)
    alpha_id = file_id_for(context, paths["alpha"])
    beta_id = file_id_for(context, paths["beta"])

    actions = [
        PlannedAction(
            file_id=alpha_id,
            action=ActionType.RENAME_AND_MOVE,
            source_path=paths["alpha"],
            destination_path=root / "Finance" / "Alpha.txt",
            original_name="alpha.txt",
            new_name="Alpha.txt",
            confidence=0.9,
        ),
        PlannedAction(
            file_id=beta_id,
            action=ActionType.RENAME,
            source_path=paths["beta"],
            destination_path=root / "Downloads" / "Beta.txt",
            original_name="beta.txt",
            new_name="Beta.txt",
            confidence=0.9,
        ),
    ]
    plan_id = context.operations.create_plan(root, actions)
    context.organisation.approve(plan_id)
    return plan_id, paths


def test_execute_moves_files_updates_database_and_undo_restores(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    plan_id, paths = _rename_plan(context, root)

    report = context.organisation.execute(plan_id)

    assert report.failed == []
    assert len(report.completed) == 2
    assert (root / "Finance" / "Alpha.txt").read_text(encoding="utf-8") == "alpha content"
    assert (root / "Downloads" / "Beta.txt").read_text(encoding="utf-8") == "beta content"
    assert not paths["alpha"].exists()
    beta_names = {item.name for item in paths["beta"].parent.iterdir()}
    assert "beta.txt" not in beta_names
    assert "Beta.txt" in beta_names

    alpha_id = file_id_for(context, root / "Finance" / "Alpha.txt")
    summary = context.files.get_summary(alpha_id)
    assert summary is not None and summary.path == str(root / "Finance" / "Alpha.txt")

    plan = context.organisation.plan(plan_id)
    assert plan["status"] == "completed"
    assert context.organisation.summary(plan_id).renames == 2

    history = context.recovery.history()
    assert len(history) == 2
    assert all(operation.status == "completed" and operation.undoable for operation in history)

    result = context.recovery.undo(history[0].id)
    assert result.success is True
    restored = Path(history[0].source_path)
    assert restored.exists()
    assert not Path(history[0].destination_path).exists()
    assert context.recovery.operation(history[0].id)["status"] == "rolled_back"


def test_executor_skips_conflicting_actions_without_touching_files(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    path = _write(root / "a.txt", "alpha")
    context.scanning.scan(root)
    file_id = file_id_for(context, path)

    action = PlannedAction(
        file_id=file_id,
        action=ActionType.RENAME,
        source_path=path,
        destination_path=root / "Alpha.txt",
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
        conflict="A file already exists at the destination.",
    )
    report = context.executor.execute(root, [action])

    assert len(report.skipped) == 1
    assert report.completed == []
    assert report.failed == []
    assert path.exists()
    assert context.recovery.history() == []


def test_executor_reports_missing_source(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    action = PlannedAction(
        file_id=999,
        action=ActionType.MOVE,
        source_path=root / "missing.txt",
        destination_path=root / "Finance" / "missing.txt",
        original_name="missing.txt",
        new_name="missing.txt",
        confidence=0.9,
    )

    report = context.executor.execute(root, [action])

    assert len(report.failed) == 1
    assert "no longer exists" in report.failed[0].message.lower()
    assert not (root / "Finance").exists()


def test_executor_rejects_source_hash_mismatch_before_recording(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    source = _write(root / "a.txt", "original content")
    context.scanning.scan(root)
    file_id = file_id_for(context, source)

    action = PlannedAction(
        file_id=file_id,
        action=ActionType.RENAME,
        source_path=source,
        destination_path=root / "renamed.txt",
        original_name="a.txt",
        new_name="renamed.txt",
        confidence=0.9,
        expected_hash="0" * 64,
    )

    report = context.executor.execute(root, [action])

    assert len(report.failed) == 1
    assert source.read_text(encoding="utf-8") == "original content"
    assert not (root / "renamed.txt").exists()
    assert context.recovery.history() == []


def test_failed_rollback_reports_where_the_file_stayed(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    path = _write(root / "a.txt", "alpha")
    context.scanning.scan(root)
    destination = root / "Alpha.txt"
    action = PlannedAction(
        file_id=file_id_for(context, path),
        action=ActionType.MOVE,
        source_path=path,
        destination_path=destination,
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
    )
    calls: list[tuple[Path, Path]] = []

    def failing_move(source: Path, target: Path, **kwargs: object) -> None:
        calls.append((source, target))
        if len(calls) == 1:
            move_no_overwrite(source, target, **kwargs)
            return
        raise OSError("locked")

    def fail_update(*args: object, **kwargs: object) -> None:
        raise OSError("database down")

    monkeypatch.setattr("app.organisation.executor.move_no_overwrite", failing_move)
    monkeypatch.setattr(context.executor._files, "update_location", fail_update)

    report = context.executor.execute(root, [action])

    assert len(report.failed) == 1
    assert str(destination) in report.failed[0].message
    assert destination.exists()

def test_rollback_leaves_foreign_destination_content_in_place(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    source = _write(root / "a.txt", "original content")
    context.scanning.scan(root)
    destination = root / "Alpha.txt"
    action = PlannedAction(
        file_id=file_id_for(context, source),
        action=ActionType.RENAME,
        source_path=source,
        destination_path=destination,
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
        expected_hash=sha256_file(source),
    )

    calls = {"count": 0}

    def hijacked_move(src: Path, dst: Path, **kwargs: object) -> None:
        executor_move(src, dst, **kwargs)
        calls["count"] += 1
        if calls["count"] == 1:
            Path(dst).write_text("foreign content", encoding="utf-8")
            raise OSError("injected failure after move")

    monkeypatch.setattr("app.organisation.executor.move_no_overwrite", hijacked_move)

    report = context.executor.execute(root, [action])

    assert len(report.failed) == 1
    assert destination.read_text(encoding="utf-8") == "foreign content"
    assert not source.exists()
    with context.db.engine.connect() as connection:
        details = connection.execute(
            text(
                "SELECT detail FROM operation_events "
                "WHERE operation_id = :operation_id AND event_type = 'rollback_failed'"
            ),
            {"operation_id": report.failed[0].operation_id},
        ).scalars().all()
    assert details and "hash" in str(details[0]).lower()


def test_undo_refuses_when_original_location_is_occupied(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    plan_id, paths = _rename_plan(context, root)
    context.organisation.execute(plan_id)
    operation = context.recovery.history()[0]
    original = Path(operation.source_path)
    organised = Path(operation.destination_path)

    _write(original, "a new file appeared here")

    with pytest.raises(RecoveryError):
        context.recovery.undo(operation.id)

    assert original.exists()
    assert organised.exists()
    assert context.recovery.operation(operation.id)["undoable"] is False


def test_undo_restores_case_only_rename(context: AppContext, tmp_path: Path) -> None:
    """Undo must reverse a case-only rename instead of refusing it."""

    if not _case_insensitive(tmp_path):
        pytest.skip("requires a case-insensitive filesystem")

    root = tmp_path / "library"
    plan_id, paths = _rename_plan(context, root)
    context.organisation.execute(plan_id)

    operation = next(
        item
        for item in context.recovery.history()
        if Path(item.destination_path).name == "Beta.txt"
    )
    result = context.recovery.undo(operation.id)

    assert result.success is True
    names = {item.name for item in paths["beta"].parent.iterdir()}
    assert "beta.txt" in names
    assert "Beta.txt" not in names
    assert context.recovery.operation(operation.id)["status"] == "rolled_back"




def test_interrupted_plan_can_be_revalidated_and_retried(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted plan must have a recovery path back to an executable state."""

    root = tmp_path / "library"
    plan_id, _ = _rename_plan(context, root)

    real_execute = context.organisation._executor.execute
    calls = {"n": 0}

    def flaky_execute(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash mid-execution")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(context.organisation._executor, "execute", flaky_execute)

    with pytest.raises(RuntimeError):
        context.organisation.execute(plan_id)
    assert context.organisation.plan(plan_id)["status"] == "revalidation_required"

    context.organisation.revalidate(plan_id)
    assert context.organisation.plan(plan_id)["status"] == "draft"

    context.organisation.approve(plan_id)
    report = context.organisation.execute(plan_id)
    assert len(report.completed) == 2
    assert (root / "Finance" / "Alpha.txt").read_text(encoding="utf-8") == "alpha content"


def test_retry_after_partial_run_skips_completed_items(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed item must not be reprocessed when an interrupted plan is retried."""

    root = tmp_path / "library"
    plan_id, _paths = _rename_plan(context, root)

    real_execute = context.organisation._executor.execute
    calls = {"n": 0}
    seen: dict[str, list[PlannedAction]] = {}

    def flaky_execute(root_path, actions, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            real_execute(root_path, actions[:1], **kwargs)
            raise RuntimeError("simulated crash mid-execution")
        seen["actions"] = actions
        return real_execute(root_path, actions, **kwargs)

    monkeypatch.setattr(context.organisation._executor, "execute", flaky_execute)

    with pytest.raises(RuntimeError):
        context.organisation.execute(plan_id)
    assert context.organisation.plan(plan_id)["status"] == "revalidation_required"

    context.organisation.revalidate(plan_id)
    context.organisation.approve(plan_id)
    report = context.organisation.execute(plan_id)

    assert len(seen["actions"]) == 1
    assert len(report.completed) == 1


def test_post_processing_error_does_not_leave_plan_executing(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any failure after the move must mark the plan for revalidation, not EXECUTING."""

    root = tmp_path / "library"
    plan_id, _ = _rename_plan(context, root)

    real_update = context.files.update_status

    def flaky_update(file_id: int, status: str) -> None:
        if status == STATUS_ORGANISED:
            raise RuntimeError("simulated database failure")
        real_update(file_id, status)

    monkeypatch.setattr(context.files, "update_status", flaky_update)

    with pytest.raises(RuntimeError):
        context.organisation.execute(plan_id)
    assert context.organisation.plan(plan_id)["status"] == "revalidation_required"




def test_move_no_overwrite_never_overwrites(tmp_path: Path) -> None:
    source = _write(tmp_path / "source.txt", "source")
    destination = _write(tmp_path / "destination.txt", "destination")

    with pytest.raises(OperationConflictError):
        move_no_overwrite(source, destination)

    assert source.read_text(encoding="utf-8") == "source"
    assert destination.read_text(encoding="utf-8") == "destination"


def test_reserve_path_is_exclusive(tmp_path: Path) -> None:
    target = tmp_path / "reserved.txt"
    reserve_path(target)
    assert target.exists()

    with pytest.raises(OperationConflictError):
        reserve_path(target)

    fsops.release_path(target)
    assert not target.exists()


def test_move_falls_back_to_copy_verify_and_unlink_across_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path / "source.txt", "portable content")
    destination = tmp_path / "moved" / "destination.txt"
    destination.parent.mkdir()

    real_replace = os.replace

    def fake_replace(src, dst):
        if Path(src) == source:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(fsops.os, "replace", fake_replace)

    from app.processing.hashing import sha256_file

    expected = sha256_file(source)
    move_no_overwrite(source, destination, expected_hash=expected)

    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "portable content"
    assert sha256_file(destination) == expected


def test_case_only_rename_rollback_when_second_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rollback must not lose data when the temporary→destination rename fails.

    On a case-insensitive filesystem the empty destination reservation makes
    ``source.exists()`` true, so the historical rollback skipped restoring the
    content and stranded it at the hidden temporary name.
    """

    if not _case_insensitive(tmp_path):
        pytest.skip("requires a case-insensitive filesystem")

    source = _write(tmp_path / "beta.txt", "precious content")
    destination = tmp_path / "Beta.txt"

    real_replace = fsops.os.replace
    calls = {"n": 0}

    def failing_second_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(errno.EACCES, "simulated failure moving into place")
        return real_replace(src, dst)

    monkeypatch.setattr(fsops.os, "replace", failing_second_replace)

    from app.organisation.fsops import _rename_case_only

    with pytest.raises(OSError):
        _rename_case_only(source, destination, expected_hash=None)

    assert source.read_text(encoding="utf-8") == "precious content"
    assert list(tmp_path.glob(".opencoeus-*")) == []


def test_case_only_rename_rollback_when_reservation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rollback must not delete the restored source when reserving fails.

    On a case-insensitive filesystem ``destination`` and ``source`` are the same
    physical path, so ``release_path(destination)`` deleted the just-restored
    content in the historical implementation.
    """

    if not _case_insensitive(tmp_path):
        pytest.skip("requires a case-insensitive filesystem")

    source = _write(tmp_path / "beta.txt", "precious content")
    destination = tmp_path / "Beta.txt"

    real_reserve = fsops.reserve_path

    def failing_reserve(path):
        if path == destination:
            raise OperationConflictError("simulated reservation conflict")
        return real_reserve(path)

    monkeypatch.setattr(fsops, "reserve_path", failing_reserve)

    from app.organisation.fsops import _rename_case_only

    with pytest.raises(OperationConflictError):
        _rename_case_only(source, destination, expected_hash=None)

    assert source.read_text(encoding="utf-8") == "precious content"
    assert list(tmp_path.glob(".opencoeus-*")) == []
