"""Typed settings validation and live reconfiguration."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.repositories.settings import SettingsRepository
from app.services.context import AppContext
from app.services.settings_service import SettingsService


def test_settings_snapshot_contains_documented_defaults(context: AppContext) -> None:
    snapshot = context.settings.snapshot()

    assert snapshot["app.naming_template"] == "{title}"
    assert snapshot["search.alpha"] == 0.4
    assert snapshot["search.beta"] == 0.6
    assert snapshot["organisation.root"] == ""
    assert snapshot["app.enable_llm"] is False
    assert snapshot["app.prefer_transformer"] is False


def test_valid_settings_update_is_persisted_and_applied(context: AppContext) -> None:
    problems = context.settings.update(
        {
            "app.naming_template": "{date}_{title}",
            "app.low_confidence": 0.5,
            "app.high_confidence": 0.9,
            "search.alpha": 0.3,
            "search.beta": 0.7,
            "app.scan_batch_size": 10,
            "app.max_file_size_mb": 50,
            "app.enable_llm": True,
        }
    )

    assert problems == []
    snapshot = context.settings.snapshot()
    assert snapshot["app.naming_template"] == "{date}_{title}"
    assert snapshot["app.low_confidence"] == 0.5
    assert snapshot["app.high_confidence"] == 0.9
    assert snapshot["search.alpha"] == 0.3
    assert snapshot["search.beta"] == 0.7
    assert snapshot["app.scan_batch_size"] == 10
    assert snapshot["app.max_file_size_mb"] == 50
    assert snapshot["app.enable_llm"] is True

    assert context.config.naming_template == "{date}_{title}"
    assert context.config.max_file_size_mb == 50
    assert context.config.enable_llm is True


def test_invalid_settings_reject_the_whole_update(context: AppContext) -> None:
    before = context.settings.snapshot()

    problems = context.settings.update(
        {
            "app.naming_template": "no placeholder",
            "app.low_confidence": 0.95,
            "app.high_confidence": 0.85,
            "search.alpha": 1.5,
            "does_not_exist": "value",
            "app.scan_batch_size": 0,
        }
    )

    assert len(problems) >= 5
    assert context.settings.snapshot() == before


def test_tiny_search_weight_survives_persistence(context: AppContext) -> None:
    assert context.settings.update({"search.alpha": 0.00001, "search.beta": 0.0}) == []

    stored = SettingsRepository(context.db).get("search.alpha")
    assert stored is not None and float(stored) > 0

    restarted = SettingsService(SettingsRepository(context.db), context.config)
    assert restarted.search_alpha == pytest.approx(0.00001)


def test_settings_reject_unparseable_booleans_and_weights(context: AppContext) -> None:
    assert context.settings.update({"app.enable_llm": "perhaps"})
    assert context.settings.update({"search.alpha": 0.0, "search.beta": 0.0})
    assert context.settings.snapshot()["app.enable_llm"] is False


def test_apply_settings_rebuilds_model_dependent_services(context: AppContext) -> None:
    classifier_before = context.classifier()
    embeddings_before = context.embeddings

    problems = context.apply_settings(
        {
            "app.naming_template": "{category}_{title}",
            "search.alpha": 0.5,
            "search.beta": 0.5,
            "app.prefer_transformer": False,
        }
    )

    assert problems == []
    assert context.embeddings is not embeddings_before
    assert context.classifier() is not classifier_before
    assert context.settings.naming_template == "{category}_{title}"
    assert context.search._hybrid.alpha == 0.5


def test_apply_settings_with_problems_changes_nothing(context: AppContext) -> None:
    classifier_before = context.classifier()

    problems = context.apply_settings({"app.naming_template": "invalid"})

    assert problems
    assert context.classifier() is classifier_before
    assert context.settings.naming_template == "{title}"


def test_settings_reject_non_loopback_llm_url(context: AppContext) -> None:
    before = context.settings.snapshot()

    problems = context.settings.update({"llm.base_url": "http://example.com:11434"})

    assert problems and "llm.base_url" in problems[0]
    assert context.settings.snapshot() == before


def test_settings_accept_loopback_llm_url(context: AppContext) -> None:
    problems = context.settings.update({"llm.base_url": "http://localhost:11434"})

    assert problems == []
    assert context.config.llm_base_url == "http://localhost:11434"


def test_settings_reject_invalid_organisation_roots(
    context: AppContext, tmp_path: Path
) -> None:
    before = context.settings.snapshot()
    existing = tmp_path / "library"
    existing.mkdir()

    for raw in (
        str(tmp_path / "missing"),
        "relative/library",
        str(existing / ".." / "elsewhere"),
        str(existing / "sub" / ".."),
    ):
        problems = context.settings.update({"organisation.root": raw})
        assert problems and "organisation.root" in problems[0], raw
        assert context.settings.snapshot() == before, raw


def test_settings_accept_existing_organisation_root(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir()

    problems = context.settings.update({"organisation.root": str(root)})

    assert problems == []
    assert context.settings.organisation_root == root.resolve()


def test_settings_clear_organisation_root_with_none(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    assert context.settings.update({"organisation.root": str(root)}) == []

    problems = context.settings.update({"organisation.root": None})

    assert problems == []
    assert context.settings.organisation_root is None


def test_settings_clear_organisation_root_with_empty_string(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    assert context.settings.update({"organisation.root": str(root)}) == []

    problems = context.settings.update({"organisation.root": ""})

    assert problems == []
    assert context.settings.organisation_root is None


def test_organisation_root_round_trip(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()

    context.set_organisation_root(root)
    assert context.settings.organisation_root == root.resolve()
    assert context.organisation.organisation_root() == root.resolve()

    context.set_organisation_root(None)
    assert context.settings.organisation_root is None
