from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MODELS_DIR = Path.home() / ".opencode" / "models"
BIN_DIR = Path.home() / ".opencode" / "bin"

PHI3_GGUF_FILENAME = "Phi-3-mini-4k-instruct-q4.gguf"
Qwen25_GGUF_FILENAME = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
LLAMA_CLI_FILENAME = "llama-cli.exe"


def model_path(model_filename: str) -> Path:
    return MODELS_DIR / model_filename


def llama_cli_path() -> Path | None:
    exe = BIN_DIR / LLAMA_CLI_FILENAME
    return exe if exe.exists() else None


def is_model_downloaded(model_filename: str) -> bool:
    return (MODELS_DIR / model_filename).exists()


def is_llama_cli_downloaded() -> bool:
    return (BIN_DIR / LLAMA_CLI_FILENAME).exists()
