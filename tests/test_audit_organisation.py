"""Regressions for organisation recovery, races, path validation and conflicts."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.domain.enums import ActionType, PlanStatus
from app.domain.models import PlannedAction
from app.infrastructure.models import PlanItem
from app.organisation.planner import PlanDraft
from app.processing.hashing import sha256_file as real_sha256
from tests.conftest import file_id_for
from tests.test_organisation import _rename_plan, _write
from tests.test_organisation_safety import _approved_plan


def _single_action_plan(context, root: Path) -> tuple[int, Path]:
    source = _write(root / "Downloads" / "a.txt", "alpha")
    context.scanning.scan(root)
    action = PlannedAction(
        file_id=file_id_for(context, source),
        action=ActionType.RENAME,
        source_path=source,
        destination_path=root / "Downloads" / "Alpha.txt",
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
    )
    plan_id = context.operations.create_plan(root, [action])
    context.organisation.approve(plan_id)
    return plan_id, source


def _tamper_destination(context, item, destination: Path) -> None:
    with context.db.session() as session:
        row = session.get(PlanItem, item.id)
        row.destination_path = str(destination)


def test_retry_after_interrupted_batch_uses_held_source(context, analysed_library) -> None:
    plan_id = _approved_plan(context, analysed_library)
    items = context.operations.plan_items(plan_id)
    held_item = items[0]
    for item in items[1:]:
        final = Path(item.destination_path)
        final.parent.mkdir(parents=True, exist_ok=True)
        Path(item.source_path).rename(final)
        context.operations.set_item_status(item.id, "completed")

    original = Path(held_item.source_path)
    held = context.config.data_dir / "holding" / "manual" / "held.txt"
    held.parent.mkdir(parents=True, exist_ok=True)
    original.rename(held)
    batch_id = context.batches.create(plan_id, context.config.data_dir / "holding")
    context.batches.record_item(
        batch_id, held_item.file_id, original, held, Path(held_item.destination_path)
    )
    context.batches.set_item_state(batch_id, held_item.file_id, "HELD")
    context.batches.set_state(batch_id, "HELD")
    context.operations.update_plan_status(plan_id, PlanStatus.REVALIDATION_REQUIRED)

    context.organisation.revalidate(plan_id)
    assert context.batches.get(batch_id).state == "HELD"
    assert held.is_file()

    context.organisation.approve(plan_id)
    report = context.organisation.execute(plan_id)

    assert report.failed == []
    assert len(report.completed) == 1
    assert not held.exists()
    assert Path(held_item.destination_path).is_file()
    assert context.batches.get(batch_id).state == "HELD"


def test_concurrent_execute_records_single_operation(
    context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    source = _write(root / "a.txt", "alpha")
    context.scanning.scan(root)
    action = PlannedAction(
        file_id=file_id_for(context, source),
        action=ActionType.RENAME,
        source_path=source,
        destination_path=root / "Alpha.txt",
        original_name="a.txt",
        new_name="Alpha.txt",
        confidence=0.9,
    )
    started = threading.Event()
    release = threading.Event()
    hashes: list[Path] = []

    def blocking_hash(path: Path) -> str:
        if Path(path) == source:
            hashes.append(Path(path))
            if len(hashes) == 1:
                started.set()
                assert release.wait(5)
        return real_sha256(path)

    monkeypatch.setattr("app.organisation.executor.sha256_file", blocking_hash)
    reports: list[object] = []

    def run() -> None:
        reports.append(context.executor.execute(root, [action]))

    first = threading.Thread(target=run)
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=run)
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert len(hashes) == 1
    assert sum(len(report.completed) for report in reports) == 1  # type: ignore[attr-defined]
    assert len(context.recovery.history()) == 1


def test_concurrent_undo_hashes_once(
    context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    plan_id, _ = _rename_plan(context, root)
    context.organisation.execute(plan_id)
    operation = context.recovery.history()[0]
    started = threading.Event()
    release = threading.Event()
    hashes: list[Path] = []

    def blocking_hash(path: Path) -> str:
        hashes.append(Path(path))
        if len(hashes) == 1:
            started.set()
            assert release.wait(5)
        return real_sha256(path)

    monkeypatch.setattr("app.organisation.recovery.sha256_file", blocking_hash)
    results: list[bool] = []
    errors: list[Exception] = []

    def run() -> None:
        try:
            results.append(context.recovery.undo(operation.id).success)
        except Exception as exc:  # noqa: BLE001 - concurrency outcome under test
            errors.append(exc)

    first = threading.Thread(target=run)
    first.start()
    assert started.wait(5)
    second = threading.Thread(target=run)
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert len(hashes) == 1
    assert results == [True]
    assert len(errors) == 1


@pytest.mark.parametrize("escape", ["absolute", "traversal"])
def test_execute_rejects_destination_outside_root_before_writing(
    context, analysed_library, tmp_path: Path, escape: str
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    root = Path(item.destination_path).parents[1]
    outside = tmp_path / "escape" / "pwned.txt"
    destination = outside if escape == "absolute" else root / ".." / "escape" / "pwned.txt"
    _tamper_destination(context, item, destination)

    with pytest.raises(Exception, match="organisation root|escape"):
        context.organisation.execute(plan_id)

    assert not outside.parent.exists()
    assert Path(item.source_path).is_file()


@pytest.mark.parametrize("escape", ["absolute", "traversal"])
def test_batch_rejects_destination_outside_root_before_writing(
    context, analysed_library, tmp_path: Path, escape: str
) -> None:
    plan_id = _approved_plan(context, analysed_library)
    item = context.operations.plan_items(plan_id)[0]
    root = Path(item.destination_path).parents[1]
    outside = tmp_path / "escape" / "pwned.txt"
    destination = outside if escape == "absolute" else root / ".." / "escape" / "pwned.txt"
    _tamper_destination(context, item, destination)

    with pytest.raises(Exception, match="organisation root|escape"):
        context.organisation.execute_batch(plan_id)

    assert not outside.parent.exists()
    assert Path(item.source_path).is_file()


def test_revalidate_clears_stale_conflict_on_completed_item(context, tmp_path: Path) -> None:
    root = tmp_path / "library"
    plan_id, source = _single_action_plan(context, root)
    context.organisation.execute(plan_id)
    item = context.operations.plan_items(plan_id)[0]
    assert item.status == "completed"

    with context.db.session() as session:
        row = session.get(PlanItem, item.id)
        row.conflict = "stale conflict"
    context.operations.update_plan_status(plan_id, PlanStatus.FAILED)

    summary = context.organisation.revalidate(plan_id)

    assert summary.conflicts == 0
    assert context.operations.plan_items(plan_id)[0].conflict is None
    assert source.is_file() is False


def test_plan_summary_ignores_conflict_on_unchanged_action(tmp_path: Path) -> None:
    path = _write(tmp_path / "library" / "a.txt", "alpha")
    draft = PlanDraft(
        root=tmp_path / "library",
        actions=[
            PlannedAction(
                file_id=1,
                action=ActionType.RENAME,
                source_path=path,
                destination_path=path,
                original_name="a.txt",
                new_name="a.txt",
                confidence=0.9,
                conflict="stale conflict",
            )
        ],
    )

    assert draft.summary.conflicts == 0
