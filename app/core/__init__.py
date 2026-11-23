"""Core utilities shared by every layer."""

from app.core.config import AppConfig, default_data_dir
from app.core.exceptions import (
    DatabaseError,
    ExtractionError,
    FileAccessError,
    InvalidRecommendationError,
    ModelUnavailableError,
    OpenCoeusError,
    OperationConflictError,
    RecoveryError,
    UnsupportedFormatError,
)
from app.core.logging_config import configure_logging, get_logger

__all__ = [
    "AppConfig",
    "default_data_dir",
    "DatabaseError",
    "ExtractionError",
    "FileAccessError",
    "InvalidRecommendationError",
    "ModelUnavailableError",
    "OpenCoeusError",
    "OperationConflictError",
    "RecoveryError",
    "UnsupportedFormatError",
    "configure_logging",
    "get_logger",
]
