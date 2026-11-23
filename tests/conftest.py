"""Shared pytest fixtures.

Every test runs against a temporary data directory and the deterministic
hashing embedding backend. The optional Sentence-Transformers model and the
local LLM are never contacted by the test suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import AppConfig
from app.services.context import AppContext


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    """Isolated configuration with optional AI features disabled."""

    return AppConfig(
        data_dir=tmp_path / "data",
        prefer_transformer=False,
        enable_llm=False,
        scan_batch_size=5,
        max_file_size_mb=25,
    )


@pytest.fixture()
def context(config: AppConfig):
    """A fully wired application context backed by a temporary database."""

    ctx = AppContext(config)
    try:
        yield ctx
    finally:
        ctx.close()


def write_text(path: Path, text: str) -> Path:
    """Write a UTF-8 text file, creating parent directories."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def sample_library(tmp_path: Path) -> Path:
    """A small, deterministic library covering four document families."""

    root = tmp_path / "library"
    write_text(
        root / "Downloads" / "invoice_acme_2024.txt",
        "INVOICE\n\n"
        "Invoice number: INV-2024-0042\n"
        "Bill to: Acme Systems Ltd\n"
        "Subtotal: 1,250.00\nVAT: 250.00\nAmount due: 1,500.00\n"
        "Payment terms: 30 days.\n",
    )
    write_text(
        root / "University" / "assignment_final.txt",
        "CS2018 Software Engineering Assignment\n\n"
        "Module code: CS2018. Student ID: 20481922.\n"
        "This coursework submission has a deadline and a marking rubric.\n"
        "Learning outcomes must be demonstrated in the final hand in.\n",
    )
    write_text(
        root / "Projects" / "api_reference.md",
        "# Local API Reference\n\n"
        "Installation and configuration guide.\n\n"
        "GET /health returns the service status. "
        "Troubleshooting: check the command syntax and schema version.\n",
    )
    write_text(
        root / "Documents" / "bank_statement_march.txt",
        "MONTHLY STATEMENT\n\n"
        "Account number: 12345678\nSort code: 40-11-22\n"
        "Opening balance: 2,300.00\nClosing balance: 1,980.25\n"
        "Transactions: credit salary, debit rent.\n",
    )
    write_text(root / ".git" / "config", "not a document")
    return root


@pytest.fixture()
def analysed_library(context: AppContext, sample_library: Path) -> Path:
    """Scan and analyse :func:`sample_library`, returning its root."""

    scan = context.scanning.scan(sample_library)
    assert scan.created == 4
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.failed == 0
    assert report.analysed == 4
    return sample_library


def file_id_for(context: AppContext, path: Path) -> int:
    """Look up a file id by path, failing loudly when it is absent."""

    file_id = context.files.find_by_path(path)
    assert file_id is not None, f"{path} was not registered"
    return file_id


def analysed_file(context: AppContext, root: Path, relative: str) -> int:
    """Return the id of one analysed file inside ``root``."""

    return file_id_for(context, root / relative)
