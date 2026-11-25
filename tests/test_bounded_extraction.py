"""Text extraction must bound reads only after decoding bytes."""

from __future__ import annotations

from pathlib import Path

from PIL import ExifTags

from app.processing.extractors import image as image_module
from app.processing.extractors.base import MAX_TEXT_CHARS
from app.processing.extractors.image import ImageExtractor
from app.processing.extractors.text import TextExtractor


def test_text_extractor_stops_reading_after_decode_limit(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "big.txt"
    path.write_text("INVOICE 12345\n" * 300_000, encoding="utf-8")

    original_open = Path.open
    read_sizes: list[int] = []

    class CountingFile:
        def __init__(self, handle) -> None:
            self._handle = handle

        def read(self, size: int = -1) -> bytes:
            data = self._handle.read(size)
            read_sizes.append(len(data))
            return data

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, *args):
            return self._handle.__exit__(*args)

    def counting_open(self, *args, **kwargs):
        return CountingFile(original_open(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", counting_open)

    result = TextExtractor().extract(path)

    assert len(result.text) == MAX_TEXT_CHARS
    assert sum(read_sizes) < path.stat().st_size
    assert any("truncated" in warning for warning in result.warnings)


def test_image_extractor_truncates_oversized_exif_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(image_module, "inspect_format", lambda path: "image")
    description = "x" * (MAX_TEXT_CHARS + 10)
    tag = next(key for key, value in ExifTags.TAGS.items() if value == "ImageDescription")

    class FakeImage:
        width = 1
        height = 1
        mode = "RGB"
        format = "PNG"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def getexif(self):
            return {tag: description}

    monkeypatch.setattr(image_module.Image, "open", lambda path: FakeImage())

    result = ImageExtractor().extract(tmp_path / "image.png")

    assert len(result.text) == MAX_TEXT_CHARS
    assert any("truncated" in warning for warning in result.warnings)


def test_text_extractor_decodes_utf16_with_bom(tmp_path: Path) -> None:
    path = tmp_path / "utf16.txt"
    path.write_bytes("UTF-16 invoice\nAmount: €100\n".encode("utf-16"))

    result = TextExtractor().extract(path)

    assert result.success is True
    assert "invoice" in result.text
    assert "€100" in result.text
    assert result.meta["encoding"] == "utf-16"
    assert result.warnings == []


def test_text_extractor_preserves_multibyte_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "unicode.txt"
    path.write_text("€" * 100, encoding="utf-8")

    result = TextExtractor().extract(path)
    assert result.text == "€" * 100
    assert result.meta["encoding"] == "utf-8-sig"
