"""Image metadata extraction with optional local OCR.

OCR is deliberately optional: it requires the Tesseract binary and adds
significant processing time. When it is unavailable the image is still indexed
by filename and EXIF description so that it can be organized, but the
extraction result reports low content quality.
"""

from __future__ import annotations

from pathlib import Path

from PIL import ExifTags, Image

from app.core.exceptions import ExtractionError
from app.domain.models import ExtractionResult
from app.processing.extractors.base import BaseExtractor
from app.processing.file_signature import inspect_format

_EXIF_NAMES = {value: key for key, value in ExifTags.TAGS.items()}


class ImageExtractor(BaseExtractor):
    name = "image"
    version = "1.2"
    formats = ("image", "vector-image")

    def __init__(self, *, enable_ocr: bool = False) -> None:
        self.enable_ocr = enable_ocr

    def extract(self, path: Path) -> ExtractionResult:
        if inspect_format(path) == "vector-image":
            return ExtractionResult(
                text="",
                method="vector-metadata",
                success=True,
                page_count=1,
                title=None,
                warnings=[
                    "Vector image: only file metadata is indexed; drawing content is not extracted."
                ],
                meta={"format": path.suffix[1:].upper() or "EPS", "vector": True},
            )

        warnings: list[str] = []
        try:
            with Image.open(path) as image:
                meta: dict[str, object] = {
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                    "format": image.format,
                }
                description = None
                exif = None
                try:
                    exif = image.getexif()
                except Exception as exc:
                    warnings.append(f"Image metadata is incomplete: {exc}")
                if exif:
                    for tag_id, value in exif.items():
                        tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                        if tag_name in {"ImageDescription", "XPTitle", "XPComment"}:
                            description = str(value) if value else None
                        if tag_name in {"Model", "Make", "DateTime"}:
                            meta[tag_name] = str(value)
        except Exception as exc:
            raise ExtractionError(f"Cannot open image {path.name}: {exc}") from exc

        text = description or ""
        method = "image-metadata"
        if self.enable_ocr:
            try:
                import pytesseract  # type: ignore[import-not-found]

                text = pytesseract.image_to_string(str(path)).strip()
                method = "ocr"
                if not text:
                    warnings.append("OCR returned no readable text.")
            except Exception as exc:
                warnings.append(f"OCR is unavailable: {exc}")

        return ExtractionResult(
            text=self._truncate(text, warnings),
            method=method,
            success=True,
            page_count=1,
            title=None,
            warnings=warnings,
            meta=meta,
        )
