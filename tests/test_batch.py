"""Staged batch execution: holding area, rollback and batch lock."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.exceptions import OperationConflictError
from app.domain.enums import ActionType, PlanStatus
from app.domain.models import PlannedAction
from app.services import organisation_service as org_service
from tests.conftest import file_id_for, write_text


def _approved_plan(context, analysed_library) -> int:
    plan_id = context.organisation.create_plan()
    context.organisation.approve(plan_id)
    return plan_id


def test_batch_failure_restores_all_files(context, analysed_library, monkeypatch):
    plan_id = _approved_plan(context, analysed_library)
    originals = [p for p in analysed_library.rglob("*") if p.is_file()]
    real_move = org_service.move_no_overwrite
    calls = []

    def failing_move(source, destination, *args, **kwargs):
        calls.append(source)
        if len(calls) == 2:
            raise OSError("injected second-hop failure")
        return real_move(source, destination, *args, **kwargs)

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", failing_move)
    result = context.organisation.execute_batch(plan_id)
    assert result.state == "FAILED"
    assert all(path.exists() for path in originals)
    batch = context.batches.unfinished()[0]
    assert not list(batch.holding_dir.iterdir())


def test_crash_during_staging_keeps_file_in_rollback_scope(
    context, analysed_library, monkeypatch
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    original = Path(item.source_path)
    real_move = org_service.move_no_overwrite
    calls: list[Path] = []

    def crashing_move(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(source))
        if len(calls) == 1:
            real_move(source, destination, *args, **kwargs)
            raise OSError("injected crash after staging")
        return real_move(source, destination, *args, **kwargs)

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", crashing_move)

    result = context.organisation.execute_batch(plan_id)

    assert result.state == "FAILED"
    assert original.is_file()
    batch_id = context.batches.unfinished()[0].id
    records = context.batches.items_for_batch(batch_id)
    assert len(records) == 1
    assert records[0].state == "ROLLED_BACK"


def test_batch_rollback_leaves_foreign_final_content_in_place(
    context, tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "library"
    source = root / "a.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("original content", encoding="utf-8")
    context.scanning.scan(root)
    final = root / "Alpha.txt"
    action = PlannedAction(
        file_id=file_id_for(context, source),
        action=ActionType.RENAME,
        source_path=source,
        destination_path=final,
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
    )
    plan_id = context.operations.create_plan(root, [action])
    context.organisation.approve(plan_id)
    real_move = org_service.move_no_overwrite
    calls: list[Path] = []

    def hijacked_move(source_path, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(destination))
        result = real_move(source_path, destination, *args, **kwargs)
        if len(calls) == 2:
            Path(destination).write_text("foreign content", encoding="utf-8")
            raise OSError("injected failure after final move")
        return result

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", hijacked_move)

    result = context.organisation.execute_batch(plan_id)

    assert result.state == "FAILED"
    assert final.read_text(encoding="utf-8") == "foreign content"
    assert not source.exists()
    with context.db.engine.connect() as connection:
        details = connection.execute(
            text(
                "SELECT detail FROM operation_events "
                "WHERE operation_id = :operation_id AND event_type = 'rollback_failed'"
            ),
            {"operation_id": result.operation_ids[0]},
        ).scalars().all()
    assert details and "hash" in str(details[0]).lower()


def test_execute_batch_recomputes_stale_conflicts(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    source = root / "a.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("alpha content", encoding="utf-8")
    blocker = root / "Blocker.txt"
    blocker.write_text("old blocker", encoding="utf-8")
    context.scanning.scan(root)
    action = PlannedAction(
        file_id=file_id_for(context, source),
        action=ActionType.RENAME,
        source_path=source,
        destination_path=root / "Renamed.txt",
        original_name="a.txt",
        new_name="Renamed.txt",
        confidence=0.9,
        conflict="A file already exists at the destination.",
    )
    plan_id = context.operations.create_plan(root, [action])
    context.organisation.approve(plan_id)
    blocker.unlink()

    result = context.organisation.execute_batch(plan_id)

    assert result.state == "COMPLETED"
    assert len(result.completed) == 1
    assert (root / "Renamed.txt").read_text(encoding="utf-8") == "alpha content"
    assert all(row.conflict is None for row in context.operations.plan_items(plan_id))


def test_concurrent_execute_is_refused(context, analysed_library, monkeypatch):
    plan_id = _approved_plan(context, analysed_library)
    lock = threading.Lock()
    assert lock.acquire(blocking=False)
    monkeypatch.setattr("app.services.organisation_service._BATCH_LOCK", lock)
    with pytest.raises(OperationConflictError, match="already running"):
        context.organisation.execute_batch(plan_id)


def test_revalidate_held_item_uses_holding_path(context, analysed_library, tmp_path):
    plan_id = _approved_plan(context, analysed_library)
    holding = tmp_path / "holding"
    holding.mkdir()
    original = analysed_library / "Downloads" / "invoice_acme_2024.txt"
    file_id = file_id_for(context, original)
    batch_id = context.batches.create(plan_id, holding)
    held = holding / "held.txt"
    original.rename(held)
    context.batches.record_item(batch_id, file_id, original, held, Path("final"))
    context.batches.set_item_state(batch_id, file_id, "HELD")
    context.operations.update_plan_status(plan_id, PlanStatus.FAILED)
    context.organisation.revalidate(plan_id)
    assert all(item.conflict is None for item in context.operations.plan_items(plan_id))


def test_undo_still_works_after_completed_batch(context, analysed_library):
    plan_id = _approved_plan(context, analysed_library)
    result = context.organisation.execute_batch(plan_id)
    assert result.state == "COMPLETED"
    assert context.recovery.undo(result.operation_ids[0]).success is True


def test_execute_batch_orders_rename_chain_by_vacated_source(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    first = write_text(root / "a.txt", "A")
    second = write_text(root / "z.txt", "Z")
    third = write_text(root / "y.txt", "Y")
    context.scanning.scan(root)
    first_id = file_id_for(context, first)
    second_id = file_id_for(context, second)
    third_id = file_id_for(context, third)

    actions = [
        PlannedAction(
            file_id=first_id,
            action=ActionType.RENAME,
            source_path=first,
            destination_path=root / "z.txt",
            original_name=first.name,
            new_name="z.txt",
            confidence=0.9,
        ),
        PlannedAction(
            file_id=second_id,
            action=ActionType.RENAME,
            source_path=second,
            destination_path=root / "y.txt",
            original_name=second.name,
            new_name="y.txt",
            confidence=0.9,
        ),
        PlannedAction(
            file_id=third_id,
            action=ActionType.RENAME,
            source_path=third,
            destination_path=root / "x.txt",
            original_name=third.name,
            new_name="x.txt",
            confidence=0.9,
        ),
    ]
    plan_id = context.operations.create_plan(root, actions)
    context.organisation.approve(plan_id)

    result = context.organisation.execute_batch(plan_id)

    assert result.state == "COMPLETED"
    assert not first.exists()
    assert (root / "z.txt").read_text(encoding="utf-8") == "A"
    assert (root / "y.txt").read_text(encoding="utf-8") == "Z"
    assert (root / "x.txt").read_text(encoding="utf-8") == "Y"
