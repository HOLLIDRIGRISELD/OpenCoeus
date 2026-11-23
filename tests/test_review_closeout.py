"""Regression tests for independent-review findings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import AppConfig
from app.domain.models import NamingSuggestion
from app.infrastructure.repositories.batches import cleanup_stale_batches
from app.services import organisation_service as org_service
from app.services.context import AppContext
from tests.conftest import file_id_for


def _approved_plan(context, analysed_library) -> int:  # type: ignore[no-untyped-def]
    plan_id = context.organisation.create_plan()
    context.organisation.approve(plan_id)
    return plan_id


def test_explicit_dir_beats_config_json_data_dir(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit"
    other = tmp_path / "other"
    explicit.mkdir()
    (explicit / "config.json").write_text(
        json.dumps({"data_dir": str(other)}), encoding="utf-8"
    )

    assert AppConfig.load(explicit).data_dir == explicit


def test_env_dir_beats_config_json_data_dir(tmp_path: Path, monkeypatch) -> None:
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    other = tmp_path / "other"
    (env_dir / "config.json").write_text(
        json.dumps({"data_dir": str(other)}), encoding="utf-8"
    )
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(env_dir))

    assert AppConfig.load().data_dir == env_dir


def test_holding_dir_lives_under_data_dir(context, analysed_library) -> None:  # type: ignore[no-untyped-def]
    plan_id = _approved_plan(context, analysed_library)
    real_move = org_service.move_no_overwrite
    calls: list[Path] = []

    def failing_move(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(Path(source))
        if len(calls) == 2:
            raise OSError("injected failure")
        return real_move(source, destination, *args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.services.organisation_service.move_no_overwrite", failing_move)
    try:
        result = context.organisation.execute_batch(plan_id)
    finally:
        monkeypatch.undo()

    assert result.state == "FAILED"
    batch = context.batches.unfinished()[0]
    assert context.config.data_dir in batch.holding_dir.parents
    assert analysed_library not in batch.holding_dir.parents


def test_second_item_failure_restores_completed_item(context, analysed_library, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan_id = _approved_plan(context, analysed_library)
    sources = [Path(item.source_path) for item in context.operations.plan_items(plan_id)]
    assert len(sources) >= 2

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
    assert len(calls) >= 4
    assert all(path.is_file() for path in sources)
    assert all(context.files.find_by_path(path) is not None for path in sources)


def test_occupied_original_logs_warning_and_stays_held(context, analysed_library, caplog) -> None:  # type: ignore[no-untyped-def]
    plan_id = _approved_plan(context, analysed_library)
    source = Path(context.operations.plan_items(plan_id)[0].source_path)
    file_id = file_id_for(context, source)
    batch_id = context.batches.create(plan_id, context.config.data_dir / "holding")
    held = context.config.data_dir / "holding" / f"batch-{batch_id}" / "held.txt"
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_text("held", encoding="utf-8")
    source.write_text("new owner", encoding="utf-8")
    context.batches.record_item(batch_id, file_id, source, held, Path("final.txt"))
    context.batches.set_item_state(batch_id, file_id, "HELD")
    context.batches.set_state(batch_id, "HELD")

    with caplog.at_level("WARNING"):
        cleanup_stale_batches(context.db)

    assert "occupied" in caplog.text
    assert held.is_file()
    assert context.batches.held_items(batch_id=batch_id)


def test_startup_purge_keeps_stranded_batch_rows(config) -> None:  # type: ignore[no-untyped-def]
    first = AppContext(config, purge=False)
    try:
        root = config.data_dir.parent / "library"
        source = root / "a.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("invoice totals invoice totals", encoding="utf-8")
        first.scanning.scan(root)
        first.analysis.analyse_pending(use_llm=False)
        file_id = first.files.find_by_path(source)
        assert file_id is not None
        plan_id = first.organisation.create_plan()
        batch_id = first.batches.create(plan_id, config.data_dir / "holding")
        held = config.data_dir / "holding" / f"batch-{batch_id}" / "a.txt"
        held.parent.mkdir(parents=True, exist_ok=True)
        held.write_text("held", encoding="utf-8")
        source.write_text("new owner", encoding="utf-8")
        first.batches.record_item(batch_id, file_id, source, held, root / "final.txt")
        first.batches.set_item_state(batch_id, file_id, "HELD")
        first.batches.set_state(batch_id, "HELD")
    finally:
        first.close()

    second = AppContext(config, purge=True)
    try:
        assert second.batches.unfinished()
        assert second.batches.held_items()
    finally:
        second.close()


def test_convention_sequence_is_reserved_within_run(context) -> None:  # type: ignore[no-untyped-def]
    context.settings.update({"naming.use_conventions": True})
    reserved: set[str] = set()
    suggestion = NamingSuggestion(
        original_name="report.txt",
        suggested_name="Report-01.txt",
        confidence=0.7,
        explanation="template",
        template="{title}",
    )
    existing = ["2026-Report-01", "2026-Report-02"]

    first = context.analysis._apply_naming_conventions(suggestion, existing, reserved)
    second = context.analysis._apply_naming_conventions(suggestion, existing, reserved)

    assert first.suggested_name == "2026 Report 03.txt"
    assert second.suggested_name == "2026 Report 04.txt"


def test_analyse_pending_shares_reservation_set(context, analysed_library, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[object] = []
    original = context.analysis.analyse_file

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs.get("reserved_names"))
        return original(*args, **kwargs)

    monkeypatch.setattr(context.analysis, "analyse_file", spy)
    context.analysis.analyse_pending(use_llm=False, force=True)

    assert seen
    assert all(item is seen[0] for item in seen)
    assert isinstance(seen[0], set)
