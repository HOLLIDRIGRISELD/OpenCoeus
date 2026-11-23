"""Analysis pipeline: extract → chunk → embed → classify → recommend.

The service orchestrates the deterministic and statistical parts of OpenCoeus.
Every stage degrades gracefully: a missing extractor, embedding backend or local
language model produces a lower-confidence suggestion rather than a crash, and
the reason is recorded as evidence/uncertainty so the UI can explain it.
"""

from __future__ import annotations

import contextlib
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from app.core.config import AppConfig
from app.core.constants import (
    CHUNKER_VERSION,
    CLASSIFIER_VERSION,
    STATUS_ANALYSED,
    STATUS_ANALYSING,
    STATUS_DISCOVERED,
    STATUS_EXTRACTED,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_PENDING_ANALYSIS,
    STATUS_PENDING_REVIEW,
    STATUS_UNAVAILABLE,
    STATUS_UNSUPPORTED,
    UNCLASSIFIED,
)
from app.core.exceptions import (
    DatabaseError,
    ExtractionError,
    FileAccessError,
    UnsupportedFormatError,
)
from app.core.logging_config import get_logger
from app.core.progress import CancellationToken, ProgressCallback, emit
from app.domain.models import (
    ClassificationResult,
    DocumentChunk,
    DocumentProfile,
    ExtractionResult,
    NamingSuggestion,
)
from app.infrastructure.database import Database
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.infrastructure.repositories.caches import AnalysisCacheRepository
from app.infrastructure.repositories.files import FileRepository
from app.intelligence.classifier import HybridClassifier
from app.intelligence.content_naming import resolve_suggestion
from app.intelligence.conventions import apply_convention, detect_convention
from app.intelligence.embeddings import EmbeddingEngine, mean_vector
from app.intelligence.entities import (
    extract_date,
    extract_document_type,
    extract_organisation,
    extract_title,
)
from app.intelligence.folder_recommender import FolderRecommender, existing_relative_folders
from app.intelligence.keywords import extract_keywords
from app.intelligence.llm import LocalLLMClient
from app.intelligence.llm_policy import should_use_llm
from app.intelligence.naming_engine import NamingEngine
from app.intelligence.summarisation import extractive_summary
from app.processing.chunking import chunk_text
from app.processing.extractors import ExtractorRegistry
from app.processing.file_signature import inspect_format
from app.processing.hashing import sha256_file, sha256_text
from app.search.indexer import SearchIndexer
from app.services.common import ServiceReport
from app.services.settings_service import SettingsService

logger = get_logger(__name__)

_LLM_FAILURE_COOLDOWN_SECONDS = 30.0

FOLDER_CACHE_LIMIT = 20
EXTRACTION_WORKERS = 4
EXTRACTION_PREFETCH = 32

PreparedExtraction = tuple[str, ExtractionResult, list[DocumentChunk]]
PreparationJob = tuple[Path, str, str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """Batch-scoped snapshot used by every per-file naming and folder decision."""

    naming_template: str
    use_conventions: bool
    low_confidence: float
    high_confidence: float
    embedding_model: str
    prefer_transformer: bool
    organisation_root: Path | None
    feedback_present: bool

    def cache_signature(self, use_llm: bool, cache_available: bool) -> tuple[str, bool]:
        enabled = cache_available and not use_llm and not self.feedback_present
        parts = (
            CHUNKER_VERSION,
            self.embedding_model,
            str(self.prefer_transformer),
            CLASSIFIER_VERSION,
            str(self.low_confidence),
            str(self.high_confidence),
        )
        return "|".join(parts), enabled


@dataclass(slots=True)
class AnalysisOutcome:
    """Result of analysing a single file."""

    file_id: int
    status: str
    category_path: str | None = None
    confidence: float | None = None
    needs_review: bool = False
    llm_used: bool = False
    skipped: bool = False
    error: str | None = None


@dataclass(slots=True)
class AnalysisReport(ServiceReport):
    """Batch analysis counters."""

    analysed: int = 0
    pending_review: int = 0
    llm_used: int = 0
    cancelled: bool = False
    errors: list[tuple[str, str]] = field(default_factory=list)


class AnalysisService:
    """Runs the document-understanding pipeline."""

    def __init__(
        self,
        *,
        config: AppConfig,
        db: Database,
        files: FileRepository,
        analyses: AnalysisRepository,
        indexer: SearchIndexer,
        extractors: ExtractorRegistry,
        embeddings: EmbeddingEngine,
        llm: LocalLLMClient,
        naming: NamingEngine,
        folders: FolderRecommender,
        settings: SettingsService,
        classifier_provider: Callable[[], HybridClassifier],
        root_provider: Callable[[], Path | None],
        analysis_cache: AnalysisCacheRepository | None = None,
        feedback_provider: Callable[[], bool] | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._files = files
        self._analyses = analyses
        self._indexer = indexer
        self._extractors = extractors
        self._embeddings = embeddings
        self._llm = llm
        self._naming = naming
        self._folders = folders
        self._settings = settings
        self._classifier_provider = classifier_provider
        self._root_provider = root_provider
        self._analysis_cache = analysis_cache
        self._feedback_provider = feedback_provider
        self._llm_state: bool | None = None
        self._llm_failed_at: float | None = None
        self._llm_runtime: tuple[str, str, bool] | None = None

    def analyse_pending(
        self,
        *,
        limit: int | None = None,
        use_llm: bool = True,
        force: bool = False,
        reuse_duplicates: bool = True,
        progress: ProgressCallback | None = None,
        cancel: CancellationToken | None = None,
    ) -> AnalysisReport:
        started = time.perf_counter()
        report = AnalysisReport()

        statuses = [
            STATUS_DISCOVERED,
            STATUS_PENDING_ANALYSIS,
            STATUS_EXTRACTED,
            STATUS_FAILED,
        ]
        if force:
            statuses = [
                STATUS_DISCOVERED,
                STATUS_PENDING_ANALYSIS,
                STATUS_EXTRACTED,
                STATUS_FAILED,
                STATUS_ANALYSED,
                STATUS_PENDING_REVIEW,
            ]

        with self._db.batch():
            file_ids = self._files.ids_by_status(statuses, limit=limit)
            report.total = len(file_ids)
            if not file_ids:
                report.duration_seconds = round(time.perf_counter() - started, 3)
                return report

            manual_names = self._analyses.accepted_filenames(file_ids)
            folder_cache: dict[Path, set[Path]] = {}
            name_cache: dict[Path, set[str]] = {}
            reserved_names: set[str] = set()
            records = self._files.light_records(file_ids)
            cache_keys = self._analysis_cache.all_keys() if self._analysis_cache is not None else set()
            duplicate_sources = self._files.find_analysed_duplicates(
                file_ids,
                {file_id: str(record.get("hash") or "") for file_id, record in records.items()},
            )
            batch_settings = self._batch_settings()
            cache_signature = batch_settings.cache_signature(use_llm, self._analysis_cache is not None)
            category_map = self._analyses.category_map()
            category_paths = sorted(category_map.values())
        queue: deque[tuple[int, Future[PreparedExtraction] | None, int]] = deque()
        seen_hashes: set[str] = set()
        duplicate_candidates: set[int] = set()

        def process(entry: tuple[int, Future[PreparedExtraction] | None, int]) -> None:
            file_id, future, index = entry
            if cancel is not None:
                cancel.raise_if_cancelled()
            prepared: PreparedExtraction | None = None
            try:
                if future is not None:
                    prepared = future.result()
                outcome = self.analyse_file(
                    file_id,
                    use_llm=use_llm,
                    folder_cache=folder_cache,
                    reuse_duplicates=reuse_duplicates and not force,
                    force=force,
                    prepared=prepared,
                    cache_signature=cache_signature,
                    category_map=category_map,
                    category_paths=category_paths,
                    reserved_names=reserved_names,
                    settings=batch_settings,
                    name_cache=name_cache,
                    manual_names=manual_names,
                    record=records.get(file_id),
                    cache_keys=cache_keys,
                    duplicate_sources=duplicate_sources,
                    duplicate_candidates=duplicate_candidates,
                )
            except Exception as exc:
                logger.exception("Unexpected analysis failure for file %s", file_id)
                with contextlib.suppress(DatabaseError):
                    self._files.update_status(file_id, STATUS_FAILED)
                report.failed += 1
                report.errors.append((str(file_id), str(exc)))
                emit(progress, "analyse", index, len(file_ids), f"Analysed {index} of {len(file_ids)}")
                return

            if outcome.error:
                report.failed += 1
                report.errors.append((str(file_id), outcome.error))
            elif outcome.skipped:
                report.skipped += 1
            else:
                report.processed += 1
                report.analysed += 1
                if outcome.needs_review:
                    report.pending_review += 1
                if outcome.llm_used:
                    report.llm_used += 1

            emit(
                progress,
                "analyse",
                index,
                len(file_ids),
                f"Analysed {index} of {len(file_ids)}",
                outcome.category_path,
            )

        with ThreadPoolExecutor(max_workers=EXTRACTION_WORKERS) as executor:
            for index, file_id in enumerate(file_ids, start=1):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                emit(
                    progress,
                    "analyse",
                    index - 1,
                    len(file_ids),
                    f"Analysing {index} of {len(file_ids)}",
                )
                record = records.get(file_id)
                future: Future[PreparedExtraction] | None = None
                if record is not None:
                    recorded_hash = str(record.get("hash") or "")
                    seen_duplicate = bool(recorded_hash) and recorded_hash in seen_hashes
                    if recorded_hash:
                        seen_hashes.add(recorded_hash)
                    if reuse_duplicates and not force and seen_duplicate:
                        duplicate_candidates.add(file_id)
                    if not (reuse_duplicates and not force and seen_duplicate):
                        job = self._preparation_job(record, cache_keys, cache_signature)
                        if job is not None:
                            future = executor.submit(self._prepare_extraction, *job)
                queue.append((file_id, future, index))
                if len(queue) > EXTRACTION_PREFETCH:
                    process(queue.popleft())
            while queue:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                process(queue.popleft())

        self._embeddings.prune_cache()
        report.duration_seconds = round(time.perf_counter() - started, 3)
        emit(
            progress,
            "analyse",
            len(file_ids),
            len(file_ids),
            report.summary(),
        )
        return report

    def analyse_file(
        self,
        file_id: int,
        *,
        use_llm: bool = True,
        folder_cache: dict[Path, set[Path]] | None = None,
        reuse_duplicates: bool = True,
        force: bool = False,
        prepared: PreparedExtraction | None = None,
        cache_signature: tuple[str, bool] | None = None,
        category_map: dict[int, str] | None = None,
        category_paths: list[str] | None = None,
        reserved_names: set[str] | None = None,
        settings: AnalysisSettings | None = None,
        name_cache: dict[Path, set[str]] | None = None,
        manual_names: Mapping[int, str] | None = None,
        record: dict[str, object] | None = None,
        cache_keys: set[str] | None = None,
        duplicate_sources: Mapping[int, int] | None = None,
        duplicate_candidates: set[int] | None = None,
    ) -> AnalysisOutcome:
        snapshot = settings if settings is not None else self._batch_settings()
        manual_name = (
            manual_names.get(file_id)
            if manual_names is not None
            else self._analyses.accepted_filenames([file_id]).get(file_id)
        )
        return self._analyse_file(
            file_id,
            use_llm=use_llm,
            folder_cache=folder_cache,
            reuse_duplicates=reuse_duplicates,
            prepared=prepared,
            cache_signature=cache_signature
            or snapshot.cache_signature(use_llm, self._analysis_cache is not None),
            category_map=category_map,
            category_paths=category_paths,
            reserved_names=reserved_names,
            settings=snapshot,
            name_cache=name_cache,
            force=force,
            manual_name=manual_name,
            record=record if record is not None else self._files.get_record(file_id),
            cache_keys=cache_keys,
            duplicate_sources=duplicate_sources,
            duplicate_candidates=duplicate_candidates,
        )

    def _analyse_file(
        self,
        file_id: int,
        *,
        use_llm: bool = True,
        folder_cache: dict[Path, set[Path]] | None = None,
        reuse_duplicates: bool = True,
        force: bool = False,
        prepared: PreparedExtraction | None = None,
        cache_signature: tuple[str, bool] | None = None,
        category_map: dict[int, str] | None = None,
        category_paths: list[str] | None = None,
        reserved_names: set[str] | None = None,
        settings: AnalysisSettings | None = None,
        name_cache: dict[Path, set[str]] | None = None,
        manual_name: str | None = None,
        record: dict[str, object] | None = None,
        cache_keys: set[str] | None = None,
        duplicate_sources: Mapping[int, int] | None = None,
        duplicate_candidates: set[int] | None = None,
    ) -> AnalysisOutcome:
        snapshot = settings if settings is not None else self._batch_settings()
        record = record if record is not None else self._files.get_record(file_id)
        if record is None:
            return AnalysisOutcome(file_id, STATUS_FAILED, skipped=True, error="File record not found.")

        path = Path(record["path"])
        filename = str(record["name"])
        extension = str(record["extension"] or path.suffix)
        detected = prepared[0] if prepared is not None else inspect_format(path, extension)

        if not path.exists():
            self._files.mark_missing(file_id)
            return AnalysisOutcome(
                file_id, STATUS_UNAVAILABLE, skipped=True, error=f"File no longer exists: {path}"
            )
        stat_result = path.stat()
        if stat_result.st_size > self._config.max_file_size_bytes:
            self._files.update_status(file_id, STATUS_FAILED)
            return AnalysisOutcome(
                file_id,
                STATUS_FAILED,
                error=(
                    f"File exceeds the {self._config.max_file_size_mb} MB analysis limit "
                    "(configurable in Settings)."
                ),
            )
        if self._extractors.extractor_for(detected) is None:
            self._files.update_status(file_id, STATUS_UNSUPPORTED)
            return AnalysisOutcome(
                file_id,
                STATUS_UNSUPPORTED,
                skipped=True,
                error=f"No extractor for format '{detected}'.",
            )

        try:
            content_hash = sha256_file(path)
        except FileAccessError as exc:
            logger.warning("Could not refresh the hash for %s: %s", filename, exc)
            content_hash = None

        cache_prefix, cache_enabled = cache_signature or snapshot.cache_signature(
            use_llm, self._analysis_cache is not None
        )
        cache_key: str | None = None
        cached = None
        if cache_enabled and content_hash:
            extractor = self._extractors.extractor_for(detected)
            cache_key = self._cache_key(content_hash, extractor.version if extractor else "", cache_prefix)
            if cache_keys is None or cache_key in cache_keys:
                cached = self._analysis_cache.get(cache_key)

        source_id: int | None = None
        if reuse_duplicates and content_hash:
            if duplicate_sources is not None and str(record.get("hash") or "") == content_hash:
                source_id = duplicate_sources.get(file_id)
                if source_id is None and file_id in (duplicate_candidates or ()):
                    source_id = self._files.find_analysed_duplicate(file_id, content_hash)
            else:
                source_id = self._files.find_analysed_duplicate(file_id, content_hash)
            if source_id is not None:
                with self._db.batch():
                    if content_hash:
                        self._files.set_hash(file_id, content_hash)
                    reused = self._reuse_duplicate_analysis(
                        file_id,
                        source_id,
                        record,
                        filename,
                        extension,
                        folder_cache,
                        category_map,
                        reserved_names,
                        snapshot,
                        name_cache,
                        manual_name,
                    )
                if reused is not None:
                    return reused

        if cached is not None:
            payload, chunk_vectors = cached
            extraction = ExtractionResult(**payload["extraction"])
            chunks = [DocumentChunk(**item) for item in payload["chunks"]]
            with self._db.batch():
                if content_hash:
                    self._files.set_hash(file_id, content_hash)
                self._files.update_status(file_id, STATUS_EXTRACTING)
                self._analyses.save_extraction(file_id, extraction, chunks)
            classification = ClassificationResult(**payload["classification"])
            keywords = extract_keywords(extraction.text, limit=8)
            profile = self._build_profile(file_id, record, extraction, classification, keywords)
            llm_used = False
        else:
            if prepared is not None:
                _, extraction, chunks = prepared
            else:
                extraction = self._extract(path, detected, filename)
                chunks = self._chunks_for(extraction, filename, path, record)

            with self._db.batch():
                if content_hash:
                    self._files.set_hash(file_id, content_hash)
                self._files.update_status(file_id, STATUS_EXTRACTING)
                self._analyses.save_extraction(file_id, extraction, chunks)

            chunk_vectors = self._embed(file_id, chunks)
            document_vector = mean_vector(chunk_vectors) if chunk_vectors else None
            keywords = extract_keywords(extraction.text, limit=8)
            classification = self._classify(
                extraction.text, record, document_vector=document_vector, keywords=keywords
            )
            profile = self._build_profile(file_id, record, extraction, classification, keywords)
            llm_used = (
                self._apply_llm(
                    profile,
                    classification,
                    extraction.text,
                    content_title_present=profile.title_supported,
                    categories=category_paths,
                    settings=snapshot,
                )
                if use_llm
                else False
            )

        final_classification = classification
        profile.inferred_evidence.append(
            f"Assigned to {final_classification.category_path} by {final_classification.method} "
            f"with {final_classification.confidence:.0%} confidence."
        )

        root, configured = self._root_for(path, snapshot)
        existing_folders = self._folder_set(root, folder_cache) if configured else set()
        folder = self._folders.recommend(
            root=root,
            classification=final_classification,
            existing_folders=existing_folders,
        )
        destination_names = self._existing_names(folder.absolute_destination, name_cache)
        naming = self._naming.suggest(
            profile=profile,
            classification=final_classification,
            original_name=filename,
            extension=extension,
            template=snapshot.naming_template,
            existing_names=destination_names,
        )
        naming = self._apply_naming_conventions(
            naming, destination_names, reserved_names, settings=snapshot
        )
        rule_decision: str | None = None
        if manual_name is not None:
            naming.suggested_name = manual_name
            naming.changed = manual_name.lower() != filename.lower()
        else:
            decision = resolve_suggestion(
                original_name=filename,
                text=extraction.text,
                profile=asdict(profile),
                keywords=keywords,
                existing_names=destination_names,
                reserved_names=reserved_names or set(),
                relative_parent=self._relative_parent(path, root, configured),
                existing_folders=[item.as_posix() for item in existing_folders],
                detected_extension=str(record.get("detected_format") or ""),
            )
            if decision.applied:
                rule_decision = "content-naming"
                naming.suggested_name = decision.filename
                naming.changed = decision.filename.lower() != filename.lower()
                naming.explanation = f"{naming.explanation} Rule decision: content-naming."
                if decision.relative_folder and configured:
                    folder.relative_destination = Path(decision.relative_folder)
                    folder.absolute_destination = root / folder.relative_destination
                    folder.explanation = f"{folder.explanation} Rule decision: content-naming."

        needs_review = final_classification.needs_review or not extraction.success
        status = STATUS_PENDING_REVIEW if needs_review else STATUS_ANALYSED
        try:
            with self._db.batch():
                if cache_key is not None:
                    self._analysis_cache.set(
                        cache_key,
                        {
                            "extraction": asdict(extraction),
                            "chunks": [asdict(chunk) for chunk in chunks],
                            "classification": asdict(classification),
                        },
                        chunk_vectors,
                    )
                if chunk_vectors:
                    self._analyses.save_embeddings(
                        file_id, self._embeddings.model_name, chunk_vectors
                    )
                self._files.update_status(file_id, STATUS_ANALYSING)
                self._analyses.save_analysis(
                    file_id,
                    profile,
                    final_classification,
                    rule_decision=rule_decision,
                    accepted_name=manual_name,
                )
                self._analyses.save_suggestions(
                    file_id,
                    naming,
                    folder,
                    category_path=final_classification.category_path,
                    original_directory=path.parent,
                )
                self._analyses.set_tags(file_id, _merge_tags(profile, final_classification))
                self._files.update_status(file_id, status, analysed=True)
                try:
                    self._indexer.index_file(file_id, text=extraction.text)
                except Exception:  # pragma: no cover - index maintenance is best effort
                    logger.exception("Could not update the search index for %s", filename)
        except Exception as exc:
            logger.exception("Could not persist analysis for %s", filename)
            self._files.update_status(file_id, STATUS_FAILED)
            return AnalysisOutcome(file_id, STATUS_FAILED, error=f"Database write failed: {exc}")

        return AnalysisOutcome(
            file_id=file_id,
            status=status,
            category_path=final_classification.category_path,
            confidence=final_classification.confidence,
            needs_review=needs_review,
            llm_used=llm_used,
        )

    def _reuse_duplicate_analysis(
        self,
        file_id: int,
        source_id: int,
        record: dict[str, object],
        filename: str,
        extension: str,
        folder_cache: dict[Path, set[Path]] | None,
        category_map: dict[int, str] | None,
        reserved_names: set[str] | None = None,
        settings: AnalysisSettings | None = None,
        name_cache: dict[Path, set[str]] | None = None,
        manual_name: str | None = None,
    ) -> AnalysisOutcome | None:
        """Reuse a byte-identical document's analysis, regenerating path-specific advice."""

        try:
            if not self._analyses.clone_analysis(source_id, file_id):
                return None
            classification = self._analyses.latest_analysis(file_id, paths=category_map)
            if classification is None:
                return None
            refreshed = self._files.get_record(file_id)
            title = refreshed.get("title") if refreshed is not None else record.get("title")
            extraction = ExtractionResult(
                text=self._analyses.content_for(file_id),
                method="duplicate-reuse",
                success=True,
                title=str(title) if title else None,
            )
            keywords = extract_keywords(extraction.text, limit=8)
            profile = self._build_profile(file_id, record, extraction, classification, keywords)
            profile.inferred_evidence.append(
                f"Analysis reused from an identical file ({classification.method})."
            )
            snapshot = settings if settings is not None else self._batch_settings()
            path = Path(record["path"])
            root, configured = self._root_for(path, snapshot)
            existing_folders = self._folder_set(root, folder_cache) if configured else set()
            folder = self._folders.recommend(
                root=root,
                classification=classification,
                existing_folders=existing_folders,
            )
            destination_names = self._existing_names(folder.absolute_destination, name_cache)
            naming = self._naming.suggest(
                profile=profile,
                classification=classification,
                original_name=filename,
                extension=extension,
                template=snapshot.naming_template,
                existing_names=destination_names,
            )
            naming = self._apply_naming_conventions(
                naming, destination_names, reserved_names, settings=snapshot
            )
            if manual_name is not None:
                naming.suggested_name = manual_name
                naming.changed = manual_name.lower() != filename.lower()
            else:
                decision = resolve_suggestion(
                    original_name=filename,
                    text=extraction.text,
                    profile=asdict(profile),
                    keywords=keywords,
                    existing_names=destination_names,
                    reserved_names=reserved_names or set(),
                    relative_parent=self._relative_parent(path, root, configured),
                    existing_folders=[item.as_posix() for item in existing_folders],
                    detected_extension=str(record.get("detected_format") or ""),
                )
                if decision.applied:
                    naming.suggested_name = decision.filename
                    naming.changed = decision.filename.lower() != filename.lower()
                    naming.explanation = f"{naming.explanation} Rule decision: content-naming."
                    if decision.relative_folder and configured:
                        folder.relative_destination = Path(decision.relative_folder)
                        folder.absolute_destination = root / folder.relative_destination
                        folder.explanation = f"{folder.explanation} Rule decision: content-naming."
            self._analyses.save_suggestions(
                file_id,
                naming,
                folder,
                category_path=classification.category_path,
                original_directory=path.parent,
            )
            needs_review = classification.needs_review
            status = STATUS_PENDING_REVIEW if needs_review else STATUS_ANALYSED
            self._files.update_status(file_id, status, analysed=True)
            try:
                self._indexer.index_file(file_id, text=extraction.text)
            except Exception:  # pragma: no cover - best effort
                logger.exception("Could not index reused analysis for %s", filename)
            return AnalysisOutcome(
                file_id=file_id,
                status=status,
                category_path=classification.category_path,
                confidence=classification.confidence,
                needs_review=needs_review,
                llm_used=False,
            )
        except Exception as exc:
            logger.warning("Could not reuse duplicate analysis for %s: %s", filename, exc)
            return None

    def _preparation_job(
        self,
        record: dict[str, object],
        cache_keys: set[str],
        cache_signature: tuple[str, bool],
    ) -> PreparationJob | None:
        path = Path(str(record["path"]))
        if not path.exists() or path.stat().st_size > self._config.max_file_size_bytes:
            return None
        extension = str(record["extension"] or path.suffix)
        detected = str(record.get("detected_format") or "") or inspect_format(path, extension)
        extractor = self._extractors.extractor_for(detected)
        if extractor is None:
            return None
        content_hash = str(record["hash"] or "") or None
        cache_prefix, cache_enabled = cache_signature
        if cache_enabled and content_hash:
            key = self._cache_key(content_hash, extractor.version, cache_prefix)
            if key in cache_keys:
                return None
        return path, detected, str(record["name"]), record

    def _prepare_extraction(
        self, path: Path, detected: str, filename: str, record: dict[str, object]
    ) -> PreparedExtraction:
        extraction = self._extract(path, detected, filename)
        return detected, extraction, self._chunks_for(extraction, filename, path, record)

    @staticmethod
    def _chunks_for(
        extraction: ExtractionResult,
        filename: str,
        path: Path,
        record: dict[str, object],
    ) -> list[DocumentChunk]:
        chunks = chunk_text(extraction.text)
        if chunks:
            return chunks
        basis = " ".join(
            part
            for part in (
                extraction.title or "",
                filename.replace("_", " ").replace("-", " "),
                str(record.get("category") or ""),
            )
            if part
        ).strip()
        return [DocumentChunk(index=0, text=basis or path.stem)]

    def _batch_settings(self) -> AnalysisSettings:
        root = self._root_provider()
        resolved: Path | None = None
        if root:
            try:
                resolved = Path(root).expanduser().resolve()
            except OSError:
                resolved = Path(root).expanduser()
        return AnalysisSettings(
            naming_template=self._settings.naming_template,
            use_conventions=self._settings.use_conventions,
            low_confidence=self._settings.low_confidence,
            high_confidence=self._settings.high_confidence,
            embedding_model=self._settings.embedding_model,
            prefer_transformer=self._settings.prefer_transformer,
            organisation_root=resolved,
            feedback_present=bool(self._feedback_provider and self._feedback_provider()),
        )

    def _cache_signature(self, use_llm: bool) -> tuple[str, bool]:
        return self._batch_settings().cache_signature(use_llm, self._analysis_cache is not None)

    def _cache_key(self, content_hash: str, extractor_version: str, prefix: str) -> str:
        return sha256_text(f"{content_hash}|{extractor_version}|{prefix}")

    def _extract(self, path: Path, detected: str, filename: str) -> ExtractionResult:
        try:
            return self._extractors.extract(path, detected)
        except UnsupportedFormatError as exc:
            return ExtractionResult(text="", method="none", success=False, error=str(exc))
        except ExtractionError as exc:
            logger.warning("Extraction failed for %s: %s", filename, exc)
            return ExtractionResult(text="", method="none", success=False, error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected extraction failure for %s", filename)
            return ExtractionResult(text="", method="none", success=False, error=str(exc))

    def _embed(self, file_id: int, chunks: list[DocumentChunk]) -> list[np.ndarray]:
        try:
            matrix = self._embeddings.encode([chunk.text for chunk in chunks])
            return [matrix[index] for index in range(matrix.shape[0])]
        except Exception as exc:
            logger.warning("Embedding failed for file %s: %s", file_id, exc)
            return []

    def _classify(
        self,
        text: str,
        record: dict[str, object],
        *,
        document_vector: np.ndarray | None = None,
        keywords: list[str] | None = None,
    ) -> ClassificationResult:
        try:
            classifier = self._classifier_provider()
            return classifier.classify(
                text,
                filename=str(record["name"]),
                extension=str(record["extension"] or ""),
                title=str(record["title"]) if record["title"] else None,
                document_vector=document_vector,
                keywords=keywords,
            )
        except Exception as exc:
            logger.exception("Classifier unavailable")
            return ClassificationResult(
                primary_category=UNCLASSIFIED,
                secondary_category=None,
                category_path=UNCLASSIFIED,
                confidence=0.1,
                method="fallback(classifier_unavailable)",
                evidence=[f"The classifier could not run: {exc}"],
                needs_review=True,
            )

    def _build_profile(
        self,
        file_id: int,
        record: dict[str, object],
        extraction: ExtractionResult,
        classification: ClassificationResult,
        keywords: list[str] | None = None,
    ) -> DocumentProfile:
        text = extraction.text
        title, supported = extract_title(text, str(record["name"]), extraction.title)
        if keywords is None:
            keywords = extract_keywords(text, limit=8)
        if not keywords:
            keywords = [part for part in str(record["name"]).replace("_", " ").split() if len(part) > 3][:5]

        profile = DocumentProfile(
            file_id=file_id,
            title=title,
            document_type=extract_document_type(text, classification.category_path),
            organisation=extract_organisation(text[:6000]),
            document_date=extract_date(text[:8000]),
            language=_guess_language(text),
            keywords=keywords,
            summary=extractive_summary(text),
            title_supported=supported,
            extracted_evidence=[],
            inferred_evidence=[
                f"Category: {classification.category_path} ({classification.confidence:.0%})",
            ],
            uncertainties=list(extraction.warnings),
        )

        if extraction.success:
            profile.extracted_evidence.append(
                f"Extracted {extraction.char_count:,} characters using the "
                f"{extraction.method} extractor."
            )
        else:
            profile.uncertainties.append(
                f"Content could not be extracted ({extraction.error or 'unknown reason'}); "
                "recommendations rely on the filename and metadata only."
            )
        if extraction.page_count:
            profile.extracted_evidence.append(f"Document has {extraction.page_count} pages.")
        if profile.document_date:
            profile.extracted_evidence.append(f"Date found in the text: {profile.document_date}")
        if profile.organisation:
            profile.extracted_evidence.append(
                f"Organisation name found in the text: {profile.organisation}"
            )
        if supported:
            profile.extracted_evidence.append("The title was taken from the document content.")
        else:
            profile.uncertainties.append(
                "No reliable title was found in the content; the filename was used as a fallback."
            )
        if classification.needs_review:
            profile.uncertainties.append(
                "Classification confidence is below the review threshold; human review is required."
            )
        return profile

    def _apply_llm(
        self,
        profile: DocumentProfile,
        classification: ClassificationResult,
        text: str,
        *,
        content_title_present: bool,
        categories: list[str] | None = None,
        settings: AnalysisSettings | None = None,
    ) -> bool:
        if not should_use_llm(
            classification=classification,
            title_supported=content_title_present,
            text_length=len(text.strip()),
            available=self._llm_available_with_backoff,
        ):
            return False
        categories = categories if categories is not None else self._analyses.category_paths()
        result = self._llm.analyze_document(text, categories)
        if result is None:
            self._llm_failed_at = time.monotonic()
            return False
        if not any(
            (
                result.title,
                result.document_type,
                result.primary_category,
                result.secondary_category,
                result.organisation,
                result.document_date,
                result.confidence,
                result.tags,
                result.evidence,
            )
        ):
            profile.uncertainties.extend(result.uncertainties)
            return False

        if result.title:
            profile.title = result.title
            profile.title_supported = True
            profile.inferred_evidence.append("Title supplied by the local language model.")
        if result.organisation:
            profile.organisation = result.organisation
        if result.document_date:
            parsed_date = extract_date(result.document_date)
            if parsed_date:
                profile.document_date = parsed_date

        allowed = set(categories)
        proposed = result.primary_category
        if proposed and proposed not in allowed:
            proposed = next((path for path in allowed if path.startswith(f"{proposed}/")), None)

        if proposed:
            agrees = (
                proposed == classification.category_path
                or classification.category_path.startswith(f"{proposed}/")
                or proposed.startswith(f"{classification.primary_category}/")
            )
            if agrees:
                classification.evidence.append(
                    "The local language model independently agreed with this category."
                )
                classification.confidence = min(
                    0.98, round(classification.confidence + 0.02, 3)
                )
                threshold = (
                    settings.low_confidence if settings is not None else self._settings.low_confidence
                )
                classification.needs_review = classification.confidence < threshold
            elif classification.needs_review and (result.confidence or 0.0) >= 0.60:
                primary, _, secondary = proposed.partition("/")
                classification.category_path = proposed
                classification.primary_category = primary
                classification.secondary_category = secondary or None
                classification.confidence = min(
                    0.55, round(0.55 * float(result.confidence or 0.6), 3)
                )
                classification.method = f"{classification.method}+llm-tiebreak"
                classification.needs_review = True
                classification.evidence = [
                    *classification.evidence,
                    f"The local language model proposed {proposed}; it was used only as a "
                    "weak tie-breaker because the hybrid evidence was inconclusive.",
                ]
                profile.uncertainties.append(
                    "The category is a weak tie-break from a local language model and must be "
                    "confirmed by a person."
                )
            else:
                profile.uncertainties.append(
                    f"The local language model proposed {proposed}, but the hybrid evidence "
                    f"selected {classification.category_path}; the hybrid result was retained."
                )

        return True

    def _llm_available(self) -> bool:
        self._sync_llm_runtime()
        if not self._llm.enabled:
            return False
        if self._llm_state is not True:
            available, detail = self._llm.health()
            self._llm_state = True if available else None
            self._llm_failed_at = None if available else time.monotonic()
            logger.info("Local language model: %s", detail)
        return self._llm_state is True

    def _llm_available_with_backoff(self) -> bool:
        if (
            self._llm_failed_at is not None
            and time.monotonic() - self._llm_failed_at < _LLM_FAILURE_COOLDOWN_SECONDS
        ):
            return False
        return self._llm_available()

    def _sync_llm_runtime(self) -> None:
        signature = (
            self._settings.llm_model,
            self._settings.llm_base_url.rstrip("/"),
            self._settings.enable_llm,
        )
        if signature == self._llm_runtime:
            return
        self._llm.model, self._llm.base_url, self._llm.enabled = signature
        self._llm_runtime = signature
        self.reset_llm_probe()

    def reset_llm_probe(self) -> None:
        self._llm_state = None
        self._llm_failed_at = None

    def _apply_naming_conventions(
        self,
        suggestion: NamingSuggestion,
        existing_names: Sequence[str],
        reserved_names: set[str] | None = None,
        settings: AnalysisSettings | None = None,
    ) -> NamingSuggestion:
        use_conventions = (
            settings.use_conventions if settings is not None else self._settings.use_conventions
        )
        if not use_conventions:
            return suggestion
        convention = detect_convention(list(existing_names))
        if convention is None:
            return suggestion
        if reserved_names:
            prefix = convention.prefix.rstrip(convention.separator).lower()
            prefix = prefix.replace(convention.separator, "")
            numbers: list[int] = []
            for reserved in reserved_names:
                stem = Path(reserved).stem.lower()
                for separator in ("-", "_", " "):
                    stem = stem.replace(separator, "")
                if not stem.startswith(prefix):
                    continue
                tail = stem[len(prefix) :]
                width = convention.numeric_suffix
                if len(tail) >= width and tail[-width:].isdigit():
                    numbers.append(int(tail[-width:]))
            if numbers:
                convention = replace(
                    convention,
                    next_sequence=max(convention.next_sequence, max(numbers) + 1),
                )

        rewritten = apply_convention(suggestion.suggested_name, convention)
        suffix = Path(suggestion.suggested_name).suffix or Path(suggestion.original_name).suffix
        validation = self._naming.validator.validate(rewritten, extension=suffix)
        if not validation.valid or not validation.filename:
            return suggestion

        occupied = {
            name for name in existing_names if name.lower() != suggestion.original_name.lower()
        }
        if reserved_names is not None:
            occupied.update(reserved_names)
        final_name, warning = self._naming.validator.deduplicate(validation.filename, occupied)
        if reserved_names is not None:
            reserved_names.add(final_name)
        evidence = [
            *suggestion.evidence,
            f"naming convention: {convention.prefix}#{convention.numeric_suffix}",
        ]
        warnings = [*suggestion.warnings, *([warning] if warning else [])]
        return replace(
            suggestion,
            suggested_name=final_name,
            evidence=evidence,
            warnings=warnings,
            changed=final_name.lower() != suggestion.original_name.lower(),
        )

    def _root_for(self, path: Path, settings: AnalysisSettings | None = None) -> tuple[Path, bool]:
        root = settings.organisation_root if settings is not None else None
        if root is None:
            configured = self._root_provider()
            if configured:
                try:
                    root = Path(configured).expanduser().resolve()
                except OSError:
                    root = None
        if root is not None:
            try:
                if path.resolve().is_relative_to(root):
                    return root, True
            except OSError:
                pass
        return path.parent, False

    @staticmethod
    def _relative_parent(path: Path, root: Path, configured: bool) -> str | None:
        if not configured:
            return None
        try:
            relative = path.resolve().parent.relative_to(root)
        except (OSError, ValueError):
            return None
        value = relative.as_posix()
        return None if value in (".", "") else value

    @staticmethod
    def _folder_set(
        root: Path, cache: dict[Path, set[Path]] | None
    ) -> set[Path]:
        if cache is None:
            return existing_relative_folders(root)
        if root in cache:
            cache[root] = cache.pop(root)
            return cache[root]
        if len(cache) >= FOLDER_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        cache[root] = existing_relative_folders(root)
        return cache[root]

    @staticmethod
    def _existing_names(folder: Path, cache: dict[Path, set[str]] | None = None) -> set[str]:
        if cache is not None and folder in cache:
            return set(cache[folder])
        names: set[str] = set()
        try:
            if folder.is_dir():
                names = {child.name for child in folder.iterdir()}
        except OSError:
            pass
        if cache is not None:
            cache[folder] = names
        return set(names)


def _merge_tags(profile: DocumentProfile, classification: ClassificationResult) -> list[str]:
    tags = [*classification.tags, *profile.keywords]
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(tag.strip()[:60])
        if len(result) >= 12:
            break
    return result


def _guess_language(text: str) -> str:
    """Very small heuristic; ``und`` means undetermined rather than guessing."""

    if not text.strip():
        return "und"
    sample = text[:4000].lower()
    english_markers = (" the ", " and ", " of ", " to ", " is ", " for ")
    hits = sum(1 for marker in english_markers if marker in f" {sample} ")
    return "en" if hits >= 2 else "und"
