"""Regressions for audit findings in the organisation slice."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.core.constants import SUGGESTION_ACCEPTED, SUGGESTION_APPLIED, SUGGESTION_REJECTED
from app.domain.enums import ActionType, PlanStatus
from app.domain.models import PlannedAction
from app.organisation import planner as planner_module
from app.organisation.planner import OrganisationPlanner, PlanEntry, order_vacating_first
from app.services import organisation_service as org_service
from tests.conftest import file_id_for
from tests.test_organisation import _rename_plan


def _approved_plan(context) -> int:
    plan_id = context.organisation.create_plan()
    context.organisation.approve(plan_id)
    return plan_id


def test_batch_rollback_restores_held_item_that_reached_final(
    context, analysed_library, monkeypatch
) -> None:
    plan_id = _approved_plan(context)
    item = context.operations.plan_items(plan_id)[0]
    original = Path(item.source_path)
    final = Path(item.destination_path)
    real_move = org_service.move_no_overwrite
    calls: list[tuple[Path, Path]] = []

    def failing_move(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((Path(source), Path(destination)))
        result = real_move(source, destination, *args, **kwargs)
        if len(calls) == 2:
            raise OSError("injected failure after the final move")
        return result

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", failing_move)

    result = context.organisation.execute_batch(plan_id)

    assert result.state == "FAILED"
    assert original.is_file()
    assert not final.exists()
    summary = context.files.get_summary(item.file_id)
    assert summary is not None and summary.path == str(original)
    batch = context.batches.unfinished()[0]
    record = context.batches.items_for_batch(batch.id)[0]
    assert record.state == "ROLLED_BACK"
    assert {op.status for op in context.recovery.history()} == {"rolled_back"}
    assert all(row.status == "pending" for row in context.organisation.items(plan_id))


def test_executor_failure_after_move_reverts_location_and_index(
    context, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    source = root / "a.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("alpha content", encoding="utf-8")
    context.scanning.scan(root)
    file_id = file_id_for(context, source)
    destination = root / "Alpha.txt"
    action = PlannedAction(
        file_id=file_id,
        action=ActionType.RENAME,
        source_path=source,
        destination_path=destination,
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
    )

    def fail_complete(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(context.operations, "complete_operation", fail_complete)

    report = context.executor.execute(root, [action])

    assert len(report.failed) == 1
    assert source.is_file()
    assert not destination.exists()
    summary = context.files.get_summary(file_id)
    assert summary is not None and summary.path == str(source)
    with context.db.engine.connect() as connection:
        indexed_names = connection.execute(text("SELECT filename FROM file_fts")).scalars().all()
    assert "a.txt" in indexed_names
    assert "Alpha.txt" not in indexed_names


def test_execute_uses_plan_root_after_setting_changes(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    plan_id, _ = _rename_plan(context, root)
    context.settings.set_organisation_root(tmp_path / "different-root")

    report = context.organisation.execute(plan_id)

    assert len(report.completed) == 2
    assert (root / "Finance" / "Alpha.txt").read_text(encoding="utf-8") == "alpha content"


def test_revalidate_repairs_approved_plan_with_stored_root(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    plan_id, _ = _rename_plan(context, root)
    item = context.operations.plan_items(plan_id)[0]
    context.operations.update_item_conflict(item.id, "stale conflict")
    context.settings.set_organisation_root(tmp_path / "different-root")

    context.organisation.revalidate(plan_id)

    assert context.organisation.plan(plan_id)["status"] == "draft"
    assert all(row.conflict is None for row in context.organisation.items(plan_id))


def test_organisation_root_uses_common_parent_without_config(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    for index in range(20):
        path = root / "Downloads" / f"download-{index}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("download", encoding="utf-8")
    for index in range(2):
        path = root / "Documents" / f"document-{index}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("document", encoding="utf-8")

    context.scanning.scan(root)
    context.settings.set_organisation_root(None)

    assert context.settings.organisation_root is None
    assert context.organisation.organisation_root() == root


def test_planner_allows_rename_chain_and_vacates_destination_first(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    first = root / "a.txt"
    second = root / "b.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    draft = OrganisationPlanner().plan(
        root,
        [
            PlanEntry(1, first, "a.txt", "b.txt", Path("."), 0.9),
            PlanEntry(2, second, "b.txt", "c.txt", Path("."), 0.9),
        ],
    )

    assert len(draft.actions) == 2
    assert all(action.conflict is None for action in draft.actions)
    assert [action.file_id for action in draft.actions] == [2, 1]


def test_planner_orders_three_step_rename_chain(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    a = root / "a.txt"
    b = root / "b.txt"
    c = root / "c.txt"
    for path, content in ((a, "alpha"), (b, "beta"), (c, "gamma")):
        path.write_text(content, encoding="utf-8")

    draft = OrganisationPlanner().plan(
        root,
        [
            PlanEntry(1, a, "a.txt", "b.txt", Path("."), 0.9),
            PlanEntry(2, b, "b.txt", "c.txt", Path("."), 0.9),
            PlanEntry(3, c, "c.txt", "d.txt", Path("."), 0.9),
        ],
    )

    assert len(draft.actions) == 3
    assert all(action.conflict is None for action in draft.actions)
    assert [action.file_id for action in draft.actions] == [3, 2, 1]


def test_planner_marks_circular_rename_as_conflict(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    first = root / "a.txt"
    second = root / "b.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    draft = OrganisationPlanner().plan(
        root,
        [
            PlanEntry(1, first, "a.txt", "b.txt", Path("."), 0.9),
            PlanEntry(2, second, "b.txt", "a.txt", Path("."), 0.9),
        ],
    )

    assert len(draft.actions) == 2
    assert all("circular" in (action.conflict or "").lower() for action in draft.actions)


def test_order_vacating_first_computes_prerequisites_once(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    calls = {"path_key": 0}
    real_path_key = planner_module.path_key

    def counting_path_key(path: Path):  # type: ignore[no-untyped-def]
        calls["path_key"] += 1
        return real_path_key(path)

    monkeypatch.setattr(planner_module, "path_key", counting_path_key)
    size = 300
    actions = [
        PlannedAction(
            file_id=index,
            action=ActionType.RENAME,
            source_path=root / f"{index}.txt",
            destination_path=root / f"{index + 1}.txt",
            original_name=f"{index}.txt",
            new_name=f"{index + 1}.txt",
            confidence=0.9,
        )
        for index in range(size)
    ]

    ordered = order_vacating_first(actions)

    assert [action.file_id for action in ordered] == list(reversed(range(size)))
    assert calls["path_key"] <= 2 * size + 10


def test_revalidate_keeps_rename_chain_without_false_conflicts(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    first = root / "a.txt"
    second = root / "b.txt"
    third = root / "c.txt"
    for path, content in ((first, "alpha"), (second, "beta")):
        path.write_text(content, encoding="utf-8")
    context.scanning.scan(root)
    ids = {path.name: file_id_for(context, path) for path in (first, second)}

    actions = [
        PlannedAction(
            file_id=ids["b.txt"],
            action=ActionType.RENAME,
            source_path=second,
            destination_path=third,
            original_name="b.txt",
            new_name="c.txt",
            confidence=0.9,
        ),
        PlannedAction(
            file_id=ids["a.txt"],
            action=ActionType.RENAME,
            source_path=first,
            destination_path=second,
            original_name="a.txt",
            new_name="b.txt",
            confidence=0.9,
        ),
    ]
    plan_id = context.operations.create_plan(root, actions)
    context.organisation.approve(plan_id)
    context.operations.update_plan_status(plan_id, PlanStatus.REVALIDATION_REQUIRED)

    context.organisation.revalidate(plan_id)

    assert all(item.conflict is None for item in context.operations.plan_items(plan_id))


def test_execute_recomputes_conflict_after_planning(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = root / "a.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("alpha content", encoding="utf-8")
    blocker = root / "Alpha.txt"
    blocker.write_text("old blocker", encoding="utf-8")
    context.scanning.scan(root)
    file_id = file_id_for(context, source)
    action = PlannedAction(
        file_id=file_id,
        action=ActionType.RENAME,
        source_path=source,
        destination_path=blocker,
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
        conflict="A file already exists at the destination.",
    )
    plan_id = context.operations.create_plan(root, [action])
    context.organisation.approve(plan_id)
    blocker.unlink()

    report = context.organisation.execute(plan_id)

    assert len(report.completed) == 1
    assert blocker.read_text(encoding="utf-8") == "alpha content"
    assert all(row.conflict is None for row in context.organisation.items(plan_id))
    with context.db.engine.connect() as connection:
        stale = connection.execute(
            text(
                "SELECT current_path, is_available, processing_status FROM files "
                "WHERE original_path = :path AND id != :id"
            ),
            {"path": str(blocker), "id": file_id},
        ).all()
    assert len(stale) == 1
    assert "missing file" in stale[0][0]
    assert stale[0][1] == 0
    assert stale[0][2] == "unavailable"


def test_undo_resets_applied_suggestions_to_accepted(context, analysed_library) -> None:
    plan_id = _approved_plan(context)
    item = context.operations.plan_items(plan_id)[0]
    all_ids = context.analyses.suggestion_ids_for_file(item.file_id)
    relevant = {
        kind: all_ids[kind] for kind in ("filename", "destination") if kind in all_ids
    }
    assert len(relevant) == 2

    context.organisation.execute(plan_id)

    assert all(
        context.analyses.suggestion_status(suggestion_id) == SUGGESTION_APPLIED
        for suggestion_id in relevant.values()
    )
    operation = next(op for op in context.recovery.history() if op.file_id == item.file_id)

    context.recovery.undo(operation.id)

    assert all(
        context.analyses.suggestion_status(suggestion_id) == SUGGESTION_ACCEPTED
        for suggestion_id in relevant.values()
    )


def test_undo_does_not_revive_rejected_suggestion(context, analysed_library) -> None:
    plan_id = _approved_plan(context)
    item = context.operations.plan_items(plan_id)[0]
    relevant = [
        suggestion_id
        for kind, suggestion_id in context.analyses.suggestion_ids_for_file(item.file_id).items()
        if kind in {"filename", "destination"}
    ]

    context.organisation.execute(plan_id)
    operation = next(op for op in context.recovery.history() if op.file_id == item.file_id)
    rejected_id = relevant[0]
    context.analyses.set_suggestion_status(rejected_id, SUGGESTION_REJECTED)

    context.recovery.undo(operation.id)

    assert context.analyses.suggestion_status(rejected_id) == SUGGESTION_REJECTED
