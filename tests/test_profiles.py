"""Named scan profiles stay local, persistent and outside the analysis cache key."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.cli import main
from app.services.context import AppContext
from tests.conftest import write_text


def test_profile_crud_and_active(context: AppContext) -> None:
    profile_id = context.profiles.add("Docs", "/docs", ("Invoices",), ("Temp",), ("*.tmp",))
    assert [p.name for p in context.profiles.list()] == ["Docs"]

    context.profiles.set_active(profile_id)

    active = context.profiles.active()
    assert active is not None
    assert active.name == "Docs"
    assert active.included_folders == ("Invoices",)
    assert active.excluded_folders == ("Temp",)
    assert active.custom_patterns == ("*.tmp",)

    context.profiles.delete(profile_id)

    assert context.profiles.list() == []
    assert context.profiles.active() is None


def test_active_profile_survives_purge(context: AppContext) -> None:
    profile_id = context.profiles.add("Docs", "/docs", (), (), ())
    context.profiles.set_active(profile_id)

    context.db.purge_session_data()

    active = context.profiles.active()
    assert active is not None
    assert active.name == "Docs"


def test_profile_filters_are_applied_to_scan(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "lib"
    write_text(root / "skip.tmp", "x")
    write_text(root / "keep" / "keep.txt", "x")
    write_text(root / "drop" / "drop.txt", "x")
    profile_id = context.profiles.add("P", str(root), ("keep",), ("drop",), ("*.tmp",))
    context.profiles.set_active(profile_id)

    context.scanning.scan(root)

    names = [f.name for f in context.files.list_summaries()]
    assert "skip.tmp" not in names
    assert "keep.txt" in names
    assert "drop.txt" not in names


def test_profile_settings_do_not_change_cache_prefix(context: AppContext) -> None:
    before = context.analysis._cache_signature(use_llm=False)

    profile_id = context.profiles.add("P", "/docs", ("Invoices",), ("Temp",), ("*.tmp",))
    context.profiles.set_active(profile_id)

    assert context.analysis._cache_signature(use_llm=False) == before


def test_cli_profile_commands_add_list_apply_and_delete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data_dir = tmp_path / "data"
    root = tmp_path / "lib"
    root.mkdir()

    assert main(["--data-dir", str(data_dir), "profile", "add", "Docs", str(root)]) == 0
    assert main(["--data-dir", str(data_dir), "profile", "list"]) == 0
    assert "Docs" in capsys.readouterr().out
    assert main(["--data-dir", str(data_dir), "profile", "apply", "Docs"]) == 0

    ctx = AppContext.create(data_dir=data_dir, purge=False)
    try:
        active = ctx.profiles.active()
        assert active is not None
        assert active.name == "Docs"
    finally:
        ctx.close()

    assert main(["--data-dir", str(data_dir), "profile", "delete", "Docs", "--yes"]) == 0
    ctx = AppContext.create(data_dir=data_dir, purge=False)
    try:
        assert ctx.profiles.list() == []
        assert ctx.profiles.active() is None
    finally:
        ctx.close()


def test_cli_scan_uses_active_profile_root_without_positional_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    root = tmp_path / "lib"
    write_text(root / "Invoice.txt", "INVOICE 123")

    assert main(["--data-dir", str(data_dir), "profile", "add", "Docs", str(root)]) == 0
    assert main(["--data-dir", str(data_dir), "profile", "apply", "Docs"]) == 0
    assert main(["--data-dir", str(data_dir), "scan", "--no-hash"]) == 0

    ctx = AppContext.create(data_dir=data_dir, purge=False)
    try:
        assert [f.name for f in ctx.files.list_summaries()] == ["Invoice.txt"]
    finally:
        ctx.close()


def test_cli_scan_profile_option_overrides_active_profile(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    root = tmp_path / "lib"
    write_text(root / "first" / "first.txt", "x")
    write_text(root / "second" / "second.txt", "x")

    assert main(
        [
            "--data-dir", str(data_dir), "profile", "add", "First", str(root),
            "--include", "first",
        ]
    ) == 0
    assert main(
        [
            "--data-dir", str(data_dir), "profile", "add", "Second", str(root),
            "--include", "second",
        ]
    ) == 0
    assert main(["--data-dir", str(data_dir), "profile", "apply", "First"]) == 0
    assert main(
        ["--data-dir", str(data_dir), "scan", "--profile", "Second", "--no-hash", str(root)]
    ) == 0

    ctx = AppContext.create(data_dir=data_dir, purge=False)
    try:
        names = [f.name for f in ctx.files.list_summaries()]
        assert "second.txt" in names
        assert "first.txt" not in names
    finally:
        ctx.close()


def test_files_page_shows_active_profile_summary(context: AppContext) -> None:
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from app.ui.pages.files import FilesPage

    app = QApplication.instance() or QApplication([])
    assert app is not None
    profile_id = context.profiles.add("Docs", "/docs", ("Invoices",), (), ("*.tmp",))
    context.profiles.set_active(profile_id)

    page = FilesPage(context)
    try:
        text = page.profile_label.text()
        assert "Docs" in text
        assert "Invoices" in text
        assert "*.tmp" in text
    finally:
        page.deleteLater()
