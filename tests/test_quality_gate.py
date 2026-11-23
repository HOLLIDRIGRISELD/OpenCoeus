"""Golden analysis outputs that every performance change must preserve."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

import fitz
from docx import Document
from openpyxl import Workbook
from PIL import Image

from app.services.context import AppContext
from tests.conftest import write_text

GOLDEN = Path(__file__).parent / "fixtures" / "quality_golden.json"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_semantic_filename(suggested: str, original: str, content: str) -> None:
    """Reject opaque identifiers when extracted content could inform a name."""

    if not content.strip():
        return
    stem = Path(suggested).stem
    assert not re.fullmatch(r"[0-9a-f]{12,}", stem, re.IGNORECASE), stem
    assert not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stem), stem
    original_stem = Path(original).stem
    opaque_original = (
        len(original_stem) >= 12
        and any(character.isdigit() for character in original_stem)
        and original_stem.isalnum()
    )
    if opaque_original:
        assert stem.lower() != original_stem.lower(), stem


def _library(root: Path) -> dict[str, str]:
    texts = {
        "invoice.txt": (
            "INVOICE\n\nInvoice number: INV-2024-0042\nBill to: Acme Systems Ltd\n"
            "Subtotal: 1,250.00\nVAT: 250.00\nAmount due: 1,500.00\n"
            "Payment terms: 30 days. Please remit to the account below.\n"
        ),
        "notes.md": (
            "# Module notes\n\nLecture 4 covers hybrid classification.\n"
            "Revision note: review the worked example before the seminar.\n"
        ),
        "expenses.csv": (
            "date,description,amount\n2024-03-01,stationery,18.50\n"
            "2024-03-02,postage,4.20\n"
        ),
        "service.py": (
            "def classify(document: str) -> str:\n"
            "    configuration = load_config()\n"
            "    return configuration.category_for(document)\n"
        ),
    }
    for name, text in texts.items():
        write_text(root / name, text)

    Image.new("RGB", (16, 16), (20, 40, 80)).save(root / "chart.png")

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((24, 48), "INVOICE\nInvoice number: INV-2024-0099\nAmount due: 42.00")
    pdf.save(root / "statement.pdf")
    pdf.close()

    document = Document()
    document.add_paragraph("Contract agreement and governing law between the parties.")
    document.save(root / "agreement.docx")

    workbook = Workbook()
    workbook.active["A1"] = "Opening balance"
    workbook.active["B1"] = 2300
    workbook.save(root / "balances.xlsx")

    return texts


def _snapshot(context: AppContext, root: Path) -> dict[str, object]:
    analysis_repository = context.analyses
    model = context.embeddings.model_name
    embeddings: dict[int, list[list[float]]] = {}
    for file_id, vector, _ in analysis_repository.load_embeddings(model):
        embeddings.setdefault(file_id, []).append([round(float(value), 6) for value in vector])

    result: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        file_id = context.files.find_by_path(path)
        assert file_id is not None, f"{path.name} was not registered"
        classification = analysis_repository.latest_analysis(file_id)
        assert classification is not None, f"{path.name} was not analysed"
        chunks = analysis_repository.chunks_for(file_id)
        suggestions = analysis_repository.suggestions_for_file(file_id)
        content = analysis_repository.content_for(file_id)
        filename_suggestion = suggestions.get("filename")
        if filename_suggestion is not None:
            assert_semantic_filename(filename_suggestion.suggested_value, path.name, content)
        record = context.files.get_record(file_id)
        with sqlite3.connect(context.config.db_path) as connection:
            fts = connection.execute(
                "select filename, content, tags from file_fts where rowid = ?", (file_id,)
            ).fetchone()
        result[path.name] = {
            "status": record["status"],
            "content": _digest(content),
            "chunks": [[chunk.index, chunk.page, _digest(chunk.text)] for chunk in chunks],
            "embeddings": embeddings.get(file_id, []),
            "category": classification.category_path,
            "confidence": round(classification.confidence, 6),
            "scores": {key: round(value, 6) for key, value in classification.scores.items()},
            "needs_review": classification.needs_review,
            "fts": [_digest(fts[0]), _digest(fts[1]), _digest(fts[2])] if fts else None,
            "suggestions": {
                key: suggestion.suggested_value
                for key in ("filename", "destination", "category")
                if (suggestion := suggestions.get(key)) is not None
            },
        }
    return result


def test_generated_names_are_accurate_readable_and_symbol_free(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    _library(root)

    context.scanning.scan(root)
    context.analysis.analyse_pending(use_llm=False)

    expected = {
        "agreement.docx": "agreement.docx",
        "balances.xlsx": "balances.xlsx",
        "chart.png": "chart.png",
        "expenses.csv": "expenses.csv",
        "service.py": "service.py",
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        file_id = context.files.find_by_path(path)
        assert file_id is not None
        suggestion = context.analyses.suggestions_for_file(file_id)["filename"]
        if path.name in expected:
            assert suggestion.suggested_value == expected[path.name]
        stem = Path(suggestion.suggested_value).stem
        assert not any(symbol in stem for symbol in ("/", "_", "=", "\\")), stem
        assert len(stem) <= 60, stem


def test_analysis_outputs_match_the_golden_snapshot(
    context: AppContext, tmp_path: Path
) -> None:
    root = tmp_path / "library"
    expected_texts = _library(root)

    scan = context.scanning.scan(root)
    assert scan.discovered == len(expected_texts) + 4
    report = context.analysis.analyse_pending(use_llm=False)
    assert report.failed == 0
    assert report.analysed == scan.discovered

    actual = _snapshot(context, root)
    if os.environ.get("OPENCOEUS_WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(actual, indent=2, sort_keys=True), encoding="utf-8")
    assert GOLDEN.exists(), "baseline golden snapshot is missing"
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected
