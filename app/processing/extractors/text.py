"""Plain-text, Markdown, CSV and similar text formats."""

from __future__ import annotations

import codecs
import html
import re
from pathlib import Path

from app.core.exceptions import ExtractionError
from app.domain.models import ExtractionResult
from app.processing.extractors.base import MAX_TEXT_CHARS, BaseExtractor

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_READ_CHUNK_BYTES = 1 << 20
_READ_TARGET_CHARS = MAX_TEXT_CHARS + 4096
_MARKUP_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_MARKUP_TAG = re.compile(r"<[^>]*>?")
_MARKUP_SUFFIXES = {".html", ".htm", ".xhtml", ".xml"}


def _markup_title(text: str) -> str | None:
    """Return a real ``<title>`` value from HTML/XML, decoded and detagged."""

    match = _MARKUP_TITLE.search(text)
    if not match:
        return None
    value = _MARKUP_TAG.sub(" ", html.unescape(match.group(1)))
    value = " ".join(value.split())
    head = re.split(r"\.\s+", value, maxsplit=1)[0]
    if len(head) >= 15:
        value = head
    return value.strip(" .") or None


def _decode_limited(path: Path) -> tuple[str, str, bool]:
    parts: list[str] = []
    total = 0
    decoder = None
    used_encoding = ""
    replaced = False
    meaningful = False

    with path.open("rb") as handle:
        first_chunk = True
        while not meaningful or total < _READ_TARGET_CHARS:
            chunk = handle.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            if first_chunk:
                if chunk.startswith(_UTF16_BOMS):
                    used_encoding = "utf-16"
                    decoder = codecs.getincrementaldecoder(used_encoding)()
                else:
                    if b"\x00" in chunk[:4096]:
                        raise ExtractionError(f"{path.name} appears to be binary, not text.")
                    for encoding in _ENCODINGS:
                        try:
                            codecs.getincrementaldecoder(encoding)().decode(chunk, final=False)
                            decoder = codecs.getincrementaldecoder(encoding)()
                            used_encoding = encoding
                            break
                        except UnicodeDecodeError:
                            continue
                    if decoder is None:
                        decoder = codecs.getincrementaldecoder("utf-8")("replace")
                        used_encoding = "utf-8 (replaced)"
                        replaced = True
                first_chunk = False
            try:
                decoded = decoder.decode(chunk, final=False)
            except UnicodeDecodeError:
                decoder = codecs.getincrementaldecoder(used_encoding.removesuffix("-sig"))("replace")
                decoded = decoder.decode(chunk, final=False)
                replaced = True
            if not meaningful:
                if not decoded.strip():
                    continue
                meaningful = True
            parts.append(decoded)
            total += len(decoded)
        if decoder is None:
            decoder = codecs.getincrementaldecoder(_ENCODINGS[0])()
            used_encoding = _ENCODINGS[0]
        try:
            tail = decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            tail = ""
            replaced = True
        if tail:
            parts.append(tail)

    return "".join(parts), used_encoding, replaced


class TextExtractor(BaseExtractor):
    name = "text"
    version = "1.0"
    formats = ("text",)

    def extract(self, path: Path) -> ExtractionResult:
        warnings: list[str] = []
        decoded, used_encoding, replaced = _decode_limited(path)
        if replaced:
            warnings.append("Some characters could not be decoded and were replaced.")
        text = decoded.strip()
        if not text:
            warnings.append("The file is empty.")

        return ExtractionResult(
            text=self._truncate(text, warnings),
            method=self.name,
            success=True,
            page_count=None,
            title=(
                _markup_title(text)
                if path.suffix.lower() in _MARKUP_SUFFIXES
                else None
            )
            or self._first_meaningful_line(text),
            warnings=warnings,
            meta={"encoding": used_encoding},
        )
