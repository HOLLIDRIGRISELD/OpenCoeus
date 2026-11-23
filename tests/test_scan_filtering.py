"""Scan-time filtering that must happen before any file content is read."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.processing.scanner as scanner_module
from app.services.context import AppContext
from tests.conftest import write_text

BLOAT = ("money.exe", "bundle.min.js", "package-lock.json", "clip.mp4", "raw.rand")


def test_binary_bloat_never_reaches_file_description(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    write_text(root / "invoice.txt", "INVOICE\nAmount due: 10.00")
    for name in BLOAT:
        write_text(root / name, "ordinary text")

    described: list[str] = []
    real_describe = scanner_module.describe_file

    def spy(path: Path, **kwargs: object):  # type: ignore[no-untyped-def]
        described.append(path.name)
        return real_describe(path, **kwargs)

    monkeypatch.setattr(scanner_module, "describe_file", spy)

    report = context.scanning.scan(root, include_unsupported=False)

    assert report.discovered == 1
    assert described == ["invoice.txt"]


def test_excluded_directory_names_are_case_insensitive(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    write_text(root / ".GIT" / "config", "index payload")
    write_text(root / "docs" / "notes.txt", "INVOICE\nAmount due: 10.00")

    report = context.scanning.scan(root, include_unsupported=False)

    assert report.discovered == 1
    assert context.files.find_by_path(root / ".GIT" / "config") is None


def test_content_detected_document_is_not_filtered_by_its_extension(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    pdf = fitz_pdf(root / "report.dat")
    write_text(root / "notes.txt", "ordinary words")

    report = context.scanning.scan(root, include_unsupported=False)

    assert report.discovered == 2
    assert context.files.find_by_path(pdf) is not None


def fitz_pdf(path: Path) -> Path:
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((24, 48), "INVOICE\nInvoice number: INV-7\nAmount due: 7.00")
    document.save(path)
    document.close()
    return path


def test_scan_without_a_listener_does_not_build_progress_events(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    write_text(root / "notes.txt", "ordinary words")

    def no_events(*args: object, **kwargs: object) -> None:
        raise AssertionError("progress event built without a listener")

    monkeypatch.setattr(scanner_module, "ScanProgress", no_events)

    context.scanning.scan(root)


def test_os_junk_names_never_reach_file_description(
    context: AppContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "lib"
    for name in ("thumbs.db", "desktop.ini", ".DS_Store"):
        write_text(root / name, "junk")
    described: list[str] = []
    real_describe = scanner_module.describe_file

    def spy(path: Path, **kwargs: object):  # type: ignore[no-untyped-def]
        described.append(path.name)
        return real_describe(path, **kwargs)

    monkeypatch.setattr(scanner_module, "describe_file", spy)

    context.scanning.scan(root, include_unsupported=False)

    assert described == []


def test_appledouble_prefix_is_skipped(context: AppContext, tmp_path: Path) -> None:
    root = tmp_path / "lib"
    path = write_text(root / "._report.pdf", "resource fork")

    context.scanning.scan(root, include_unsupported=False)

    assert context.files.find_by_path(path) is None


def test_custom_pattern_excludes_file_and_directory(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    write_text(root / "secret.tmp", "x")
    write_text(root / "private" / "keep.txt", "x")

    found = scanner_module.FileScanner(
        scanner_module.ScanOptions(custom_patterns=("*.tmp", "private"))
    ).scan(root)

    assert all("secret.tmp" not in str(f.path) and "private" not in str(f.path) for f in found)


def test_included_folders_allowlist(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    write_text(root / "notes.txt", "x")
    write_text(root / "keep" / "keep.txt", "x")
    write_text(root / "drop" / "drop.txt", "x")

    found = scanner_module.FileScanner(
        scanner_module.ScanOptions(included_folders=("keep",))
    ).scan(root)

    assert any("keep.txt" in str(f.path) for f in found)
    assert not any("drop.txt" in str(f.path) for f in found)
