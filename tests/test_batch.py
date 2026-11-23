"""Staged batch execution: holding area, rollback and batch lock."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core.exceptions import OperationConflictError
from app.domain.enums import PlanStatus
from app.services import organisation_service as org_service
from tests.conftest import file_id_for


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
