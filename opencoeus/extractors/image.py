from __future__ import annotations

import logging
from pathlib import Path

from .signals import FileSignals

logger = logging.getLogger(__name__)


def _extract_image(file_path: Path, result: FileSignals) -> None:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(file_path)
        result.metadata["image_format"] = img.format or ""
        result.metadata["width"] = str(img.width)
        result.metadata["height"] = str(img.height)
        result.metadata["mode"] = img.mode
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        continue
                if tag_name in ("DateTimeOriginal", "DateTime", "CreateDate"):
                    result.metadata["date_taken"] = str(value)
                elif tag_name in ("Make",):
                    result.metadata["camera_make"] = str(value)
                elif tag_name in ("Model",):
                    result.metadata["camera_model"] = str(value)
                elif tag_name in ("GPSInfo",):
                    result.metadata["gps_present"] = "true"
                elif tag_name in ("Software",):
                    result.metadata["software"] = str(value)
                elif tag_name in ("Artist", "Copyright"):
                    result.metadata.setdefault(tag_name.lower(), str(value))
        img.close()
        if result.metadata:
            result.signals_present.append("metadata")
            if "date_taken" in result.metadata or "camera_model" in result.metadata:
                result.confidence_hint = max(result.confidence_hint, 0.5)
    except Exception as exc:
        logger.debug("Image extraction failed for %s: %s", file_path, exc)
