from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(file_path: Path, read_chunk_size: int = 1024 * 1024) -> str:
    # CREATES A SHA-256 HASH THAT IDENTIFIES THE FILE'S EXACT CONTENT.
    file_hasher = hashlib.sha256()
    with file_path.open("rb") as input_file:
        for file_chunk in iter(lambda: input_file.read(read_chunk_size), b""):
            file_hasher.update(file_chunk)
    return file_hasher.hexdigest()
