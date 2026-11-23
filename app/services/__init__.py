"""Service layer: application workflows that coordinate repositories and AI."""

from app.services.analysis_service import AnalysisOutcome, AnalysisReport, AnalysisService
from app.services.common import (
    CancellationToken,
    OperationCancelled,
    ProgressCallback,
    ProgressEvent,
    ServiceReport,
    emit,
)
from app.services.context import AppContext
from app.services.organisation_service import OrganisationPreviews, OrganisationService
from app.services.recommendation_service import (
    DuplicateGroup,
    EditResult,
    RecommendationDetail,
    RecommendationService,
)
from app.services.recovery_service import BackupInfo, RecoveryService
from app.services.scanning_service import ScanningService, ScanReport
from app.services.search_service import SearchService
from app.services.settings_service import SettingsService

__all__ = [
    "AnalysisOutcome",
    "AnalysisReport",
    "AnalysisService",
    "AppContext",
    "BackupInfo",
    "CancellationToken",
    "DuplicateGroup",
    "EditResult",
    "OperationCancelled",
    "OrganisationPreviews",
    "OrganisationService",
    "ProgressCallback",
    "ProgressEvent",
    "RecommendationDetail",
    "RecommendationService",
    "RecoveryService",
    "ScanReport",
    "ScanningService",
    "SearchService",
    "ServiceReport",
    "SettingsService",
    "emit",
]
