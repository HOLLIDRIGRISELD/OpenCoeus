"""Keyword extraction used for tags and evidence.

A compact TF-based extractor with phrase support. It is deliberately simple and
deterministic so that recommendation evidence is reproducible.
"""

from __future__ import annotations

import re
from collections import Counter

_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between",
    "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during",
    "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself", "no", "nor",
    "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours",
    "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "will", "with", "would", "you", "your", "yours", "yourself", "yourselves",
    "page", "document", "file", "table", "figure", "section", "chapter", "contents",
    "university", "student", "students", "module", "course", "assignment",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'\-]{2,}")
_TEXT_LIMIT = 20_000


def extract_keywords(text: str, *, limit: int = 8) -> list[str]:
    """Return the most salient words and two-word phrases.

    Words appearing in the first 1,500 characters receive a small boost because
    titles, headings and introductions are usually more informative.
    """

    if not text.strip():
        return []
    raw_tokens = _WORD.findall(text[:_TEXT_LIMIT])
    acronyms = {token.lower() for token in raw_tokens if token.isupper() and 2 <= len(token) <= 6}
    tokens = [token.lower() for token in raw_tokens]
    tokens = [token for token in tokens if token not in _STOPWORDS and len(token) > 2]
    if not tokens:
        return []

    counts = Counter(tokens)
    head = Counter(
        token.lower()
        for token in _WORD.findall(text[:1500])
        if token.lower() not in _STOPWORDS and len(token) > 2
    )

    phrase_counts: Counter[str] = Counter()
    for first, second in zip(tokens, tokens[1:], strict=False):
        if first != second:
            phrase_counts[f"{first} {second}"] += 1

    scored: list[tuple[float, str]] = []
    for word, count in counts.items():
        score = count + 2.0 * head.get(word, 0)
        if word in acronyms:
            score += 1.0
        scored.append((score, word))
    for phrase, count in phrase_counts.items():
        if count >= 2:
            scored.append((count * 2.5, phrase))

    scored.sort(key=lambda item: (-item[0], item[1]))
    result: list[str] = []
    seen_words: set[str] = set()
    for _, term in scored:
        key = term.lower()
        if any(key in existing or existing in key for existing in seen_words):
            continue
        seen_words.add(key)
        result.append(term.title() if " " in term else term.capitalize())
        if len(result) >= limit:
            break
    return result
