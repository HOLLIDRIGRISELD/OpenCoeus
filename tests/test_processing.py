"""Text chunking, format detection, hashing and extraction."""

from __future__ import annotations

import io
import random
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from PIL import Image

from app.core.exceptions import UnsupportedFormatError
from app.domain.models import DocumentChunk
from app.processing.chunking import ChunkingConfig, chunk_text
from app.processing.extractors import ExtractorRegistry
from app.processing.extractors.image import ImageExtractor
from app.processing.extractors.xlsx import XlsxExtractor
from app.processing.file_signature import inspect_format
from app.processing.hashing import sha256_file, sha256_text


def test_chunk_text_returns_empty_for_blank_input() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n\t ") == []


def test_chunk_text_keeps_short_document_whole() -> None:
    chunks = chunk_text("A short paragraph.\n\nAnother short paragraph.")
    assert len(chunks) == 1
    assert isinstance(chunks[0], DocumentChunk)
    assert chunks[0].index == 0
    assert "Another short paragraph." in chunks[0].text
    assert chunks[0].token_estimate >= 1


def test_chunk_text_splits_long_documents_with_overlap() -> None:
    paragraphs = [f"Paragraph {index}. " + ("word " * 120) for index in range(8)]
    chunks = chunk_text("\n\n".join(paragraphs), ChunkingConfig(target_chars=600, overlap_chars=80))

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.text) <= 900 for chunk in chunks)
    assert chunks[0].text[-40:] in chunks[1].text


def test_chunk_text_respects_max_chunks() -> None:
    paragraphs = [f"Paragraph {index}. " + ("word " * 200) for index in range(30)]
    chunks = chunk_text(
        "\n\n".join(paragraphs),
        ChunkingConfig(target_chars=400, max_chunks=3),
    )
    assert len(chunks) == 3


def test_chunk_text_caps_the_number_of_chunks() -> None:
    text = ("alpha beta gamma delta " * 40_000).strip()

    chunks = chunk_text(text)

    assert len(chunks) == 96


def test_chunk_text_samples_the_tail_of_a_very_long_document() -> None:
    paragraphs = [f"SECTION {index}: " + ("word " * 200) for index in range(500)]

    chunks = chunk_text("\n\n".join(paragraphs))

    assert len(chunks) == 96
    assert "SECTION 0" in chunks[0].text
    assert "SECTION 499" in chunks[-1].text


def test_chunk_text_splits_a_single_huge_paragraph() -> None:
    text = ("This is a sentence. " * 500).strip()
    chunks = chunk_text(text, ChunkingConfig(target_chars=500, overlap_chars=0))
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 700 for chunk in chunks)


def test_inspect_format_recognises_text_image_and_zip_office(tmp_path: Path) -> None:
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello", encoding="utf-8")
    assert inspect_format(text_file) == "text"

    png = tmp_path / "picture.bin"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    assert inspect_format(png) == "image"

    pdf = tmp_path / "paper.dat"
    pdf.write_bytes(b"%PDF-1.7\n")
    assert inspect_format(pdf) == "pdf"

    fake_office = tmp_path / "broken.docx"
    fake_office.write_bytes(b"PK\x03\x04" + b"\x00" * 16)
    assert inspect_format(fake_office) == "unknown"


def test_hashing_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "one.txt"
    second = tmp_path / "two.txt"
    first.write_text("same content", encoding="utf-8")
    second.write_text("same content", encoding="utf-8")

    assert sha256_file(first) == sha256_file(second)
    assert sha256_file(first) == sha256_text("same content")
    second.write_text("different content", encoding="utf-8")
    assert sha256_file(first) != sha256_file(second)


def test_text_extractor_reads_and_reports_title(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Lecture Notes Week 3\n\nLearning outcomes and reading list.\n", encoding="utf-8")
    result = ExtractorRegistry().extract(path, "text")

    assert result.success is True
    assert result.method == "text"
    assert "Lecture Notes Week 3" in result.text
    assert result.title == "Lecture Notes Week 3"
    assert result.char_count > 0
    assert result.quality in {"low", "medium", "high"}


def test_registry_rejects_unknown_formats(tmp_path: Path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    with pytest.raises(UnsupportedFormatError):
        ExtractorRegistry().extract(path, "zip")


def test_image_extractor_keeps_header_metadata_when_file_is_truncated(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    pixels = random.Random(0).randbytes(64 * 64 * 4)
    Image.frombytes("RGBA", (64, 64), pixels).save(buffer, format="PNG")
    path = tmp_path / "truncated.png"
    path.write_bytes(buffer.getvalue()[:-40])

    result = ImageExtractor().extract(path)

    assert result.success is True
    assert result.meta["format"] == "PNG"
    assert result.meta["width"] == 64
    assert result.meta["height"] == 64
    assert any("truncated" in warning.lower() for warning in result.warnings)


def test_xlsx_extractor_skips_chartsheets(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet["A1"] = "Quarter"
    sheet["B1"] = "Revenue"
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=1))
    workbook.create_chartsheet(title="Chart").add_chart(chart)
    path = tmp_path / "with_chart.xlsx"
    workbook.save(path)

    result = XlsxExtractor().extract(path)

    assert result.success is True
    assert "Revenue" in result.text
    assert "[Sheet: Chart]" not in result.text
    assert any("chart" in warning.lower() for warning in result.warnings)


def test_inspect_format_recognises_vector_images(tmp_path: Path) -> None:
    svg = tmp_path / "drawing.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    eps = tmp_path / "drawing.eps"
    eps.write_text("%!PS-Adobe-3.0\n%%EOF\n", encoding="ascii")

    assert inspect_format(svg) == "vector-image"
    assert inspect_format(eps) == "vector-image"


def test_image_extractor_returns_metadata_only_for_vector_image(tmp_path: Path) -> None:
    path = tmp_path / "drawing.svg"
    path.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    result = ImageExtractor().extract(path)

    assert result.success is True
    assert result.text == ""
    assert result.method == "vector-metadata"
    assert any("vector" in warning.lower() for warning in result.warnings)
    assert result.meta["format"] == "SVG"
