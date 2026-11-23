"""Repository for discovered files and dashboard aggregates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from sqlalchemy import func, select

from app.core.constants import (
    STATUS_ANALYSED,
    STATUS_FAILED,
    STATUS_ORGANISED,
    STATUS_PENDING_REVIEW,
    STATUS_UNAVAILABLE,
)
from app.core.exceptions import DatabaseError
from app.domain.models import DashboardStats, FileSummary, ManifestRow, ScannedFile, utcnow
from app.infrastructure.database import Database
from app.infrastructure.models import (
    DocumentAnalysis,
    File,
    FileMeta,
    FileTag,
    Operation,
    PlanItem,
    Tag,
)
from app.infrastructure.repositories._helpers import category_path_map


class FileRepository:
    """CRUD and read queries for the ``files`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(self, scanned: ScannedFile, *, status: str = "discovered") -> tuple[int, bool]:
        """Insert or refresh one file record discovered at ``scanned.path``."""

        return self.upsert_many([(scanned, status)])[0]

    def upsert_many(
        self, items: Sequence[tuple[ScannedFile, str]]
    ) -> list[tuple[int, bool]]:
        """Insert or refresh a batch of discovered files in one transaction."""

        if not items:
            return []
        paths = [str(scanned.path) for scanned, _ in items]
        now = utcnow()
        with self._db.session() as session:
            existing = {
                record.current_path: record
                for record in session.scalars(select(File).where(File.current_path.in_(paths)))
            }
            results: list[tuple[int, bool]] = []
            for scanned, status in items:
                path_str = str(scanned.path)
                record = existing.get(path_str)
                created = record is None
                if record is None:
                    record = File(
                        original_name=scanned.filename,
                        current_name=scanned.filename,
                        original_path=path_str,
                        current_path=path_str,
                        extension=scanned.extension,
                        mime_type=scanned.mime_type,
                        detected_format=scanned.detected_format,
                        file_size=scanned.size,
                        sha256_hash=scanned.sha256,
                        created_at=scanned.created_at,
                        modified_at=scanned.modified_at,
                        last_scanned_at=now,
                        processing_status=status,
                        is_available=True,
                    )
                    session.add(record)
                else:
                    changed = (
                        record.file_size != scanned.size
                        or record.modified_at != scanned.modified_at
                        or (scanned.sha256 is not None and record.sha256_hash != scanned.sha256)
                    )
                    record.file_size = scanned.size
                    record.modified_at = scanned.modified_at
                    record.extension = scanned.extension
                    record.mime_type = scanned.mime_type or record.mime_type
                    record.detected_format = scanned.detected_format or record.detected_format
                    record.last_scanned_at = now
                    record.is_available = True
                    if scanned.sha256:
                        record.sha256_hash = scanned.sha256
                    if changed:
                        record.processing_status = status
                        record.last_analysed_at = None
                results.append((record.id, created))
            session.flush()
        return results

    def get_summary(self, file_id: int) -> FileSummary | None:
        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                return None
            analyses, paths, tags = self._summary_maps(session, [record])
            return self._to_summary(record, analyses, paths, tags)

    def list_summaries(
        self,
        *,
        limit: int = 500,
        status: str | None = None,
        extension: str | None = None,
        text_filter: str | None = None,
        order_by: str = "modified",
    ) -> list[FileSummary]:
        """Return summaries for the file table.

        ``text_filter`` is a simple case-insensitive substring match on the
        current filename; deeper content search goes through ``SearchService``.
        """

        with self._db.session() as session:
            stmt = select(File)
            if status:
                stmt = stmt.where(File.processing_status == status)
            if extension:
                stmt = stmt.where(File.extension == extension.lower())
            if text_filter:
                stmt = stmt.where(File.current_name.ilike(f"%{text_filter}%"))
            if order_by == "name":
                stmt = stmt.order_by(File.current_name.collate("NOCASE"))
            elif order_by == "size":
                stmt = stmt.order_by(File.file_size.desc())
            else:
                stmt = stmt.order_by(File.modified_at.desc().nullslast())
            stmt = stmt.limit(limit)
            records = session.scalars(stmt).all()
            analyses, paths, tags = self._summary_maps(session, records)
            return [self._to_summary(record, analyses, paths, tags) for record in records]

    def _summary_maps(self, session, records: Sequence[File]) -> tuple[dict, dict, dict]:  # type: ignore[no-untyped-def]
        if not records:
            return {}, {}, {}
        file_ids = [record.id for record in records]
        analyses = {
            row.file_id: row
            for row in session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id.in_(file_ids))
                .order_by(DocumentAnalysis.id)
            ).all()
        }
        paths = category_path_map(session)
        tags: dict[int, list[str]] = {}
        rows = session.execute(
            select(FileTag.file_id, Tag.name)
            .join(Tag, FileTag.tag_id == Tag.id)
            .where(FileTag.file_id.in_(file_ids))
        )
        for file_id, name in rows:
            tags.setdefault(file_id, []).append(name)
        return analyses, paths, tags

    def _to_summary(
        self,
        record: File,
        analyses: dict,
        paths: dict,
        tags: dict,
    ) -> FileSummary:
        analysis = analyses.get(record.id)
        category = None
        confidence = None
        title = analysis.document_title if analysis else None
        if analysis and analysis.category_id:
            category = paths.get(analysis.category_id)
        if analysis:
            confidence = analysis.confidence_score
        return FileSummary(
            id=record.id,
            name=record.current_name,
            path=record.current_path,
            extension=record.extension or "",
            size=record.file_size,
            modified_at=record.modified_at,
            status=record.processing_status,
            category=category,
            confidence=confidence,
            title=title,
            tags=list(tags.get(record.id, [])),
            is_available=record.is_available,
        )

    def light_records(self, file_ids: Sequence[int]) -> dict[int, dict[str, object]]:
        latest_title = (
            select(DocumentAnalysis.document_title)
            .where(DocumentAnalysis.file_id == File.id)
            .order_by(DocumentAnalysis.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        meta_title = (
            select(FileMeta.title).where(FileMeta.file_id == File.id).scalar_subquery()
        )
        with self._db.session() as session:
            rows = session.execute(
                select(
                    File.id,
                    File.current_name,
                    File.current_path,
                    File.extension,
                    File.sha256_hash,
                    File.file_size,
                    File.modified_at,
                    File.detected_format,
                    latest_title.label("analysis_title"),
                    meta_title.label("meta_title"),
                ).where(File.id.in_(file_ids))
            ).all()
            paths = category_path_map(session)
            categories: dict[int, int | None] = {}
            for file_id, category_id in session.execute(
                select(DocumentAnalysis.file_id, DocumentAnalysis.category_id)
                .where(DocumentAnalysis.file_id.in_(file_ids))
                .order_by(DocumentAnalysis.id)
            ):
                categories[file_id] = category_id
            return {
                row.id: {
                    "id": row.id,
                    "name": row.current_name,
                    "path": Path(row.current_path),
                    "extension": row.extension or "",
                    "hash": row.sha256_hash,
                    "size": row.file_size,
                    "modified_at": row.modified_at,
                    "detected_format": row.detected_format,
                    "category": paths.get(categories.get(row.id)),
                    "title": row.analysis_title or row.meta_title,
                }
                for row in rows
            }

    def manifest_rows(self) -> list[ManifestRow]:
        """Return one audit row per file with the newest plan and operation only."""

        latest_plan = (
            select(PlanItem.action)
            .where(PlanItem.file_id == File.id)
            .order_by(PlanItem.plan_id.desc(), PlanItem.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        latest_operation = (
            select(Operation.status)
            .where(Operation.file_id == File.id)
            .order_by(Operation.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        latest_category = (
            select(DocumentAnalysis.category_id)
            .where(DocumentAnalysis.file_id == File.id)
            .order_by(DocumentAnalysis.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        with self._db.session() as session:
            categories = category_path_map(session)
            rows = session.execute(
                select(
                    File.current_path,
                    File.current_name,
                    File.file_size,
                    File.sha256_hash,
                    File.processing_status,
                    File.modified_at,
                    latest_plan,
                    latest_operation,
                    latest_category,
                ).order_by(File.current_path)
            ).all()
            return [
                ManifestRow(
                    path=path,
                    name=name,
                    size_bytes=size,
                    sha256=sha256 or "",
                    status=status,
                    category=categories.get(category_id) or "",
                    modified_at=modified.isoformat() if modified else "",
                    last_planned_action=planned_action or "",
                    last_operation_status=operation_status or "",
                )
                for (
                    path,
                    name,
                    size,
                    sha256,
                    status,
                    modified,
                    planned_action,
                    operation_status,
                    category_id,
                ) in rows
            ]

    def get_record(self, file_id: int) -> dict[str, object] | None:
        """Return a denormalised record for planning without an open session."""

        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                return None
            analysis = session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id == record.id)
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            ).first()
            meta = session.scalar(select(FileMeta).where(FileMeta.file_id == record.id))
            category = None
            category_id = None
            if analysis and analysis.category_id:
                category = category_path_map(session).get(analysis.category_id)
                category_id = analysis.category_id
            return {
                "id": record.id,
                "name": record.current_name,
                "path": Path(record.current_path),
                "extension": record.extension or "",
                "mime_type": record.mime_type,
                "detected_format": record.detected_format,
                "size": record.file_size,
                "status": record.processing_status,
                "hash": record.sha256_hash,
                "category": category,
                "category_id": category_id,
                "confidence": analysis.confidence_score if analysis else None,
                "title": (analysis.document_title if analysis else None) or (meta.title if meta else None),
                "document_type": analysis.document_type if analysis else None,
                "organisation": analysis.organisation if analysis else None,
                "document_date": analysis.document_date if analysis else None,
                "modified_at": record.modified_at,
            }

    def find_by_path(self, path: Path) -> int | None:
        with self._db.session() as session:
            return session.scalar(select(File.id).where(File.current_path == str(path)))

    def find_analysed_duplicate(self, file_id: int, sha256: str) -> int | None:
        """Return the newest analysed file with identical bytes, excluding ``file_id``."""

        if not sha256:
            return None
        with self._db.session() as session:
            return session.scalar(
                select(File.id)
                .join(DocumentAnalysis, DocumentAnalysis.file_id == File.id)
                .where(
                    File.sha256_hash == sha256,
                    File.id != file_id,
                    File.processing_status.in_(
                        [STATUS_ANALYSED, STATUS_ORGANISED, STATUS_PENDING_REVIEW]
                    ),
                )
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            )

    def find_analysed_duplicates(
        self, file_ids: Sequence[int], hashes: Mapping[int, str]
    ) -> dict[int, int]:
        """Return one analysed source per distinct non-empty hash in one query."""

        candidates = {file_id: sha256 for file_id, sha256 in hashes.items() if sha256}
        if not candidates:
            return {}
        with self._db.session() as session:
            rows = session.execute(
                select(File.id, File.sha256_hash)
                .join(DocumentAnalysis, DocumentAnalysis.file_id == File.id)
                .where(
                    File.sha256_hash.in_(set(candidates.values())),
                    File.id.not_in(file_ids),
                    File.processing_status.in_(
                        [STATUS_ANALYSED, STATUS_ORGANISED, STATUS_PENDING_REVIEW]
                    ),
                )
                .order_by(DocumentAnalysis.id.desc())
            ).all()
        sources: dict[str, int] = {}
        for source_id, sha256 in rows:
            sources.setdefault(sha256, source_id)
        return {
            file_id: sources[sha256]
            for file_id, sha256 in candidates.items()
            if sha256 in sources
        }

    def set_hash(self, file_id: int, sha256: str) -> None:
        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            record.sha256_hash = sha256

    def update_status(self, file_id: int, status: str, *, analysed: bool = False) -> None:
        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            record.processing_status = status
            if analysed:
                record.last_analysed_at = utcnow()

    def update_location(self, file_id: int, path: Path) -> None:
        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            record.current_path = str(path)
            record.current_name = path.name

    def mark_missing(self, file_id: int) -> None:
        with self._db.session() as session:
            record = session.get(File, file_id)
            if record is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            record.is_available = False
            record.processing_status = STATUS_UNAVAILABLE

    def ids_by_status(self, statuses: list[str], *, limit: int | None = None) -> list[int]:
        """Return file ids in any of ``statuses`` ordered by path.

        Used by batch pipelines that need a stable, resumable work queue.
        """

        if not statuses:
            return []
        with self._db.session() as session:
            stmt = (
                select(File.id)
                .where(File.processing_status.in_(statuses))
                .order_by(File.current_path)
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            return list(session.scalars(stmt).all())

    def root_candidates(self) -> list[str]:
        """Return the parent directory of every known file (with duplicates).

        Keeping duplicates lets callers count how many files live under each
        parent and pick the most common one as the organisation root.
        """

        with self._db.session() as session:
            paths = session.scalars(select(File.current_path)).all()
        return [str(Path(path).parent) for path in paths]

    def counts(self) -> dict[str, int]:
        with self._db.session() as session:
            rows = session.execute(
                select(File.processing_status, func.count(File.id)).group_by(File.processing_status)
            ).all()
            return {status: count for status, count in rows}

    def stats(self, *, recent_limit: int = 8) -> DashboardStats:
        with self._db.session() as session:
            total = session.scalar(select(func.count(File.id))) or 0
            total_bytes = session.scalar(select(func.coalesce(func.sum(File.file_size), 0))) or 0
            counts = dict(
                session.execute(
                    select(File.processing_status, func.count(File.id)).group_by(File.processing_status)
                ).all()
            )
            duplicates = self._duplicate_count(session)
            categories = self._category_distribution(session)
            operations = self._recent_operations(session, recent_limit)
            return DashboardStats(
                total_files=total,
                total_bytes=int(total_bytes),
                analysed=counts.get(STATUS_ANALYSED, 0),
                pending_review=counts.get(STATUS_PENDING_REVIEW, 0),
                organised=counts.get(STATUS_ORGANISED, 0),
                failed=counts.get(STATUS_FAILED, 0),
                duplicates=duplicates,
                categories=categories,
                recent_operations=operations,
            )

    @staticmethod
    def _duplicate_count(session) -> int:  # type: ignore[no-untyped-def]
        subquery = (
            select(File.sha256_hash)
            .where(File.sha256_hash.is_not(None))
            .group_by(File.sha256_hash)
            .having(func.count(File.id) > 1)
            .subquery()
        )
        return session.scalar(select(func.count()).select_from(subquery)) or 0

    @staticmethod
    def _category_distribution(session) -> dict[str, int]:  # type: ignore[no-untyped-def]
        paths = category_path_map(session)
        rows = session.execute(
            select(DocumentAnalysis.category_id, func.count(DocumentAnalysis.file_id))
            .where(DocumentAnalysis.category_id.is_not(None))
            .group_by(DocumentAnalysis.category_id)
        ).all()
        distribution: dict[str, int] = {}
        for category_id, count in rows:
            label = paths.get(category_id, "Unclassified").split("/")[0]
            distribution[label] = distribution.get(label, 0) + count
        return distribution

    @staticmethod
    def _recent_operations(session, limit: int):  # type: ignore[no-untyped-def]
        from app.domain.models import OperationView

        rows = session.execute(
            select(Operation, File.current_name)
            .join(File, File.id == Operation.file_id)
            .order_by(Operation.id.desc())
            .limit(limit)
        ).all()
        return [
            OperationView(
                id=operation.id,
                file_id=operation.file_id,
                filename=filename,
                operation_type=operation.operation_type,
                source_path=operation.source_path,
                destination_path=operation.destination_path,
                status=operation.status,
                undoable=operation.undoable,
                created_at=operation.created_at,
                completed_at=operation.completed_at,
                error_message=operation.error_message,
            )
            for operation, filename in rows
        ]

    def duplicate_groups(self) -> list[dict[str, object]]:
        """Return groups of files sharing an identical SHA-256 hash."""

        with self._db.session() as session:
            hashes = session.execute(
                select(File.sha256_hash, func.count(File.id))
                .where(File.sha256_hash.is_not(None))
                .group_by(File.sha256_hash)
                .having(func.count(File.id) > 1)
            ).all()
            groups: list[dict[str, object]] = []
            for sha256, count in hashes:
                files = session.scalars(
                    select(File).where(File.sha256_hash == sha256).order_by(File.current_path)
                ).all()
                groups.append(
                    {
                        "sha256": sha256,
                        "count": count,
                        "files": [
                            {"id": record.id, "name": record.current_name, "path": record.current_path}
                            for record in files
                        ],
                    }
                )
            return groups
