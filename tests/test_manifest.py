"""Read-only CSV audit manifest export."""

from __future__ import annotations

from app.cli import main


def test_manifest_header_and_rows(context, analysed_library, tmp_path):
    output = tmp_path / "manifest.csv"
    assert main(["--data-dir", str(context.config.data_dir), "manifest", "--output", str(output)]) == 0
    lines = output.read_text().splitlines()
    assert lines[0] == "path,name,size_bytes,sha256,status,category,modified_at,last_planned_action,last_operation_status"
    assert len(lines) == 1 + len(context.files.list_summaries())


def test_manifest_does_not_mutate_db(context, analysed_library, tmp_path):
    before = context.files.stats()
    main(["--data-dir", str(context.config.data_dir), "manifest", "--output", str(tmp_path / "m.csv")])
    assert context.files.stats() == before
