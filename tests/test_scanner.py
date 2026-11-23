"""Recursive scanner and the scanning service."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core.exceptions import FileAccessError
from app.processing.scanner import FileScanner, ScanCancelled, ScanOptions
from app.services.context import AppContext


def _touch(path: Path, content: str = "text") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_scanner_finds_nested_supported_files_and_skips_excluded(tmp_path: Path) -> None:
    _touch(tmp_path / "a.txt")
    _touch(tmp_path / "nested" / "b.md")
    _touch(tmp_path / ".git" / "config")
    _touch(tmp_path / "node_modules" / "package.json")

    options = ScanOptions(
        supported_extensions={".txt", ".md"},
        include_unsupported=False,
    )
    found = [item.relative_path.as_posix() for item in FileScanner(options).scan(tmp_path)]

    assert found == ["a.txt", "nested/b.md"]


def test_scanner_non_recursive_and_file_limit(tmp_path: Path) -> None:
    for name in ("one.txt", "two.txt", "three.txt"):
        _touch(tmp_path / name)
    _touch(tmp_path / "nested" / "four.txt")

    options = ScanOptions(supported_extensions={".txt"}, recursive=False)
    assert len(list(FileScanner(options).scan(tmp_path))) == 3

    limited = ScanOptions(supported_extensions={".txt"}, max_files=2)
    assert len(list(FileScanner(limited).scan(tmp_path))) == 2


def test_scanner_can_include_unsupported_files(tmp_path: Path) -> None:
    _touch(tmp_path / "notes.txt")
    (tmp_path / "archive.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    supported = list(
        FileScanner(
            ScanOptions(supported_extensions={".txt"}, include_unsupported=False)
        ).scan(tmp_path)
    )
    everything = list(
        FileScanner(
            ScanOptions(supported_extensions={".txt"}, include_unsupported=True)
        ).scan(tmp_path)
    )

    assert [item.filename for item in supported] == ["notes.txt"]
    assert {item.filename for item in everything} == {"archive.zip", "notes.txt"}
    assert next(item for item in everything if item.filename == "archive.zip").supported is False


def test_scanner_cancellation(tmp_path: Path) -> None:
    _touch(tmp_path / "one.txt")
    event = threading.Event()
    event.set()

    with pytest.raises(ScanCancelled):
        list(FileScanner(ScanOptions(supported_extensions={".txt"})).scan(tmp_path, cancel_event=event))


def test_scanner_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileAccessError):
        list(FileScanner().scan(tmp_path / "missing"))


def test_scanning_service_registers_hashes_and_sets_root(
    context: AppContext, sample_library: Path
) -> None:
    report = context.scanning.scan(sample_library)

    assert report.total == 4
    assert report.created == 4
    assert report.updated == 0
    assert report.hashed == 4
    assert report.failed == 0
    assert report.cancelled is False
    assert report.session_id > 0
    assert context.settings.organisation_root == sample_library.resolve()

    summaries = context.files.list_summaries()
    assert len(summaries) == 4
    assert all(summary.status == "discovered" for summary in summaries)
    assert all(len(summary.path) > 0 for summary in summaries)

    records = [context.files.get_record(summary.id) for summary in summaries]
    assert all(record is not None and len(str(record["hash"])) == 64 for record in records)

    sessions = context.sessions.recent()
    assert sessions[0]["status"] == "completed"
    assert sessions[0]["discovered"] == 4


def test_scanning_service_rescan_updates_without_duplicates(
    context: AppContext, sample_library: Path
) -> None:
    first = context.scanning.scan(sample_library)
    second = context.scanning.scan(sample_library)

    assert first.created == 4
    assert second.created == 0
    assert second.updated == 4
    assert len(context.files.list_summaries()) == 4


def test_scanning_service_marks_unsupported_files(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "mixed"
    _touch(root / "notes.txt")
    (root / "archive.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    report = context.scanning.scan(root, include_unsupported=True)

    assert report.total == 2
    assert report.unsupported == 1
    statuses = context.files.counts()
    assert statuses["unsupported"] == 1
    assert statuses["discovered"] == 1
