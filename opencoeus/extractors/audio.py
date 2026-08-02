from __future__ import annotations

import logging
from pathlib import Path

from .signals import FileSignals

logger = logging.getLogger(__name__)


def _extract_audio(file_path: Path, result: FileSignals) -> None:
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            return
        if audio.info:
            result.metadata["duration_seconds"] = str(round(audio.info.length, 1))
            if hasattr(audio.info, "bitrate"):
                result.metadata["bitrate"] = str(audio.info.bitrate)
            if hasattr(audio.info, "sample_rate"):
                result.metadata["sample_rate"] = str(audio.info.sample_rate)
        if audio.tags:
            for key in ("title", "artist", "album", "date", "genre", "tracknumber"):
                val = audio.tags.get(key)
                if val:
                    result.metadata[key] = val[0] if isinstance(val, list) else str(val)
        if result.metadata:
            result.signals_present.append("metadata")
            if "artist" in result.metadata or "title" in result.metadata:
                result.confidence_hint = max(result.confidence_hint, 0.6)
    except Exception as exc:
        logger.debug("Audio extraction failed for %s: %s", file_path, exc)
