"""Repositories: the only layer that reads or writes SQLAlchemy entities."""

from app.infrastructure.repositories.analysis import AnalysisRepository
from app.infrastructure.repositories.embedding_cache import EmbeddingCacheRepository
from app.infrastructure.repositories.feedback import FeedbackRepository
from app.infrastructure.repositories.files import FileRepository
from app.infrastructure.repositories.operations import OperationRepository
from app.infrastructure.repositories.settings import (
    RuleRepository,
    ScanSessionRepository,
    SettingsRepository,
)

__all__ = [
    "AnalysisRepository",
    "EmbeddingCacheRepository",
    "FeedbackRepository",
    "FileRepository",
    "OperationRepository",
    "RuleRepository",
    "ScanSessionRepository",
    "SettingsRepository",
]
