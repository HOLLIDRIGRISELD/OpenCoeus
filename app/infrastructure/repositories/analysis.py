"""Repository for extracted content, analyses, suggestions, tags and embeddings."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.constants import (
    STATUS_ANALYSED,
    STATUS_FAILED,
    STATUS_ORGANISED,
    STATUS_PENDING_REVIEW,
)
from app.core.exceptions import DatabaseError
from app.domain.models import (
    ClassificationResult,
    DocumentChunk,
    DocumentProfile,
    ExtractionResult,
    FolderSuggestion,
    NamingSuggestion,
    SuggestionView,
    utcnow,
)
from app.infrastructure.database import Database
from app.infrastructure.models import (
    Category,
    DocumentAnalysis,
    DocumentChunkRecord,
    DocumentContent,
    Embedding,
    EmbeddingBlob,
    File,
    FileMeta,
    FileTag,
    Suggestion,
    Tag,
)
from app.infrastructure.repositories._helpers import category_path_map

IDF_CORPUS_MAX_TEXTS = 2000
IDF_CORPUS_CHARS_PER_TEXT = 2000
IDF_CORPUS_MAX_CHARS = 4_000_000


def limit_embedding_corpus(
    texts: Sequence[str],
    *,
    max_texts: int,
    max_chars_per_text: int,
    max_total_chars: int,
) -> list[str]:
    """Bound the IDF-fitting corpus so startup cost stays flat on large libraries."""

    limited: list[str] = []
    total = 0
    for text in texts:
        if not text or len(limited) >= max_texts:
            continue
        excerpt = text[:max_chars_per_text]
        if total + len(excerpt) > max_total_chars:
            continue
        limited.append(excerpt)
        total += len(excerpt)
    return limited


class AnalysisRepository:
    """Persists the output of extraction, classification and recommendation."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def ensure_category(self, path: str, *, description: str | None = None) -> int:
        """Return the id for ``path`` (e.g. ``Education/Assignments``), creating it."""

        parts = [part.strip() for part in path.split("/") if part.strip()]
        if not parts:
            parts = ["Unclassified"]
        with self._db.session() as session:
            parent_id: int | None = None
            for index, name in enumerate(parts):
                session.execute(
                    sqlite_insert(Category)
                    .values(
                        name=name,
                        parent_id=parent_id,
                        description=description if index == len(parts) - 1 else None,
                        created_at=utcnow(),
                    )
                    .on_conflict_do_nothing()
                )
                node = session.scalar(
                    select(Category).where(
                        Category.name == name,
                        Category.parent_id == parent_id if parent_id is not None else Category.parent_id.is_(None),
                    )
                )
                parent_id = node.id
            return parent_id or 0

    def category_descriptions(self) -> dict[str, str]:
        """Return ``{category_path: description}`` for classifier prompts."""

        with self._db.session() as session:
            paths = category_path_map(session)
            rows = session.execute(
                select(Category.id, Category.description).order_by(Category.id)
            ).all()
            return {
                paths.get(category_id, ""): description or ""
                for category_id, description in rows
                if paths.get(category_id)
            }

    def category_paths(self) -> list[str]:
        with self._db.session() as session:
            return sorted(category_path_map(session).values())

    def active_file_counts(self) -> dict[str, int]:
        """Return dashboard counts limited to files still present in the library."""

        active = File.is_available.is_(True)
        with self._db.session() as session:
            total = session.scalar(select(func.count(File.id)).where(active)) or 0
            total_bytes = (
                session.scalar(select(func.coalesce(func.sum(File.file_size), 0)).where(active)) or 0
            )
            counts = dict(
                session.execute(
                    select(File.processing_status, func.count(File.id))
                    .where(active)
                    .group_by(File.processing_status)
                ).all()
            )
            duplicates_subquery = (
                select(File.sha256_hash)
                .where(active, File.sha256_hash.is_not(None))
                .group_by(File.sha256_hash)
                .having(func.count(File.id) > 1)
                .subquery()
            )
            duplicates = session.scalar(select(func.count()).select_from(duplicates_subquery)) or 0
            return {
                "total": int(total),
                "total_bytes": int(total_bytes),
                "analysed": counts.get(STATUS_ANALYSED, 0),
                "pending_review": counts.get(STATUS_PENDING_REVIEW, 0),
                "organised": counts.get(STATUS_ORGANISED, 0),
                "failed": counts.get(STATUS_FAILED, 0),
                "duplicates": int(duplicates),
            }

    def embedding_corpus(self) -> list[str]:
        """Return a bounded sample of document text and labels for IDF fitting."""

        descriptions = [value for value in self.category_descriptions().values() if value]
        with self._db.session() as session:
            texts = session.scalars(
                select(func.substr(DocumentContent.text, 1, IDF_CORPUS_CHARS_PER_TEXT))
                .join(File, File.id == DocumentContent.file_id)
                .where(
                    func.lower(File.extension).notin_((".svg", ".eps")),
                    DocumentContent.text.is_not(None),
                    DocumentContent.text != "",
                )
                .order_by(File.id)
                .limit(IDF_CORPUS_MAX_TEXTS)
            ).all()
        return limit_embedding_corpus(
            descriptions + list(texts),
            max_texts=IDF_CORPUS_MAX_TEXTS,
            max_chars_per_text=IDF_CORPUS_CHARS_PER_TEXT,
            max_total_chars=IDF_CORPUS_MAX_CHARS,
        )

    def save_extraction(
        self,
        file_id: int,
        result: ExtractionResult,
        chunks: list[DocumentChunk],
    ) -> None:
        """Store extracted text, quality indicators and chunk records."""

        with self._db.session() as session:
            content = session.scalar(select(DocumentContent).where(DocumentContent.file_id == file_id))
            if content is None:
                content = DocumentContent(file_id=file_id)
                session.add(content)
            content.text = result.text
            content.char_count = result.char_count
            content.extraction_method = result.method
            content.status = "completed" if result.success else "failed"
            content.quality = result.quality
            content.warnings = result.warnings
            content.error = result.error
            content.extracted_at = utcnow()

            session.execute(delete(DocumentChunkRecord).where(DocumentChunkRecord.file_id == file_id))
            if chunks:
                session.execute(
                    insert(DocumentChunkRecord),
                    [
                        {
                            "file_id": file_id,
                            "chunk_index": chunk.index,
                            "text": chunk.text,
                            "page": chunk.page,
                            "heading": chunk.heading,
                            "token_estimate": chunk.token_estimate,
                        }
                        for chunk in chunks
                    ],
                )

            meta = session.scalar(select(FileMeta).where(FileMeta.file_id == file_id))
            if result.title or result.author or result.page_count:
                if meta is None:
                    meta = FileMeta(file_id=file_id)
                    session.add(meta)
                meta.title = result.title or meta.title
                meta.author = result.author or meta.author
                meta.page_count = result.page_count or meta.page_count
            session.flush()

    def content_for(self, file_id: int) -> str:
        with self._db.session() as session:
            content = session.scalar(select(DocumentContent).where(DocumentContent.file_id == file_id))
            return content.text if content else ""

    def chunks_for(self, file_id: int) -> list[DocumentChunk]:
        with self._db.session() as session:
            records = session.scalars(
                select(DocumentChunkRecord)
                .where(DocumentChunkRecord.file_id == file_id)
                .order_by(DocumentChunkRecord.chunk_index)
            ).all()
            return [
                DocumentChunk(
                    index=record.chunk_index,
                    text=record.text,
                    page=record.page,
                    heading=record.heading,
                )
                for record in records
            ]

    def save_analysis(
        self,
        file_id: int,
        profile: DocumentProfile,
        classification: ClassificationResult,
        *,
        rule_decision: str | None = None,
        accepted_name: str | None = None,
    ) -> int:
        """Store a new analysis row; previous analyses are retained for history."""

        category_id = self.ensure_category(classification.category_path or classification.primary_category)
        extra = {
            "scores": classification.scores,
            "tags": classification.tags,
            "needs_review": classification.needs_review,
            "extracted_evidence": profile.extracted_evidence,
            "inferred_evidence": profile.inferred_evidence,
        }
        if rule_decision:
            extra["rule_decision"] = rule_decision
        if accepted_name:
            extra["accepted_name"] = accepted_name
        with self._db.session() as session:
            analysis = DocumentAnalysis(
                file_id=file_id,
                category_id=category_id,
                document_title=profile.title,
                document_type=profile.document_type,
                organisation=profile.organisation,
                document_date=profile.document_date,
                summary=profile.summary,
                confidence_score=classification.confidence,
                classification_method=classification.method,
                model_name=classification.model_name,
                model_version=classification.model_version,
                evidence=classification.evidence,
                uncertainties=profile.uncertainties,
                extra=extra,
                analysis_status="completed",
            )
            session.add(analysis)
            session.flush()
            return analysis.id

    def category_map(self) -> dict[int, str]:
        with self._db.session() as session:
            return category_path_map(session)

    def latest_analysis(
        self, file_id: int, *, paths: dict[int, str] | None = None
    ) -> ClassificationResult | None:
        with self._db.session() as session:
            analysis = session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id == file_id)
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            ).first()
            if analysis is None:
                return None
            if paths is None:
                paths = category_path_map(session)
            path = paths.get(analysis.category_id or 0, "Unclassified")
            primary, _, secondary = path.partition("/")
            return ClassificationResult(
                primary_category=primary,
                secondary_category=secondary or None,
                category_path=path,
                confidence=analysis.confidence_score or 0.0,
                method=analysis.classification_method,
                tags=list((analysis.extra or {}).get("tags", [])),
                evidence=list(analysis.evidence or []),
                scores=dict((analysis.extra or {}).get("scores", {})),
                model_name=analysis.model_name,
                model_version=analysis.model_version,
                needs_review=bool((analysis.extra or {}).get("needs_review", False)),
            )

    def categories_for_files(self, file_ids: list[int]) -> dict[int, str]:
        """Return ``{file_id: category_path}`` for the latest analysis of each file."""

        if not file_ids:
            return {}
        with self._db.session() as session:
            paths = category_path_map(session)
            rows = session.execute(
                select(DocumentAnalysis.file_id, DocumentAnalysis.category_id)
                .where(DocumentAnalysis.file_id.in_(file_ids))
                .order_by(DocumentAnalysis.file_id, DocumentAnalysis.id.desc())
            ).all()
            result: dict[int, str] = {}
            for file_id, category_id in rows:
                result.setdefault(file_id, paths.get(category_id or 0, "Unclassified"))
            return result

    def save_suggestions(
        self,
        file_id: int,
        naming: NamingSuggestion,
        folder: FolderSuggestion,
        *,
        category_path: str,
        original_directory: Path | None = None,
    ) -> tuple[int, int]:
        """Supersede previous active suggestions and store the new ones.

        Accepted suggestions must be superseded too: deleting only pending rows
        leaves an older accepted filename suggestion active, so a re-analysis
        produces two competing suggestions for the same file.
        """

        with self._db.session() as session:
            session.execute(
                update(Suggestion)
                .where(
                    Suggestion.file_id == file_id,
                    Suggestion.status.in_(["pending", "accepted"]),
                    Suggestion.suggestion_type.in_(["filename", "destination", "category"]),
                )
                .values(status="superseded", reviewed_at=utcnow())
            )
            filename_suggestion = Suggestion(
                file_id=file_id,
                suggestion_type="filename",
                original_value=naming.original_name,
                suggested_value=naming.suggested_name,
                confidence_score=naming.confidence,
                explanation=naming.explanation,
                evidence=naming.evidence,
                warnings=naming.warnings,
                template=naming.template,
                status="pending",
            )
            destination_suggestion = Suggestion(
                file_id=file_id,
                suggestion_type="destination",
                original_value=str(original_directory) if original_directory else None,
                suggested_value=folder.relative_destination.as_posix(),
                confidence_score=folder.confidence,
                explanation=folder.explanation,
                evidence=folder.evidence,
                status="pending",
            )
            category_suggestion = Suggestion(
                file_id=file_id,
                suggestion_type="category",
                original_value=None,
                suggested_value=category_path,
                confidence_score=folder.confidence,
                explanation=folder.explanation,
                evidence=folder.evidence,
                status="pending",
            )
            session.add_all([filename_suggestion, destination_suggestion, category_suggestion])
            session.flush()
            return filename_suggestion.id, destination_suggestion.id

    def pending_suggestions(self, *, limit: int = 500) -> list[SuggestionView]:
        """Return filename suggestions joined with their file and destination."""

        with self._db.session() as session:
            latest = (
                select(
                    Suggestion.file_id.label("file_id"),
                    func.max(Suggestion.id).label("suggestion_id"),
                )
                .where(
                    Suggestion.suggestion_type == "filename",
                    Suggestion.status.in_(["pending", "accepted"]),
                )
                .group_by(Suggestion.file_id)
                .subquery()
            )
            rows = session.execute(
                select(Suggestion, File)
                .join(File, File.id == Suggestion.file_id)
                .join(latest, latest.c.suggestion_id == Suggestion.id)
                .where(Suggestion.status.in_(["pending", "accepted"]))
                .order_by(Suggestion.confidence_score.desc().nullslast())
                .limit(limit)
            ).all()
            file_ids = [file.id for _, file in rows]
            destination_map = self._destination_map(session, file_ids)
            category_map = self._category_suggestion_map(session, file_ids)
            return [
                SuggestionView(
                    id=suggestion.id,
                    file_id=file.id,
                    filename=file.current_name,
                    path=file.current_path,
                    suggestion_type=suggestion.suggestion_type,
                    original_value=suggestion.original_value,
                    suggested_value=suggestion.suggested_value,
                    confidence=suggestion.confidence_score,
                    explanation=suggestion.explanation,
                    evidence=list(suggestion.evidence or []),
                    warnings=list(suggestion.warnings or []),
                    status=suggestion.status,
                    category=category_map.get(file.id),
                    destination=destination_map.get(file.id),
                )
                for suggestion, file in rows
            ]

    def pending_suggestion_count(self) -> int:
        """Count the same latest filename suggestions as :meth:`pending_suggestions`."""

        with self._db.session() as session:
            latest = (
                select(
                    Suggestion.file_id.label("file_id"),
                    func.max(Suggestion.id).label("suggestion_id"),
                )
                .where(
                    Suggestion.suggestion_type == "filename",
                    Suggestion.status.in_(["pending", "accepted"]),
                )
                .group_by(Suggestion.file_id)
                .subquery()
            )
            total = session.scalar(
                select(func.count())
                .select_from(Suggestion)
                .join(latest, latest.c.suggestion_id == Suggestion.id)
                .where(Suggestion.status.in_(["pending", "accepted"]))
            )
            return int(total or 0)

    @staticmethod
    def _destination_map(session, file_ids: list[int]) -> dict[int, str]:  # type: ignore[no-untyped-def]
        if not file_ids:
            return {}
        rows = session.execute(
            select(Suggestion.file_id, Suggestion.suggested_value, Suggestion.id)
            .where(
                Suggestion.file_id.in_(file_ids),
                Suggestion.suggestion_type == "destination",
                Suggestion.status.in_(["pending", "accepted"]),
            )
            .order_by(Suggestion.id.desc())
        ).all()
        result: dict[int, str] = {}
        for file_id, value, _ in rows:
            result.setdefault(file_id, value)
        return result

    @staticmethod
    def _category_suggestion_map(session, file_ids: list[int]) -> dict[int, str]:  # type: ignore[no-untyped-def]
        if not file_ids:
            return {}
        rows = session.execute(
            select(Suggestion.file_id, Suggestion.suggested_value, Suggestion.id)
            .where(
                Suggestion.file_id.in_(file_ids),
                Suggestion.suggestion_type == "category",
                Suggestion.status.in_(["pending", "accepted"]),
            )
            .order_by(Suggestion.id.desc())
        ).all()
        result: dict[int, str] = {}
        for file_id, value, _ in rows:
            result.setdefault(file_id, value)
        return result

    def accepted_filenames(self, file_ids: Sequence[int]) -> dict[int, str]:
        """Return the durable accepted filename for each requested file."""

        if not file_ids:
            return {}
        with self._db.session() as session:
            rows = session.execute(
                select(DocumentAnalysis.file_id, DocumentAnalysis.extra)
                .where(DocumentAnalysis.file_id.in_(file_ids))
                .order_by(DocumentAnalysis.id.desc())
            ).all()
        result: dict[int, str] = {}
        for file_id, extra in rows:
            if file_id not in result and extra and extra.get("accepted_name"):
                result[file_id] = str(extra["accepted_name"])
        return result

    def record_accepted_filename(self, file_id: int, filename: str) -> None:
        """Persist a user filename choice across later re-analyses."""

        with self._db.session() as session:
            analysis = session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id == file_id)
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            ).first()
            if analysis is None:
                return
            extra = dict(analysis.extra or {})
            extra["accepted_name"] = filename
            analysis.extra = extra

    def suggestions_for_file(self, file_id: int) -> dict[str, Suggestion]:
        """Return the latest filename/destination suggestions for one file."""

        with self._db.session() as session:
            rows = session.scalars(
                select(Suggestion)
                .where(Suggestion.file_id == file_id, Suggestion.status.in_(["pending", "accepted"]))
                .order_by(Suggestion.id.desc())
            ).all()
            result: dict[str, Suggestion] = {}
            for suggestion in rows:
                result.setdefault(suggestion.suggestion_type, suggestion)
            for suggestion in result.values():
                session.expunge(suggestion)
            return result

    def set_suggestion_status(self, suggestion_id: int, status: str) -> None:
        with self._db.session() as session:
            suggestion = session.get(Suggestion, suggestion_id)
            if suggestion is None:
                raise DatabaseError(f"Suggestion {suggestion_id} does not exist.")
            suggestion.status = status
            suggestion.reviewed_at = utcnow()

    def suggestion_status(self, suggestion_id: int) -> str | None:
        """Return the current status of a suggestion, or ``None`` if missing."""

        with self._db.session() as session:
            suggestion = session.get(Suggestion, suggestion_id)
            return suggestion.status if suggestion is not None else None

    def set_suggestion_status_for_file(self, file_id: int, status: str) -> None:
        with self._db.session() as session:
            for suggestion in session.scalars(
                select(Suggestion).where(
                    Suggestion.file_id == file_id,
                    Suggestion.status.in_(["pending", "accepted"]),
                )
            ):
                suggestion.status = status
                suggestion.reviewed_at = utcnow()

    def suggestion_ids_for_file(self, file_id: int) -> dict[str, int]:
        """Return the latest suggestion id per type for a file."""

        with self._db.session() as session:
            rows = session.scalars(
                select(Suggestion)
                .where(Suggestion.file_id == file_id)
                .order_by(Suggestion.id.desc())
            ).all()
            ids: dict[str, int] = {}
            for suggestion in rows:
                ids.setdefault(suggestion.suggestion_type, suggestion.id)
            return ids

    def update_suggestion(
        self,
        suggestion_id: int,
        *,
        value: str | None = None,
        status: str | None = None,
        explanation: str | None = None,
        evidence: list[str] | None = None,
        warnings: list[str] | None = None,
        confidence: float | None = None,
    ) -> bool:
        """Update a suggestion in place. Returns ``False`` when it is missing."""

        with self._db.session() as session:
            suggestion = session.get(Suggestion, suggestion_id)
            if suggestion is None:
                return False
            if value is not None:
                suggestion.suggested_value = value
            if status is not None:
                suggestion.status = status
                suggestion.reviewed_at = utcnow()
            if explanation is not None:
                suggestion.explanation = explanation
            if evidence is not None:
                suggestion.evidence = list(evidence)
            if warnings is not None:
                suggestion.warnings = list(warnings)
            if confidence is not None:
                suggestion.confidence_score = round(float(confidence), 3)
            return True

    def override_category(self, file_id: int, category_path: str, *, note: str) -> None:
        """Record a human category decision on the latest analysis row."""

        category_id = self.ensure_category(category_path)
        with self._db.session() as session:
            analysis = session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id == file_id)
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            ).first()
            if analysis is None:
                raise DatabaseError(f"File {file_id} has no analysis to override.")
            analysis.category_id = category_id
            analysis.confidence_score = 1.0
            analysis.classification_method = "manual"
            analysis.evidence = list(analysis.evidence or []) + [note]
            analysis.uncertainties = [
                item
                for item in (analysis.uncertainties or [])
                if "review threshold" not in item.lower()
            ]
            extra = dict(analysis.extra or {})
            extra["manual_override"] = True
            analysis.extra = extra

    def analysis_detail(self, file_id: int) -> dict[str, object]:
        """Return the fields needed to explain a recommendation."""

        with self._db.session() as session:
            analysis = session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id == file_id)
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            ).first()
            if analysis is None:
                return {}
            category = category_path_map(session).get(analysis.category_id or 0)
            return {
                "title": analysis.document_title,
                "document_type": analysis.document_type,
                "organisation": analysis.organisation,
                "document_date": analysis.document_date,
                "summary": analysis.summary,
                "category": category,
                "confidence": analysis.confidence_score,
                "method": analysis.classification_method,
                "evidence": list(analysis.evidence or []),
                "uncertainties": list(analysis.uncertainties or []),
                "tags": list((analysis.extra or {}).get("tags", [])),
                "extracted_evidence": list((analysis.extra or {}).get("extracted_evidence", [])),
                "inferred_evidence": list((analysis.extra or {}).get("inferred_evidence", [])),
            }

    def get_suggestion_bundle(self, file_id: int) -> dict[str, object] | None:
        """Return filename/destination suggestions plus file data for planning."""

        from app.infrastructure.repositories.files import FileRepository

        file_data = FileRepository(self._db).get_record(file_id)
        if file_data is None:
            return None
        with self._db.session() as session:
            filename = session.scalars(
                select(Suggestion)
                .where(
                    Suggestion.file_id == file_id,
                    Suggestion.suggestion_type == "filename",
                    Suggestion.status.in_(["pending", "accepted"]),
                )
                .order_by(Suggestion.id.desc())
                .limit(1)
            ).first()
            destination = session.scalars(
                select(Suggestion)
                .where(
                    Suggestion.file_id == file_id,
                    Suggestion.suggestion_type == "destination",
                    Suggestion.status.in_(["pending", "accepted"]),
                )
                .order_by(Suggestion.id.desc())
                .limit(1)
            ).first()
            return {
                "file": file_data,
                "filename_suggestion": {
                    "id": filename.id if filename else None,
                    "value": filename.suggested_value if filename else None,
                    "confidence": filename.confidence_score if filename else None,
                    "explanation": filename.explanation if filename else None,
                },
                "destination_suggestion": {
                    "id": destination.id if destination else None,
                    "value": destination.suggested_value if destination else None,
                    "confidence": destination.confidence_score if destination else None,
                    "explanation": destination.explanation if destination else None,
                },
            }

    def set_tags(self, file_id: int, tags: list[str], *, source: str = "ai") -> None:
        cleaned = sorted({tag.strip()[:80] for tag in tags if tag.strip()})
        with self._db.session() as session:
            if session.get(File, file_id) is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            existing = session.execute(
                select(Tag.id, Tag.name).join(FileTag, FileTag.tag_id == Tag.id).where(FileTag.file_id == file_id)
            ).all()
            stale_ids = [tag_id for tag_id, name in existing if name not in cleaned]
            if stale_ids:
                session.execute(
                    delete(FileTag).where(
                        FileTag.file_id == file_id,
                        FileTag.tag_id.in_(stale_ids),
                    )
                )

            known: dict[str, int] = {}
            if cleaned:
                session.execute(
                    sqlite_insert(Tag)
                    .values([{"name": name} for name in cleaned])
                    .on_conflict_do_nothing()
                )
                rows = session.execute(select(Tag.id, Tag.name).where(Tag.name.in_(cleaned))).all()
                known = {name: tag_id for tag_id, name in rows}

            present = set(session.execute(
                select(FileTag.tag_id).where(FileTag.file_id == file_id)
            ).scalars().all())
            links = [
                {"file_id": file_id, "tag_id": known[name], "source": source}
                for name in cleaned
                if known[name] not in present
            ]
            if links:
                session.execute(insert(FileTag), links)
            session.flush()

    def delete_tags(self, file_id: int) -> None:
        with self._db.session() as session:
            if session.get(File, file_id) is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            session.execute(delete(FileTag).where(FileTag.file_id == file_id))

    def save_embeddings(self, file_id: int, model_name: str, vectors: list[np.ndarray]) -> None:
        """Replace all embeddings for a file/model pair.

        Args:
            file_id: File whose chunks are being indexed.
            model_name: Embedding model identity (including version).
            vectors: One vector per stored chunk, in chunk order.
        """

        if not vectors:
            return
        with self._db.session() as session:
            chunks = session.scalars(
                select(DocumentChunkRecord.id)
                .where(DocumentChunkRecord.file_id == file_id)
                .order_by(DocumentChunkRecord.chunk_index)
            ).all()
            if len(chunks) != len(vectors):
                raise DatabaseError(
                    f"Chunk/vector mismatch for file {file_id}: {len(chunks)} chunks, {len(vectors)} vectors"
                )
            session.execute(
                delete(EmbeddingBlob).where(
                    EmbeddingBlob.file_id == file_id, EmbeddingBlob.model_name == model_name
                )
            )
            session.execute(
                insert(EmbeddingBlob),
                [
                    {
                        "file_id": file_id,
                        "chunk_id": chunk_id,
                        "model_name": model_name,
                        "dimension": int(vector.shape[0]),
                        "vector": np.asarray(vector, dtype="<f8").tobytes(),
                        "created_at": utcnow(),
                    }
                    for chunk_id, vector in zip(chunks, vectors, strict=True)
                ],
            )

    def clone_analysis(self, source_id: int, target_id: int) -> bool:
        """Copy a finished analysis to a byte-identical file.

        The copy replaces any stale analysis data on ``target_id`` in one
        transaction. Suggestions are deliberately *not* copied: naming and
        destination depend on the target's own filename and path and are
        regenerated by the analysis service.
        """

        with self._db.session() as session:
            source_analysis = session.scalars(
                select(DocumentAnalysis)
                .where(DocumentAnalysis.file_id == source_id)
                .order_by(DocumentAnalysis.id.desc())
                .limit(1)
            ).first()
            if source_analysis is None:
                return False

            source_content = session.scalar(
                select(DocumentContent).where(DocumentContent.file_id == source_id)
            )
            source_chunks = session.scalars(
                select(DocumentChunkRecord)
                .where(DocumentChunkRecord.file_id == source_id)
                .order_by(DocumentChunkRecord.chunk_index)
            ).all()
            source_embeddings = session.scalars(
                select(EmbeddingBlob).where(EmbeddingBlob.file_id == source_id)
            ).all()
            source_legacy_embeddings = session.scalars(
                select(Embedding).where(Embedding.file_id == source_id)
            ).all()
            source_meta = session.scalar(select(FileMeta).where(FileMeta.file_id == source_id))
            source_status = session.scalar(select(File.processing_status).where(File.id == source_id))
            source_tags = session.execute(
                select(Tag.name, FileTag.source)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .where(FileTag.file_id == source_id)
            ).all()

            for entity in (
                EmbeddingBlob,
                Embedding,
                DocumentChunkRecord,
                DocumentContent,
                DocumentAnalysis,
                Suggestion,
                FileTag,
                FileMeta,
            ):
                session.execute(delete(entity).where(entity.file_id == target_id))

            if source_content is not None:
                session.add(
                    DocumentContent(
                        file_id=target_id,
                        text=source_content.text,
                        char_count=source_content.char_count,
                        extraction_method=source_content.extraction_method,
                        extractor_version=source_content.extractor_version,
                        status=source_content.status,
                        quality=source_content.quality,
                        warnings=list(source_content.warnings or []),
                        error=source_content.error,
                        extracted_at=source_content.extracted_at,
                    )
                )

            chunk_ids: dict[int, int] = {}
            for chunk in source_chunks:
                copy = DocumentChunkRecord(
                    file_id=target_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    page=chunk.page,
                    heading=chunk.heading,
                    token_estimate=chunk.token_estimate,
                )
                session.add(copy)
                session.flush()
                chunk_ids[chunk.id] = copy.id

            for vector_row in source_embeddings:
                session.add(
                    EmbeddingBlob(
                        file_id=target_id,
                        chunk_id=chunk_ids.get(vector_row.chunk_id),
                        model_name=vector_row.model_name,
                        dimension=vector_row.dimension,
                        vector=vector_row.vector,
                        created_at=vector_row.created_at,
                    )
                )
            for vector_row in source_legacy_embeddings:
                session.add(
                    Embedding(
                        file_id=target_id,
                        chunk_id=chunk_ids.get(vector_row.chunk_id),
                        model_name=vector_row.model_name,
                        dimension=vector_row.dimension,
                        vector=list(vector_row.vector),
                        created_at=vector_row.created_at,
                    )
                )

            if source_meta is not None:
                session.add(
                    FileMeta(
                        file_id=target_id,
                        title=source_meta.title,
                        author=source_meta.author,
                        page_count=source_meta.page_count,
                        language=source_meta.language,
                        extra=dict(source_meta.extra or {}),
                    )
                )

            session.add(
                DocumentAnalysis(
                    file_id=target_id,
                    category_id=source_analysis.category_id,
                    document_title=source_analysis.document_title,
                    document_type=source_analysis.document_type,
                    organisation=source_analysis.organisation,
                    document_date=source_analysis.document_date,
                    summary=source_analysis.summary,
                    confidence_score=source_analysis.confidence_score,
                    classification_method=source_analysis.classification_method,
                    model_name=source_analysis.model_name,
                    model_version=source_analysis.model_version,
                    evidence=list(source_analysis.evidence or []),
                    uncertainties=list(source_analysis.uncertainties or []),
                    extra={
                        **{
                            key: value
                            for key, value in (source_analysis.extra or {}).items()
                            if key != "accepted_name"
                        },
                        "needs_review": (source_analysis.extra or {}).get(
                            "needs_review", source_status == STATUS_PENDING_REVIEW
                        ),
                    },
                    analysis_status=source_analysis.analysis_status,
                    created_at=source_analysis.created_at,
                )
            )

            for name, source in source_tags:
                tag = session.scalar(select(Tag).where(Tag.name == name))
                if tag is not None:
                    session.add(FileTag(file_id=target_id, tag_id=tag.id, source=source))
            return True

    def mean_document_vector(self, file_id: int, model_name: str) -> np.ndarray | None:
        """Return the normalised mean of a file's stored chunk vectors."""

        with self._db.session() as session:
            rows = session.scalars(
                select(EmbeddingBlob.vector).where(
                    EmbeddingBlob.file_id == file_id, EmbeddingBlob.model_name == model_name
                )
            ).all()
            if not rows:
                legacy = session.scalars(
                    select(Embedding.vector).where(
                        Embedding.file_id == file_id, Embedding.model_name == model_name
                    )
                ).all()
                rows = [np.asarray(value, dtype="<f8").tobytes() for value in legacy]
        if not rows:
            return None
        mean = np.mean([np.frombuffer(value, dtype="<f8") for value in rows], axis=0)
        norm = float(np.linalg.norm(mean))
        return mean / norm if norm > 0 else None

    def iter_embeddings(self, model_name: str) -> Iterator[tuple[int, np.ndarray, str]]:
        """Stream every ``(file_id, vector, chunk_text)`` row for a model."""

        with self._db.session() as session:
            rows = session.execute(
                select(EmbeddingBlob.file_id, EmbeddingBlob.vector, DocumentChunkRecord.text)
                .join(DocumentChunkRecord, DocumentChunkRecord.id == EmbeddingBlob.chunk_id)
                .where(EmbeddingBlob.model_name == model_name)
                .order_by(EmbeddingBlob.file_id, EmbeddingBlob.chunk_id)
            ).yield_per(1000)
            blob_files: set[int] = set()
            for file_id, vector, text in rows:
                blob_files.add(file_id)
                yield file_id, np.frombuffer(vector, dtype="<f8"), text or ""

            legacy = session.execute(
                select(Embedding.file_id, Embedding.vector, DocumentChunkRecord.text)
                .join(DocumentChunkRecord, DocumentChunkRecord.id == Embedding.chunk_id)
                .where(Embedding.model_name == model_name)
                .order_by(Embedding.file_id, Embedding.chunk_id)
            ).yield_per(1000)
            for file_id, vector, text in legacy:
                if file_id not in blob_files:
                    yield file_id, np.asarray(vector, dtype=np.float32), text or ""

    def load_embeddings(self, model_name: str) -> list[tuple[int, np.ndarray, str]]:
        """Return all stored chunk vectors for a model."""

        return sorted(self.iter_embeddings(model_name), key=lambda row: row[0])

    def delete_embeddings(self, file_id: int, model_name: str | None = None) -> None:
        with self._db.session() as session:
            if session.get(File, file_id) is None:
                raise DatabaseError(f"File {file_id} does not exist.")
            for entity in (EmbeddingBlob, Embedding):
                stmt = delete(entity).where(entity.file_id == file_id)
                if model_name:
                    stmt = stmt.where(entity.model_name == model_name)
                session.execute(stmt)

