"""Folder destination recommendation.

The engine never invents an arbitrary deep hierarchy. It maps the classification
to a bounded path, reuses existing folders where the case or naming differs, and
reports whether the destination is new.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.models import ClassificationResult, FolderSuggestion


class FolderRecommender:
    """Recommends a destination relative to the organisation root.

    Args:
        max_depth: Maximum number of path components beneath the root.
    """

    def __init__(self, max_depth: int = 4) -> None:
        self.max_depth = max(1, max_depth)

    def recommend(
        self,
        *,
        root: Path,
        classification: ClassificationResult,
        existing_folders: set[Path] | None = None,
    ) -> FolderSuggestion:
        parts = [part for part in classification.category_path.split("/") if part]
        parts = parts[: self.max_depth]
        relative = Path(*parts) if parts else Path("Unclassified")

        existing = existing_folders or set()
        reuse = self._match_existing(relative, existing)
        if reuse is not None:
            relative = reuse
            reuse_note = "Reused an existing folder."
        else:
            reuse_note = "A new destination folder will be created if approved."

        destination = root / relative
        evidence = [
            f"Classification: {classification.category_path}",
            f"Classification confidence: {classification.confidence:.0%}",
            reuse_note,
        ]
        confidence = round(min(0.98, classification.confidence * 0.92), 3)
        explanation = (
            f"Grouped under '{relative.as_posix()}' because the document was classified as "
            f"{classification.category_path}. {reuse_note}"
        )
        return FolderSuggestion(
            relative_destination=relative,
            absolute_destination=destination,
            confidence=confidence,
            explanation=explanation,
            evidence=evidence,
            is_new=reuse is None and not destination.exists(),
        )

    @staticmethod
    def _match_existing(relative: Path, existing: set[Path]) -> Path | None:
        target = relative.as_posix().lower()
        for folder in existing:
            if folder.as_posix().lower() == target:
                return folder
        return None


def existing_relative_folders(root: Path, *, limit: int = 5000) -> set[Path]:
    """List directories beneath ``root`` as relative paths.

    Errors (for example a directory deleted mid-scan) are ignored; folder
    recommendation must not fail because one directory is unreadable.
    """

    folders: set[Path] = set()
    try:
        for count, path in enumerate(root.rglob("*")):
            if count >= limit:
                break
            try:
                if path.is_dir():
                    folders.add(path.relative_to(root))
            except OSError:
                continue
    except OSError:
        pass
    return folders
