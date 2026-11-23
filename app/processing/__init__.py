"""Processing layer: discovery and document content extraction."""

from app.processing.chunking import ChunkingConfig, chunk_text
from app.processing.extractors import ExtractorRegistry
from app.processing.hashing import sha256_file, sha256_text
from app.processing.scanner import FileScanner, ScanOptions, ScanProgress

__all__ = [
    "ChunkingConfig",
    "ExtractorRegistry",
    "FileScanner",
    "ScanOptions",
    "ScanProgress",
    "chunk_text",
    "sha256_file",
    "sha256_text",
]
