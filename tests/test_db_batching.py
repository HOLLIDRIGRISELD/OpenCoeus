"""Transaction counts for scan and analysis batches."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sqlalchemy import event

from app.services.context import AppContext
from tests.conftest import write_text


def _library(root: Path, count: int) -> None:
    for index in range(count):
        write_text(
            root / f"invoice_{index:02d}.txt",
            f"INVOICE\nInvoice number: INV-{index}\nAmount due: {index}.00\n",
        )


def _count_commits(db, callback):  # type: ignore[no-untyped-def]
    commits = [0]

    def on_commit(_connection) -> None:  # type: ignore[no-untyped-def]
        commits[0] += 1

    event.listen(db.engine, "commit", on_commit)
    try:
        callback()
    finally:
        event.remove(db.engine, "commit", on_commit)
    return commits[0]


def test_scan_registers_a_batch_in_one_transaction(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    _library(root, 12)

    commits = _count_commits(context.db, lambda: context.scanning.scan(root))

    assert commits <= 8


def test_embedding_write_does_not_reload_chunk_text(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    _library(root, 1)
    context.scanning.scan(root)
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.analysed == 1

    statements: list[str] = []

    def on_statement(_conn, cursor, statement, _parameters, _context, _many):  # type: ignore[no-untyped-def]
        statements.append(statement)

    event.listen(context.db.engine, "before_cursor_execute", on_statement)
    try:
        context.analyses.save_embeddings(
            context.files.find_by_path(root / "invoice_00.txt"),
            context.embeddings.model_name,
            [np.zeros(context.embeddings.dimension, dtype=np.float32)],
        )
    finally:
        event.remove(context.db.engine, "before_cursor_execute", on_statement)

    assert not any("document_chunks.text" in statement for statement in statements)


def test_analysis_persists_one_file_in_a_few_transactions(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    _library(root, 12)
    context.scanning.scan(root)

    commits = _count_commits(context.db, lambda: context.analysis.analyse_pending(use_llm=False))

    assert commits <= 96
