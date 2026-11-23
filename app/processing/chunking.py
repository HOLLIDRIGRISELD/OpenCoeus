"""Text segmentation for embeddings and evidence.

Chunks are measured in characters with a configurable overlap. The defaults
correspond roughly to 450–500 English tokens per chunk, which is a reasonable
starting point for the MiniLM-class embedding models used by OpenCoeus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.models import DocumentChunk

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")


@dataclass(slots=True)
class ChunkingConfig:
    """Chunk-size configuration.

    Args:
        target_chars: Soft maximum size of a chunk.
        overlap_chars: Characters repeated between adjacent chunks.
        min_chars: Chunks smaller than this are merged into the previous one.
        max_chunks: Safety cap for extremely long documents.
    """

    target_chars: int = 1800
    overlap_chars: int = 250
    min_chars: int = 200
    max_chunks: int = 96


def chunk_text(text: str, config: ChunkingConfig | None = None) -> list[DocumentChunk]:
    """Split text into overlapping chunks on paragraph and sentence boundaries."""

    config = config or ChunkingConfig()
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalised:
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(normalised) if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= config.target_chars:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= config.target_chars:
            current = paragraph
        else:
            chunks.extend(_split_long_paragraph(paragraph, config))
            current = ""

    if current:
        if chunks and len(current) < config.min_chars:
            chunks[-1] = f"{chunks[-1]}\n\n{current}"
        else:
            chunks.append(current)

    overlapped: list[str] = []
    for index, chunk in enumerate(chunks):
        if index == 0 or config.overlap_chars <= 0:
            overlapped.append(chunk)
            continue
        tail = chunks[index - 1][-config.overlap_chars :]
        overlapped.append(f"{tail}\n{chunk}".strip())

    return [
        DocumentChunk(index=index, text=chunk)
        for index, chunk in enumerate(overlapped[: config.max_chunks])
    ]


def _split_long_paragraph(paragraph: str, config: ChunkingConfig) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= config.target_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                pieces.append(current)
            while len(sentence) > config.target_chars:
                pieces.append(sentence[: config.target_chars])
                sentence = sentence[config.target_chars :]
            current = sentence
    if current:
        pieces.append(current)
    return pieces
