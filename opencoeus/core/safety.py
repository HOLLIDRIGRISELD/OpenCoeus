from __future__ import annotations

import re
import threading
from pathlib import Path

# CACHE COMPILED PATTERNS TO AVOID RECOMPILING ON EVERY CALL
MAX_CACHE_SIZE = 64
_compiled_cache: dict[tuple[str, ...], list[re.Pattern]] = {}
_CACHE_LOCK = threading.Lock()


def is_protected(file_path: Path, protected_patterns: list[str]) -> bool:
    """Check every folder name in a path against the configured safety rules."""
    cache_key = tuple(protected_patterns)
    with _CACHE_LOCK:
        compiled = _compiled_cache.get(cache_key)
    if compiled is None:
        compiled = [re.compile(p, re.IGNORECASE) for p in protected_patterns]
        with _CACHE_LOCK:
            if len(_compiled_cache) >= MAX_CACHE_SIZE:
                oldest_key = next(iter(_compiled_cache))
                del _compiled_cache[oldest_key]
            _compiled_cache[cache_key] = compiled
    return any(
        pattern.search(path_part)
        for path_part in file_path.parts
        for pattern in compiled
    )


RESERVED_WINDOWS_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})


def is_valid_filename(name: str) -> tuple[bool, str]:
    """Validate a filename for OS-level constraints; returns (valid, reason)."""
    if not name:
        return (False, "Filename is empty")
    if len(name) > 255:
        return (False, f"Filename exceeds 255 characters ({len(name)})")
    stem = Path(name).stem.upper()
    if stem in RESERVED_WINDOWS_NAMES:
        return (False, f"Filename uses reserved name: {stem}")
    if name.rstrip().endswith(".") or name.rstrip().endswith(" "):
        return (False, "Filename ends with trailing dot or space")
    invalid = set('<>:"/\\|?*')
    if any(c in name for c in invalid):
        return (False, f"Filename contains invalid characters")
    return (True, "")
