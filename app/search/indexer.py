"""Full-text index maintenance.

FTS is kept as an explicit projection of the relational data rather than using
SQLite triggers, because the indexed text combines the filename, extracted
content and AI tags, which live in different tables.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.logging_config import get_logger
from app.infrastructure.database import Database
from app.infrastructure.models import DocumentContent, File, FileTag, Tag

logger = get_logger(__name__)


class SearchIndexer:
    """Writes and rebuilds the SQLite FTS5 index."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def index_file(self, file_id: int, *, text: str | None = None) -> None:
        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                return
            if text is None:
                content = session.scalar(
                    select(DocumentContent).where(DocumentContent.file_id == file_id)
                )
                text = content.text if content else ""
            tags = session.execute(
                select(Tag.name).join(FileTag, FileTag.tag_id == Tag.id).where(FileTag.file_id == file_id)
            ).scalars().all()
            self._db.upsert_fts(
                file_id,
                record.current_name,
                text,
                " ".join(tags),
            )

    def rebuild(self) -> int:
        """Recreate the FTS index for every file. Returns the number indexed."""

        with self._db.batch():
            with self._db.session() as session:
                rows = session.execute(
                    select(File.id, File.current_name, DocumentContent.text).outerjoin(
                        DocumentContent, DocumentContent.file_id == File.id
                    )
                ).all()
                tags: dict[int, list[str]] = {}
                for file_id, name in session.execute(
                    select(FileTag.file_id, Tag.name).join(
                        Tag, FileTag.tag_id == Tag.id
                    )
                ):
                    tags.setdefault(file_id, []).append(name)
            payload = [
                (file_id, filename, content or "", " ".join(tags.get(file_id, [])))
                for file_id, filename, content in rows
            ]
            self._db.upsert_fts_many(payload)
        logger.info("Rebuilt FTS index for %d files", len(payload))
        return len(payload)
