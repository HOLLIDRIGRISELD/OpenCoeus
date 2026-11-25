"""Composition root for the application.

``AppContext`` owns the database, repositories and services. Constructing it has
one side effect: it creates the SQLite schema if needed. Everything else is lazy,
so starting the GUI or CLI is fast even on a machine without optional AI models.

The UI and CLI depend on this context rather than instantiating repositories
themselves. Rebuilding the services after a settings change ensures that a new
embedding model or local-LLM endpoint is used immediately.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.core.config import AppConfig
from app.core.constants import STATUS_ANALYSING, STATUS_PENDING_ANALYSIS, UNCLASSIFIED
from app.core.exceptions import OperationConflictError
from app.core.logging_config import configure_logging, get_logger
from app.core.process_lock import DATA_LOCK_NAME, ProcessLock
from app.domain.enums import PlanStatus
from app.infrastructure.database import Database
from app.infrastructure.repositories.analysis import AnalysisRepository
from app.infrastructure.repositories.batches import BatchRepository, cleanup_stale_batches
from app.infrastructure.repositories.caches import (
    AnalysisCacheRepository,
    FileFingerprintRepository,
)
from app.infrastructure.repositories.embedding_cache import EmbeddingCacheRepository
from app.infrastructure.repositories.feedback import FeedbackRepository
from app.infrastructure.repositories.files import FileRepository
from app.infrastructure.repositories.operations import OperationRepository
from app.infrastructure.repositories.settings import (
    ScanSessionRepository,
    SettingsRepository,
)
from app.intelligence.classifier import HybridClassifier
from app.intelligence.embeddings import EmbeddingEngine
from app.intelligence.folder_recommender import FolderRecommender
from app.intelligence.llm import LocalLLMClient
from app.intelligence.model_manager import CapabilityStatus, ModelManager
from app.intelligence.naming_engine import FilenameValidator, NamingEngine
from app.organisation.executor import FileOperationExecutor
from app.organisation.recovery import RecoveryManager
from app.processing.extractors import ExtractorRegistry
from app.search.hybrid import HybridSearch
from app.search.indexer import SearchIndexer
from app.search.keyword import KeywordSearch
from app.search.semantic import SemanticSearch
from app.services.analysis_service import AnalysisService
from app.services.organisation_service import OrganisationService
from app.services.profile_service import ProfileService
from app.services.recommendation_service import RecommendationService
from app.services.recovery_service import RecoveryService
from app.services.scanning_service import ScanningService
from app.services.search_service import SearchService
from app.services.settings_service import SettingsService

logger = get_logger(__name__)


class AppContext:
    """Wires the whole application together.

    Args:
        config: Process configuration. Defaults are loaded from disk by
            :meth:`create`.
        db: Optional database override (used by tests).
    """

    def __init__(
        self, config: AppConfig, db: Database | None = None, *, purge: bool = True
    ) -> None:
        config.ensure_directories()
        configure_logging(config.log_dir, config.log_level)
        self.config = config
        self.db = db or Database(config.db_url or f"sqlite:///{config.data_dir / 'opencoeus.db'}")
        self.db.create_schema()
        self.files = FileRepository(self.db)
        self.analyses = AnalysisRepository(self.db)
        self.operations = OperationRepository(self.db)
        self.batches = BatchRepository(self.db)
        # A staged batch is live state even before cleanup resolves its items.
        try:
            with ProcessLock(config.data_dir / DATA_LOCK_NAME).locked():
                staged = bool(self.batches.unfinished())
                cleanup_stale_batches(self.db)
                self.operations.reset_status(
                    PlanStatus.EXECUTING, PlanStatus.REVALIDATION_REQUIRED
                )
                self.files.reset_status(STATUS_ANALYSING, STATUS_PENDING_ANALYSIS)
        except OperationConflictError:
            logger.warning("Skipped batch cleanup; another process holds the data lock")
            staged = True

        self.settings_repository = SettingsRepository(self.db)
        self.embedding_cache = EmbeddingCacheRepository(self.db)
        self.analysis_cache = AnalysisCacheRepository(self.db)
        self.file_fingerprints = FileFingerprintRepository(self.db)
        self.feedback = FeedbackRepository(self.db)
        self.sessions = ScanSessionRepository(self.db)
        self.profiles = ProfileService(self.db)

        if purge and not staged and not self.batches.held_items():
            self.db.purge_session_data()

        self.settings = SettingsService(self.settings_repository, self.config)
        self.indexer = SearchIndexer(self.db)
        self.extractors = ExtractorRegistry()
        self.filename_validator = FilenameValidator()
        self.naming = NamingEngine(self.filename_validator)
        self.folders = FolderRecommender(max_depth=self.config.max_folder_depth)

        self.embeddings = EmbeddingEngine(
            self.settings.embedding_model,
            prefer_transformer=self.settings.prefer_transformer,
            cache=self.embedding_cache,
            corpus_provider=self.embedding_corpus,
        )
        self.llm = LocalLLMClient(
            self.settings.llm_base_url,
            self.settings.llm_model,
            enabled=self.settings.enable_llm,
        )
        self.models = ModelManager(
            self.embeddings,
            self.llm,
            prefer_transformer=self.settings.prefer_transformer,
        )

        self._classifier: HybridClassifier | None = None
        self._classifier_lock = threading.Lock()
        self._wire_services()

    @classmethod
    def create(
        cls,
        config: AppConfig | None = None,
        *,
        data_dir: Path | None = None,
        purge: bool = True,
    ) -> AppContext:
        """Load configuration (unless provided) and open the database."""

        resolved = config or AppConfig.load(data_dir)
        return cls(resolved, purge=purge)

    def _wire_services(self) -> None:
        keyword = KeywordSearch(self.db)
        semantic = SemanticSearch(self.analyses, self.embeddings)
        hybrid = HybridSearch(
            keyword,
            semantic,
            alpha=self.settings.search_alpha,
            beta=self.settings.search_beta,
        )

        self.scanning = ScanningService(
            self.config,
            self.files,
            self.sessions,
            self.settings,
            self.file_fingerprints,
            self.db,
            profiles=self.profiles,
        )
        self.analysis = AnalysisService(
            config=self.config,
            db=self.db,
            files=self.files,
            analyses=self.analyses,
            indexer=self.indexer,
            extractors=self.extractors,
            embeddings=self.embeddings,
            llm=self.llm,
            naming=self.naming,
            folders=self.folders,
            settings=self.settings,
            classifier_provider=self.classifier,
            root_provider=lambda: self.settings.organisation_root,
            analysis_cache=self.analysis_cache,
            feedback_provider=self.feedback.has_any,
        )
        self.recommendations = RecommendationService(
            self.files,
            self.analyses,
            self.settings,
            self.filename_validator,
            feedback=self.feedback,
            model_name_provider=lambda: self.embeddings.model_name,
            on_feedback=self.invalidate_classifier,
        )
        self.executor = FileOperationExecutor(self.files, self.operations, self.indexer)
        self.recovery_manager = RecoveryManager(
            self.files, self.analyses, self.operations, self.indexer
        )
        self.organisation = OrganisationService(
            self.files,
            self.analyses,
            self.operations,
            self.recommendations,
            self.executor,
            self.settings,
            self.indexer,
            self.batches,
            self.config.data_dir / "holding",
        )
        self.search = SearchService(
            keyword, semantic, hybrid, self.analyses, self.embeddings, self.settings
        )
        self.recovery = RecoveryService(
            self.config, self.db, self.operations, self.recovery_manager, self.indexer
        )

    def embedding_corpus(self) -> list[str]:
        """Text used to fit the deterministic fallback's IDF weights."""

        return self.analyses.embedding_corpus()

    def classifier(self) -> HybridClassifier:
        """Build the classifier lazily from the category descriptions.

        The category table is the single source of truth: adding a category in
        the database changes the classifier on the next analysis run.
        """

        with self._classifier_lock:
            if self._classifier is None:
                descriptions = self.analyses.category_descriptions()
                if not descriptions:
                    descriptions = {
                        UNCLASSIFIED: "Documents that do not match a known category"
                    }
                self._classifier = HybridClassifier(
                    descriptions,
                    self.embeddings,
                    review_threshold=self.settings.low_confidence,
                    feedback=self.feedback.for_model(self.embeddings.model_name),
                )
            return self._classifier

    def invalidate_classifier(self) -> None:
        with self._classifier_lock:
            self._classifier = None

    def capabilities(self, *, probe: bool = False) -> list[CapabilityStatus]:
        return self.models.statuses(probe=probe)

    def apply_settings(self, values: dict[str, object]) -> list[str]:
        """Validate and apply settings, rebuilding model-dependent services.

        Returns:
            Validation problems. When non-empty, nothing changed.
        """

        problems = self.settings.update(values)
        if problems:
            return problems

        self.embeddings = EmbeddingEngine(
            self.settings.embedding_model,
            prefer_transformer=self.settings.prefer_transformer,
            cache=self.embedding_cache,
            corpus_provider=self.embedding_corpus,
        )
        self.llm = LocalLLMClient(
            self.settings.llm_base_url,
            self.settings.llm_model,
            enabled=self.settings.enable_llm,
        )
        self.models = ModelManager(
            self.embeddings,
            self.llm,
            prefer_transformer=self.settings.prefer_transformer,
        )
        self._wire_services()
        self.invalidate_classifier()
        logger.info("Settings applied; services rebuilt")
        return []

    def set_organisation_root(self, root: Path | None) -> list[str]:
        """Set the organisation root through validated settings."""

        return self.apply_settings({"organisation.root": root})

    def stats(self):
        return self.files.stats()

    def duplicates(self):
        return self.recommendations.duplicates()

    def close(self) -> None:
        """Dispose of the engine and release the database file."""

        try:
            self.db.dispose()
        except Exception:  # pragma: no cover - shutdown should not raise
            logger.exception("Error while closing the database")

    def __enter__(self) -> AppContext:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["AppContext"]
