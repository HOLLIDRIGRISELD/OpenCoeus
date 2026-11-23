"""Keyword retrieval over SQLite FTS5.

Queries are tokenised and quoted before being passed to ``MATCH``. This avoids
the most common FTS5 failure mode (syntax errors from raw user input) and keeps
the search predictable for ordinary keyword searches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text

from app.domain.models import SearchHit
from app.infrastructure.database import Database

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "my", "of", "on", "or", "that", "the", "this", "to", "with", "find", "show", "me",
    "documents", "document", "files", "file", "about", "which", "what", "where",
}


@dataclass(slots=True)
class KeywordQuery:
    match_expression: str
    terms: list[str]


def build_match_expression(query: str) -> KeywordQuery:
    tokens = [token.lower() for token in _TOKEN.findall(query)]
    meaningful = [token for token in tokens if token not in _STOPWORDS]
    selected = meaningful or tokens
    if not selected:
        return KeywordQuery("", [])
    expression = " OR ".join(f'"{token}"' for token in dict.fromkeys(selected[:12]))
    return KeywordQuery(expression, list(dict.fromkeys(selected)))


class KeywordSearch:
    """FTS5-backed search returning ranked file ids with snippets."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def search(self, query: str, *, limit: int = 50) -> list[SearchHit]:
        parsed = build_match_expression(query)
        if not parsed.match_expression:
            return []

        sql = text(
            """
            SELECT
                f.id AS file_id,
                f.current_name AS filename,
                f.current_path AS path,
                bm25(file_fts) AS rank,
                snippet(file_fts, 1, '[', ']', ' … ', 14) AS content_snippet,
                snippet(file_fts, 0, '[', ']', ' … ', 8) AS name_snippet
            FROM file_fts
            JOIN files AS f ON f.id = file_fts.rowid
            WHERE file_fts MATCH :expression
            ORDER BY rank
            LIMIT :limit
            """
        )
        with self._db.engine.connect() as connection:
            rows = connection.execute(
                sql, {"expression": parsed.match_expression, "limit": limit}
            ).mappings().all()

        hits: list[SearchHit] = []
        for row in rows:
            raw_rank = float(row["rank"] or 0.0)
            score = 1.0 / (1.0 + abs(raw_rank))
            snippet = (row["content_snippet"] or "").strip() or (row["name_snippet"] or "").strip()
            hits.append(
                SearchHit(
                    file_id=int(row["file_id"]),
                    filename=str(row["filename"]),
                    path=row["path"],
                    score=round(score, 4),
                    mode="keyword",
                    snippet=snippet or None,
                    explanation="Matched indexed filename, content or tags.",
                )
            )
        return hits
