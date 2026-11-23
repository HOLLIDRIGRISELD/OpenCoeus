"""Central exception hierarchy.

Every expected failure mode has a dedicated exception so that the UI can show a
useful message and the pipeline can decide whether to retry, skip or abort.
"""

from __future__ import annotations


class OpenCoeusError(Exception):
    """Base class for all application-specific errors.

    Attributes:
        user_message: A short, non-technical explanation suitable for the UI.
    """

    default_user_message = "An unexpected problem occurred."

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        super().__init__(message or self.default_user_message)
        self.user_message = user_message or self.default_user_message


class FileAccessError(OpenCoeusError):
    """A file or directory could not be read or written."""

    default_user_message = "OpenCoeus cannot access this file. Check your folder permissions."


class UnsupportedFormatError(OpenCoeusError):
    """No extractor is registered for the detected document format."""

    default_user_message = "This file format is not supported."


class ExtractionError(OpenCoeusError):
    """A supported document could not be read or decoded."""

    default_user_message = "OpenCoeus could not extract readable content from this document."


class ModelUnavailableError(OpenCoeusError):
    """A local AI model or runtime is not available."""

    default_user_message = "The selected local AI model could not be loaded."


class InvalidRecommendationError(OpenCoeusError):
    """A recommendation failed validation."""

    default_user_message = "The proposed change is not valid and was not applied."


class OperationConflictError(OpenCoeusError):
    """A filesystem operation would overwrite or conflict with existing data."""

    default_user_message = "A file with the proposed name already exists."


class RecoveryError(OpenCoeusError):
    """An operation could not be reversed safely."""

    default_user_message = "The original location is occupied. The file has not been restored."


class DatabaseError(OpenCoeusError):
    """A database operation failed."""

    default_user_message = "OpenCoeus could not read or update its local database."


class ConfigurationError(OpenCoeusError):
    """Invalid or missing configuration."""

    default_user_message = "The application configuration is invalid."
