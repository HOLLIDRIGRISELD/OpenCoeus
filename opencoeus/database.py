from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .config import database_url
from .models import Base, FileAudit, NamingHistory


class AuditStore:
    def __init__(self, database_connection_url: str | None = None) -> None:
        self.engine = create_engine(database_connection_url or database_url())
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def record_file(self, file_path: str, file_size: int, file_hash: str | None, file_status: str) -> None:
        with self.session_factory() as session:
            audit_record = session.scalar(select(FileAudit).where(FileAudit.path == file_path))
            if audit_record is None:
                audit_record = FileAudit(path=file_path, size=file_size, sha256=file_hash, status=file_status)
                session.add(audit_record)
            else:
                audit_record.size, audit_record.sha256, audit_record.status = file_size, file_hash, file_status
                audit_record.last_seen_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()

    def reserve_title(self, proposed_title: str, source_file_path: str) -> str:
        with self.session_factory() as session:
            existing_source_title = session.scalar(
                select(NamingHistory).where(NamingHistory.source_path == source_file_path)
            )
            if existing_source_title:
                return existing_source_title.suggested_title
            available_title, duplicate_number = proposed_title, 2
            while session.scalar(select(NamingHistory).where(NamingHistory.suggested_title == available_title)):
                available_title = f"{proposed_title} ({duplicate_number})"
                duplicate_number += 1
            session.add(NamingHistory(suggested_title=available_title, source_path=source_file_path))
            session.commit()
            return available_title

    def close(self) -> None:
        """RELEASES SQLITE HANDLES PROMPTLY."""
        self.engine.dispose()
