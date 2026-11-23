"""Destructive CLI commands need an explicit confirmation or --yes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cli


@pytest.fixture()
def answer_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")


def test_cli_undo_requires_confirmation_without_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer_no: None, capsys
) -> None:
    undone: list[int] = []

    class FakeRecovery:
        @staticmethod
        def undo(operation_id: int):
            undone.append(operation_id)
            return SimpleNamespace(message="Operation undone.")

    class FakeContext:
        recovery = FakeRecovery()

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(cli.AppContext, "create", lambda *_args, **_kwargs: FakeContext())

    assert cli.main(["--data-dir", str(tmp_path / "data"), "undo", "7"]) == 1

    assert undone == []
    assert "Aborted" in capsys.readouterr().out


def test_cli_undo_yes_skips_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    undone: list[int] = []

    class FakeRecovery:
        @staticmethod
        def undo(operation_id: int):
            undone.append(operation_id)
            return SimpleNamespace(message="Operation undone.")

    class FakeContext:
        recovery = FakeRecovery()

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(cli.AppContext, "create", lambda *_args, **_kwargs: FakeContext())

    assert cli.main(["--data-dir", str(tmp_path / "data"), "undo", "7", "--yes"]) == 0

    assert undone == [7]


def test_cli_profile_delete_requires_confirmation_without_yes(
    answer_no: None, capsys
) -> None:
    deleted: list[int] = []

    class FakeProfiles:
        @staticmethod
        def get_by_name(name: str):
            return SimpleNamespace(id=3, name=name)

        @staticmethod
        def delete(profile_id: int) -> None:
            deleted.append(profile_id)

    args = cli.build_parser().parse_args(["profile", "delete", "demo"])
    ctx = SimpleNamespace(profiles=FakeProfiles())

    assert cli.cmd_profile(args, ctx) == 1  # type: ignore[arg-type]

    assert deleted == []
    assert "Aborted" in capsys.readouterr().out


def test_cli_profile_delete_yes_skips_confirmation(capsys) -> None:
    deleted: list[int] = []

    class FakeProfiles:
        @staticmethod
        def get_by_name(name: str):
            return SimpleNamespace(id=3, name=name)

        @staticmethod
        def delete(profile_id: int) -> None:
            deleted.append(profile_id)

    args = cli.build_parser().parse_args(["profile", "delete", "demo", "--yes"])
    ctx = SimpleNamespace(profiles=FakeProfiles())

    assert cli.cmd_profile(args, ctx) == 0  # type: ignore[arg-type]

    assert deleted == [3]
    assert "Profile demo deleted." in capsys.readouterr().out


def test_cli_manifest_refuses_to_overwrite_without_yes(tmp_path: Path, capsys) -> None:
    output = tmp_path / "manifest.csv"
    output.write_text("keep me", encoding="utf-8")
    args = cli.build_parser().parse_args(["manifest", "--output", str(output)])

    class FakeFiles:
        @staticmethod
        def manifest_rows() -> list[object]:
            return []

    assert cli.cmd_manifest(args, SimpleNamespace(files=FakeFiles())) == 1  # type: ignore[arg-type]

    assert output.read_text(encoding="utf-8") == "keep me"
    assert "already exists" in capsys.readouterr().err


def test_cli_manifest_refuses_file_created_during_row_collection(tmp_path: Path, capsys) -> None:
    output = tmp_path / "manifest.csv"
    args = cli.build_parser().parse_args(["manifest", "--output", str(output)])

    class FakeFiles:
        @staticmethod
        def manifest_rows() -> list[object]:
            output.write_text("raced", encoding="utf-8")
            return []

    assert cli.cmd_manifest(args, SimpleNamespace(files=FakeFiles())) == 1  # type: ignore[arg-type]

    assert output.read_text(encoding="utf-8") == "raced"
    assert "already exists" in capsys.readouterr().err


def test_cli_manifest_yes_overwrites_existing_output(tmp_path: Path, capsys) -> None:
    output = tmp_path / "manifest.csv"
    output.write_text("old", encoding="utf-8")
    args = cli.build_parser().parse_args(["manifest", "--output", str(output), "--yes"])

    class FakeFiles:
        @staticmethod
        def manifest_rows() -> list[object]:
            return []

    assert cli.cmd_manifest(args, SimpleNamespace(files=FakeFiles())) == 0  # type: ignore[arg-type]

    assert "path,name" in output.read_text(encoding="utf-8")
    assert "Wrote 0 row(s)" in capsys.readouterr().out
