"""Regression tests for organisation execution and recovery safety."""

from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

from app.core.exceptions import DatabaseError, InvalidRecommendationError
from app.domain.enums import PlanStatus
from app.infrastructure.repositories.batches import cleanup_stale_batches
from app.organisation.fsops import HashMismatchError, _rename_case_only
from app.processing.hashing import sha256_file
from app.services import organisation_service as org_service
from tests.test_organisation import _case_insensitive, _rename_plan


def _approved_plan(context, analysed_library) -> int:
    plan_id = context.organisation.create_plan()
    context.organisation.approve(plan_id)
    return plan_id


def test_mutating_operation_lookup_raises_for_missing_row(context) -> None:
    with pytest.raises(DatabaseError):
        context.operations.complete_operation(10**9, destination_hash=None)


def test_set_organisation_root_uses_validated_settings_path(
    context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    seen: dict[str, object] = {}

    def fake_apply(values: dict[str, object]) -> list[str]:
        seen.update(values)
        return ["invalid root"]

    monkeypatch.setattr(context, "apply_settings", fake_apply)

    problems = context.set_organisation_root(root)

    assert Path(str(seen["organisation.root"])) == root.resolve()
    assert problems == ["invalid root"]


def test_plan_claim_is_atomic_against_stale_status(context, analysed_library) -> None:
    plan_id = _approved_plan(context, analysed_library)

    assert context.operations.claim_plan(plan_id)
    assert not context.operations.claim_plan(plan_id)
    assert context.organisation.plan(plan_id)["status"] == PlanStatus.EXECUTING.value


def test_execute_refuses_when_plan_claim_is_lost(
    context, analysed_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    source = Path(context.operations.plan_items(plan_id)[0].source_path)
    monkeypatch.setattr(context.operations, "claim_plan", lambda *_a, **_k: False)

    with pytest.raises(InvalidRecommendationError, match="claimed by another run"):
        context.organisation.execute(plan_id)

    assert source.is_file()
    assert context.organisation.plan(plan_id)["status"] == PlanStatus.APPROVED.value


def test_batch_execute_refuses_when_plan_claim_is_lost(
    context, analysed_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    monkeypatch.setattr(context.operations, "claim_plan", lambda *_a, **_k: False)

    with pytest.raises(InvalidRecommendationError, match="claimed by another run"):
        context.organisation.execute_batch(plan_id)

    assert context.organisation.plan(plan_id)["status"] == PlanStatus.APPROVED.value


def test_execute_without_approval_preserves_draft_behaviour(context, analysed_library) -> None:
    plan_id = context.organisation.create_plan()
    source = Path(context.operations.plan_items(plan_id)[0].source_path)

    report = context.organisation.execute(plan_id, require_approval=False)

    assert report.completed
    assert not source.is_file()


def test_execute_refuses_source_changed_since_scan(context, analysed_library) -> None:
    plan_id = _approved_plan(context, analysed_library)
    source = Path(context.operations.plan_items(plan_id)[0].source_path)
    source.write_text("changed since scan", encoding="utf-8")

    with pytest.raises(InvalidRecommendationError, match="changed since it was scanned"):
        context.organisation.execute(plan_id)

    assert source.is_file()
    assert context.organisation.plan(plan_id)["status"] == PlanStatus.APPROVED.value
    assert context.recovery.history() == []


def test_execute_reports_filtered_conflicts_as_skipped(context, analysed_library) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    blocker = Path(item.destination_path)
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("occupied", encoding="utf-8")
    context.operations.update_item_conflict(item.id, "destination is occupied")

    report = context.organisation.execute(plan_id)

    assert any(
        result.file_id == item.file_id and result.message.startswith("Skipped")
        for result in report.skipped
    )
    assert blocker.read_text(encoding="utf-8") == "occupied"


def test_execute_catches_same_size_content_change_without_preflight_hash(
    context, analysed_library
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    source = Path(item.source_path)
    original = source.read_bytes()
    source.write_bytes(b"!" * len(original))
    assert source.read_bytes() != original

    report = context.organisation.execute(plan_id)

    failed = [result for result in report.failed if result.file_id == item.file_id]
    assert len(failed) == 1
    assert source.read_bytes() == b"!" * len(original)
    assert all(op.file_id != item.file_id for op in context.recovery.history())


def test_batch_rollback_invalidates_completed_operations(
    context, analysed_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    originals = [Path(item.source_path) for item in context.operations.plan_items(plan_id)]
    real_move = org_service.move_no_overwrite
    calls: list[Path] = []

    def failing_move(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(source))
        if len(calls) == 4:
            raise OSError("injected second-item failure")
        return real_move(source, destination, *args, **kwargs)

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", failing_move)
    result = context.organisation.execute_batch(plan_id)

    assert result.state == "FAILED"
    assert all(path.is_file() for path in originals)
    undoable_ids = {operation.id for operation in context.recovery.undoable()}
    assert all(operation_id not in undoable_ids for operation_id in result.operation_ids)


def test_batch_rollback_marks_held_item_operation_rolled_back(
    context, analysed_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    originals = [Path(item.source_path) for item in context.operations.plan_items(plan_id)]
    real_move = org_service.move_no_overwrite
    calls: list[Path] = []

    def failing_move(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(source))
        if len(calls) == 4:
            raise OSError("injected second-item failure")
        return real_move(source, destination, *args, **kwargs)

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", failing_move)
    monkeypatch.setattr(context.operations, "fail_operation", lambda *_a, **_k: None)

    result = context.organisation.execute_batch(plan_id)

    assert result.state == "FAILED"
    assert all(path.is_file() for path in originals)
    assert {op.status for op in context.recovery.history()} == {"rolled_back"}


def test_undo_treats_case_only_paths_as_same_physical_file(
    context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    posix_like = types.SimpleNamespace(
        path=types.SimpleNamespace(
            normcase=lambda value: value, abspath=os.path.abspath, samefile=os.path.samefile
        ),
        makedirs=os.makedirs,
    )
    monkeypatch.setattr("app.organisation.recovery.os", posix_like)

    result = context.recovery.undo(operation.id)

    assert result.success is True
    assert "beta.txt" in {item.name for item in paths["beta"].parent.iterdir()}


def test_case_only_rename_rolls_back_on_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not _case_insensitive(tmp_path):
        pytest.skip("requires a case-insensitive filesystem")

    source = tmp_path / "beta.txt"
    source.write_text("precious content", encoding="utf-8")
    destination = tmp_path / "Beta.txt"
    monkeypatch.setattr(
        "app.organisation.fsops.verify_destination", lambda *_a, **_k: (False, "hash mismatch")
    )

    with pytest.raises(HashMismatchError):
        _rename_case_only(source, destination, expected_hash=sha256_file(source))

    assert source.read_text(encoding="utf-8") == "precious content"
    names = {item.name for item in tmp_path.iterdir()}
    assert "beta.txt" in names and "Beta.txt" not in names
    assert list(tmp_path.glob(".opencoeus-*")) == []


def _stranded_batch(context, analysed_library, *, outcome: str) -> tuple[int, object]:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    batch_id = context.batches.create(plan_id, context.config.data_dir / "holding")
    original = Path(item.source_path)
    held = context.config.data_dir / "holding" / f"batch-{batch_id}" / "held.txt"
    final = Path(item.destination_path)
    held.parent.mkdir(parents=True, exist_ok=True)

    if outcome == "final":
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text("organised", encoding="utf-8")
        original.unlink()
    elif outcome == "original":
        pass
    else:
        original.unlink()

    context.batches.record_item(batch_id, item.file_id, original, held, final)
    context.batches.set_item_state(batch_id, item.file_id, "HELD")
    context.batches.set_state(batch_id, "HELD")
    return batch_id, item


def test_cleanup_reconciles_crash_after_final_move(context, analysed_library) -> None:
    batch_id, _item = _stranded_batch(context, analysed_library, outcome="final")
    cleanup_stale_batches(context.db)
    assert context.batches.items_for_batch(batch_id)[0].state == "COMPLETED"


def test_cleanup_keeps_item_held_when_holding_file_still_exists(
    context, analysed_library
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    batch_id = context.batches.create(plan_id, context.config.data_dir / "holding")
    original = Path(item.source_path)
    held = context.config.data_dir / "holding" / f"batch-{batch_id}" / "held.txt"
    final = Path(item.destination_path)
    held.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    held.write_text("still staged", encoding="utf-8")
    final.write_text("stale final", encoding="utf-8")
    original.unlink()

    context.batches.record_item(batch_id, item.file_id, original, held, final)
    context.batches.set_item_state(batch_id, item.file_id, "HELD")
    context.batches.set_state(batch_id, "HELD")

    cleanup_stale_batches(context.db)
    assert context.batches.items_for_batch(batch_id)[0].state == "HELD"


def test_cleanup_reconciles_already_restored_item(context, analysed_library) -> None:
    batch_id, _item = _stranded_batch(context, analysed_library, outcome="original")
    cleanup_stale_batches(context.db)
    assert context.batches.items_for_batch(batch_id)[0].state == "ROLLED_BACK"


def test_cleanup_marks_unlocatable_item_unavailable(context, analysed_library) -> None:
    batch_id, _item = _stranded_batch(context, analysed_library, outcome="gone")
    cleanup_stale_batches(context.db)
    assert context.batches.items_for_batch(batch_id)[0].state == "UNAVAILABLE"


def test_batch_retry_moves_from_held_path(
    context, analysed_library, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    original = Path(item.source_path)
    held = context.config.data_dir / "holding" / "manual" / "held.txt"
    held.parent.mkdir(parents=True, exist_ok=True)
    original.rename(held)

    batch_id = context.batches.create(plan_id, context.config.data_dir / "holding")
    context.batches.record_item(batch_id, item.file_id, original, held, Path(item.destination_path))
    context.batches.set_item_state(batch_id, item.file_id, "HELD")
    context.batches.set_state(batch_id, "HELD")
    context.operations.update_plan_status(plan_id, PlanStatus.FAILED)
    context.organisation.revalidate(plan_id)
    context.organisation.approve(plan_id)

    real_move = org_service.move_no_overwrite
    sources: list[Path] = []

    def spy(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        sources.append(Path(source))
        return real_move(source, destination, *args, **kwargs)

    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", spy)
    result = context.organisation.execute_batch(plan_id)

    assert result.state == "COMPLETED"
    assert held in sources
    assert not held.exists()
    assert Path(item.destination_path).is_file()
