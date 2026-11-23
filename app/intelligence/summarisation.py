"""Deterministic extractive summarisation.

The UI needs a short description of a document even when no language model is
available. This module selects the most representative sentences using a simple
frequency score (a one-iteration TextRank-style heuristic). It never invents
content, which keeps the "extracted vs inferred" distinction honest.
"""

from __future__ import annotations

import re
from collections import Counter

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
_TEXT_LIMIT = 20_000

_STOPWORDS = {
    "about", "after", "again", "against", "all", "also", "and", "another", "any", "are",
    "because", "been", "before", "being", "between", "both", "but", "can", "could", "did",
    "does", "each", "for", "from", "further", "had", "has", "have", "here", "how", "into",
    "its", "more", "most", "not", "now", "only", "other", "our", "out", "over", "same",
    "shall", "should", "some", "such", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "through", "under", "until", "very", "was",
    "were", "what", "when", "where", "which", "while", "who", "will", "with", "would",
    "you", "your", "document", "file", "page", "section",
}


def extractive_summary(
    text: str,
    *,
    max_chars: int = 300,
    max_sentences: int = 2,
    min_sentence_chars: int = 30,
) -> str | None:
    """Return a short summary selected from the document's own sentences.

    Returns ``None`` when the text is empty.
    """

    clean = " ".join(text[:_TEXT_LIMIT].split())
    if not clean:
        return None
    if len(clean) <= max_chars:
        return clean

    candidates = [
        sentence.strip()
        for sentence in _SENTENCE.split(clean)[:80]
        if min_sentence_chars <= len(sentence.strip()) <= 400
    ]
    if not candidates:
        return _truncate(clean, max_chars)

    frequencies: Counter[str] = Counter()
    for sentence in candidates:
        frequencies.update(
            word.lower()
            for word in _WORD.findall(sentence)
            if word.lower() not in _STOPWORDS
        )
    if not frequencies:
        return _truncate(clean, max_chars)
    peak = max(frequencies.values())

    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(candidates):
        words = [
            word.lower()
            for word in _WORD.findall(sentence)
            if word.lower() in frequencies
        ]
        if not words:
            continue
        score = sum(frequencies[word] / peak for word in words) / (len(words) + 1)
        if index == 0:
            score += 0.15
        scored.append((score, index, sentence))
    if not scored:
        return _truncate(clean, max_chars)

    selected = sorted(sorted(scored, reverse=True)[:max_sentences], key=lambda item: item[1])
    summary = " ".join(sentence for _, _, sentence in selected).strip()
    return _truncate(summary, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"
