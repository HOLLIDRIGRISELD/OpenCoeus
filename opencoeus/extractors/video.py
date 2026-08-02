from __future__ import annotations

import logging
from pathlib import Path

from .signals import FileSignals

logger = logging.getLogger(__name__)


def _extract_video(file_path: Path, result: FileSignals) -> None:
    try:
        from pymediainfo import MediaInfo
        media = MediaInfo.parse(file_path)
        for track in media.tracks:
            if track.track_type == "General":
                if track.duration:
                    result.metadata["duration_ms"] = track.duration
                if track.file_size:
                    result.metadata["file_size_bytes"] = str(track.file_size)
            elif track.track_type == "Video":
                if track.format:
                    result.metadata["video_format"] = track.format
                if track.width and track.height:
                    result.metadata["resolution"] = f"{track.width}x{track.height}"
                if track.frame_rate:
                    result.metadata["frame_rate"] = track.frame_rate
            elif track.track_type == "Audio":
                if track.format:
                    result.metadata["audio_format"] = track.format
                if track.channel_s:
                    result.metadata["audio_channels"] = str(track.channel_s)
        if result.metadata:
            result.signals_present.append("metadata")
            result.confidence_hint = max(result.confidence_hint, 0.4)
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Video extraction failed for %s: %s", file_path, exc)
