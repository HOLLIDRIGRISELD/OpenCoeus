from __future__ import annotations

import re
import threading
from pathlib import Path

# CACHE COMPILED PATTERNS TO AVOID RECOMPILING ON EVERY CALL
MAX_CACHE_SIZE = 64
_compiled_cache: dict[tuple[str, ...], list[re.Pattern]] = {}
_CACHE_LOCK = threading.Lock()


def is_protected(file_path: Path, protected_patterns: list[str]) -> bool:
    # CHECKS EVERY FOLDER NAME IN A PATH AGAINST THE CONFIGURED SAFETY RULES
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
