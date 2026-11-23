"""End-to-end demo: scan → analyse → plan → approve → execute → search → undo."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import InvalidRecommendationError
from app.demo import create_sample_library
from app.services.context import AppContext


@pytest.fixture()
def demo_library(tmp_path: Path) -> Path:
    root = tmp_path / "OpenCoeus-Demo"
    created = create_sample_library(root)
    assert len(created) == 19
    return root


def test_demo_pipeline_end_to_end(context: AppContext, demo_library: Path) -> None:
    scan = context.scanning.scan(demo_library, include_unsupported=True)
    assert scan.total == 19
    assert scan.created == 19
    assert scan.unsupported == 1
    assert scan.failed == 0

    analysis = context.analysis.analyse_pending(use_llm=False)
    assert analysis.total == 18
    assert analysis.analysed == 18
    assert analysis.failed == 0
    assert analysis.pending_review >= 1

    groups = context.duplicates()
    assert len(groups) == 1
    assert groups[0].count == 2

    preview = context.organisation.build_preview()
    assert preview.considered == 18
    assert preview.draft.actions
    assert len(preview.draft.actions) >= 16
    assert preview.summary.conflicts >= 1
    assert preview.summary.renames >= 14

    plan_id = context.organisation.create_plan()
    assert plan_id > 0
    plan = context.organisation.plan(plan_id)
    assert plan["status"] == "draft"
    assert plan["root_path"] == str(demo_library.resolve())

    with pytest.raises(InvalidRecommendationError):
        context.organisation.execute(plan_id)

    context.organisation.approve(plan_id)
    report = context.organisation.execute(plan_id)

    assert report.completed
    assert report.failed == []
    assert report.skipped
    assert report.succeeded >= 15
    assert report.created_directories

    for operation in report.completed:
        assert operation.destination_path.exists()
        assert not operation.source_path.exists()
        assert operation.undoable is True

    blocked_sources = [
        item.source_path
        for item in context.organisation.items(plan_id)
        if item.conflict
    ]
    assert blocked_sources
    assert all(Path(source).exists() for source in blocked_sources)

    assert context.organisation.plan(plan_id)["status"] == "partially_completed"

    found = context.search.search("invoice", mode="hybrid", limit=10)
    assert found.hits
    assert any("Finance" in (hit.category or "") for hit in found.hits)
    assert any(Path(hit.path).exists() for hit in found.hits)

    undoable = context.recovery.undoable()
    assert undoable
    operation = undoable[0]
    restored = context.recovery.undo(operation.id)

    assert restored.success is True
    assert Path(operation.source_path).exists()
    assert not Path(operation.destination_path).exists()

    with pytest.raises(InvalidRecommendationError):
        context.organisation.execute(plan_id)
