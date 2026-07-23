from __future__ import annotations

import re
from pathlib import Path


def is_protected(file_path: Path, protected_patterns: list[str]) -> bool:
    # CHECKS EVERY FOLDER NAME IN A PATH AGAINST THE CONFIGURED SAFETY RULES.
    return any(
        re.search(pattern, path_part, re.IGNORECASE)
        for path_part in file_path.parts
        for pattern in protected_patterns
    )
