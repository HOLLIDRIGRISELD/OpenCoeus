from __future__ import annotations

import logging
import re
from pathlib import Path

from .signals import FileSignals

logger = logging.getLogger(__name__)


def _extract_code(file_path: Path, result: FileSignals) -> None:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    lines = content.splitlines()
    for line in lines[:200]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#!") or stripped.startswith("//!") or stripped.startswith("--!"):
            result.metadata.setdefault("shebang", stripped)
        if re.match(r"^(import |from |using |require|include|#include)", stripped):
            result.metadata.setdefault("imports", []).append(stripped)
    result.text = "\n".join(lines[:500])
    if result.text.strip():
        result.signals_present.append("text")
        result.confidence_hint = max(result.confidence_hint, 0.6)


def _extract_text(file_path: Path, result: FileSignals) -> None:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        result.text = f.read(100_000)
    if result.text.strip():
        result.signals_present.append("text")
        result.confidence_hint = max(result.confidence_hint, 0.9)


def _extract_text_fallback(file_path: Path, result: FileSignals) -> None:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            result.text = f.read(65536)
        if result.text.strip():
            result.signals_present.append("text")
            result.confidence_hint = max(result.confidence_hint, 0.4)
    except Exception:
        pass
