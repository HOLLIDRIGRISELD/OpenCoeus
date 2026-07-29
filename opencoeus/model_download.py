from __future__ import annotations

import logging
import os
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

logger = logging.getLogger(__name__)

MODELS_DIR = Path.home() / ".opencode" / "models"
BIN_DIR = Path.home() / ".opencode" / "bin"

PHI3_GGUF_URL = (
    "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/"
    "Phi-3-mini-4k-instruct-q4.gguf"
)
PHI3_GGUF_FILENAME = "Phi-3-mini-4k-instruct-q4.gguf"
PHI3_GGUF_SIZE = 2_509_000_000  # ~2.5 GB

Qwen25_GGUF_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
)
Qwen25_GGUF_FILENAME = "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
Qwen25_GGUF_SIZE = 987_000_000  # ~1 GB

LLAMA_CLI_VERSION = "b3560"
LLAMA_CLI_URL = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/b{LLAMA_CLI_VERSION}/"
    f"llama-b{LLAMA_CLI_VERSION}-bin-win-msvc-x64.zip"
)
LLAMA_CLI_FILENAME = "llama-cli.exe"

BACKEND_CANDIDATES: dict[str, str] = {
    "phi3": PHI3_GGUF_FILENAME,
    "qwen2.5": Qwen25_GGUF_FILENAME,
}

MODEL_URLS: dict[str, str] = {
    PHI3_GGUF_FILENAME: PHI3_GGUF_URL,
    Qwen25_GGUF_FILENAME: Qwen25_GGUF_URL,
}


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _download_file(url: str, dest: Path, desc: str = "") -> None:
    _ensure_dir(dest.parent)
    logger.info("Downloading %s from %s", desc or dest.name, url)
    try:
        import requests
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total and downloaded % (1024 * 1024 * 10) < 65536:
                        pct = downloaded / total * 100
                        logger.info("  %s: %.1f MB / %.1f MB (%.0f%%)", desc or dest.name,
                                     downloaded / 1e6, total / 1e6, pct)
    except ImportError:
        _download_file_urllib(url, dest, desc)


def _download_file_urllib(url: str, dest: Path, desc: str = "") -> None:
    _ensure_dir(dest.parent)
    tmp = dest.with_suffix(".part")
    try:
        resp = urlopen(url, timeout=30)
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total and downloaded % (1024 * 1024 * 10) < 65536:
                    pct = downloaded / total * 100
                    logger.info("  %s: %.1f MB / %.1f MB (%.0f%%)", desc or dest.name,
                                 downloaded / 1e6, total / 1e6, pct)
        shutil.move(str(tmp), str(dest))
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def download_model(model_filename: str) -> Path:
    _ensure_dir(MODELS_DIR)
    dest = MODELS_DIR / model_filename
    if dest.exists():
        logger.info("Model %s already exists at %s", model_filename, dest)
        return dest
    url = MODEL_URLS.get(model_filename)
    if not url:
        raise ValueError(f"Unknown model: {model_filename}")
    _download_file(url, dest, desc=model_filename)
    return dest


def download_llama_cli() -> Path:
    _ensure_dir(BIN_DIR)
    exe_path = BIN_DIR / LLAMA_CLI_FILENAME
    if exe_path.exists():
        logger.info("llama-cli already exists at %s", exe_path)
        return exe_path
    zip_name = f"llama-b{LLAMA_CLI_VERSION}-bin-win-msvc-x64.zip"
    zip_path = BIN_DIR / zip_name
    _download_file(LLAMA_CLI_URL, zip_path, desc=zip_name)
    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            for member in zf.namelist():
                if member.endswith("/llama-cli.exe") or member.endswith("\\llama-cli.exe"):
                    with zf.open(member) as src, open(exe_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break
            else:
                for member in zf.namelist():
                    name = os.path.basename(member)
                    if name == "llama-cli.exe":
                        with zf.open(member) as src, open(exe_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        break
                else:
                    raise FileNotFoundError("llama-cli.exe not found in zip archive")
        exe_path.chmod(exe_path.stat().st_mode | 0o111)
    finally:
        if zip_path.exists():
            zip_path.unlink()
    return exe_path


def model_path(model_filename: str) -> Path:
    return MODELS_DIR / model_filename


def llama_cli_path() -> Path | None:
    exe = BIN_DIR / LLAMA_CLI_FILENAME
    return exe if exe.exists() else None


def is_model_downloaded(model_filename: str) -> bool:
    return (MODELS_DIR / model_filename).exists()


def is_llama_cli_downloaded() -> bool:
    return (BIN_DIR / LLAMA_CLI_FILENAME).exists()
