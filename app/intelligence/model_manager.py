"""Capability discovery for local AI and supporting tools."""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from app.intelligence.embeddings import EmbeddingEngine
from app.intelligence.llm import LocalLLMClient


@dataclass(slots=True)
class CapabilityStatus:
    """Human-readable status of one optional capability."""

    key: str
    label: str
    available: bool
    detail: str
    required: bool = False


class ModelManager:
    """Reports which local capabilities are usable on this machine.

    The application must remain functional when optional models are absent, so
    every capability has a defined fallback (see ``fallbacks``).
    """

    def __init__(
        self,
        embeddings: EmbeddingEngine,
        llm: LocalLLMClient,
        *,
        prefer_transformer: bool = True,
    ) -> None:
        self.embeddings = embeddings
        self.llm = llm
        self.prefer_transformer = prefer_transformer

    def statuses(self, *, probe: bool = True) -> list[CapabilityStatus]:
        """Return capability statuses.

        Args:
            probe: When False, skip operations that may load a model or make a
                network request (useful for a fast UI refresh).
        """

        statuses: list[CapabilityStatus] = []
        if probe:
            embedding_available = True
            try:
                backend = self.embeddings.backend
                detail = (
                    f"{backend.name} ({'semantic' if backend.is_semantic else 'deterministic fallback'})"
                )
            except Exception as exc:
                embedding_available = False
                detail = f"Embedding backend failed to load: {exc}"
        else:
            embedding_available = True
            detail = self.embeddings.requested_model

        statuses.append(
            CapabilityStatus(
                "embeddings",
                "Embedding model",
                embedding_available,
                detail,
                required=True,
            )
        )

        if probe:
            llm_available, llm_detail = self.llm.health()
        else:
            llm_available, llm_detail = self.llm.enabled, "Not probed"
        statuses.append(
            CapabilityStatus(
                "llm",
                "Local language model",
                llm_available,
                llm_detail + " Filename generation falls back to deterministic templates.",
            )
        )

        tesseract = shutil.which("tesseract")
        ocr_package = False
        try:
            import pytesseract  # type: ignore[import-not-found]  # noqa: F401

            ocr_package = True
        except ImportError:
            ocr_package = False
        statuses.append(
            CapabilityStatus(
                "ocr",
                "OCR engine",
                bool(tesseract and ocr_package),
                "Tesseract is installed." if tesseract and ocr_package else "Not configured; scanned images are indexed by metadata only.",
            )
        )
        return statuses

    @property
    def fallbacks(self) -> dict[str, str]:
        return {
            "embeddings": "Hashed n-gram vectors keep semantic search operational without a transformer.",
            "llm": "Deterministic naming templates and keyword classification.",
            "ocr": "Images are classified from filename, EXIF metadata and any embedded description.",
        }
