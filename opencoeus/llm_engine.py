from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .content_extractor import FileSignals
from .model_download import (
    llama_cli_path,
    model_path,
    is_model_downloaded,
    is_llama_cli_downloaded,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a file naming assistant. Given file information, suggest a concise "
    "descriptive filename and a destination folder path. "
    "Use underscores in filenames, not spaces. "
    "Destinations use forward slashes."
)

USER_TEMPLATE = """FILE TYPE: {file_type}
EXTENSION: {ext}
DOC TYPE: {doc_type}
TOPIC: {topic}
AUTHOR: {author}
ORGANIZATION: {org}
DATE: {date}
KEYWORDS: {keywords}
SUMMARY: {summary}
PROJECT: {project}
LOCATION: {location}
CAMERA: {camera}
ARTIST: {artist}
ALBUM: {album}

CONTENT:
{text}
"""


@dataclass
class LLMConfig:
    enabled: bool = False
    model: str = "phi3"
    temperature: float = 0.3
    max_tokens: int = 128
    context_length: int = 2048
    n_threads: int = 4


@dataclass
class LLMGenerationResult:
    filename: str = ""
    destination: str = ""
    success: bool = False
    duration_ms: int = 0
    error: str = ""


class LLMEngine:

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        self._backend: _Backend | None = None
        self._model_filename: str = ""

    def _resolve_model_filename(self) -> str:
        if self.config.model == "phi3":
            return "Phi-3-mini-4k-instruct-q4.gguf"
        elif self.config.model == "qwen2.5":
            return "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
        return self.config.model

    def _ensure_backend(self) -> _Backend | None:
        if self._backend is not None:
            return self._backend

        self._model_filename = self._resolve_model_filename()
        model_file = model_path(self._model_filename)

        if not model_file.exists():
            logger.warning("Model %s not downloaded; LLM disabled", self._model_filename)
            return None

        backend = _try_llama_cpp_python(model_file, self.config)
        if backend is not None:
            logger.info("Using llama-cpp-python backend")
            self._backend = backend
            return backend

        backend = _try_llama_cli(model_file, self.config)
        if backend is not None:
            logger.info("Using llama-cli subprocess backend")
            self._backend = backend
            return backend

        logger.warning("No LLM backend available; falling back to heuristic generation")
        return None

    def generate(self, nlp_result, signals: FileSignals) -> LLMGenerationResult:
        if not self.config.enabled:
            return LLMGenerationResult(success=False, error="LLM disabled")

        backend = self._ensure_backend()
        if backend is None:
            return LLMGenerationResult(success=False, error="No LLM backend available")

        prompt = self._build_prompt(nlp_result, signals)
        start = time.monotonic()
        try:
            raw = backend.generate(prompt, max_tokens=self.config.max_tokens)
            elapsed = int((time.monotonic() - start) * 1000)
            result = self._parse_output(raw)
            result.duration_ms = elapsed
            result.success = bool(result.filename)
            return result
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.debug("LLM generation failed: %s", exc)
            return LLMGenerationResult(success=False, duration_ms=elapsed, error=str(exc))

    def _build_prompt(self, nlp_result, signals: FileSignals) -> str:
        text_snippet = signals.text[:1500] if signals.text else ""
        keywords = ", ".join(nlp_result.keywords[:8]) if nlp_result.keywords else ""

        user = USER_TEMPLATE.format(
            file_type=signals.file_type or "unknown",
            ext=signals.extension or "",
            doc_type=nlp_result.document_type or "",
            topic=nlp_result.topic or "",
            author=nlp_result.author.replace("_", " ") if nlp_result.author else "",
            org=nlp_result.organization.replace("_", " ") if nlp_result.organization else "",
            date=nlp_result.date or "",
            keywords=keywords,
            summary=nlp_result.summary or "",
            project=nlp_result.project.replace("_", " ") if nlp_result.project else "",
            location=nlp_result.location.replace("_", " ") if nlp_result.location else "",
            camera=nlp_result.camera_model or "",
            artist=nlp_result.artist or "",
            album=nlp_result.album or "",
            text=text_snippet,
        )
        if self.config.model in ("phi3",):
            return f"<|system|>\n{SYSTEM_PROMPT}\n<|end|>\n<|user|>\n{user}\n<|end|>\n<|assistant|>\n"
        return f"<|system|>\n{SYSTEM_PROMPT}\n<|end|>\n<|user|>\n{user}\n<|end|>\n<|assistant|>\n"

    def _parse_output(self, raw: str) -> LLMGenerationResult:
        result = LLMGenerationResult()
        filename = ""
        destination = ""
        for line in raw.strip().splitlines():
            line = line.strip()
            if line.upper().startswith("FILENAME:") or line.upper().startswith("FILENAME:"):
                filename = line.split(":", 1)[1].strip()
            elif line.upper().startswith("DESTINATION:") or line.upper().startswith("DESTINATION:"):
                destination = line.split(":", 1)[1].strip()
        result.filename = filename
        result.destination = destination
        return result


class _Backend:

    def generate(self, prompt: str, max_tokens: int = 128) -> str:
        raise NotImplementedError


def _try_llama_cpp_python(model_file: Path, config: LLMConfig) -> _Backend | None:
    try:
        from llama_cpp import Llama
        llm = Llama(
            model_path=str(model_file),
            n_ctx=config.context_length,
            n_threads=config.n_threads or None,
            verbose=False,
        )
        return _LlamaCppPythonBackend(llm)
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("llama-cpp-python init failed: %s", exc)
        return None


def _try_llama_cli(model_file: Path, config: LLMConfig) -> _Backend | None:
    cli_path = llama_cli_path()
    if not cli_path:
        return None
    if not cli_path.exists():
        logger.debug("llama-cli not found at %s", cli_path)
        return None
    return _LlamaCliBackend(cli_path, model_file, config)


class _LlamaCppPythonBackend(_Backend):

    def __init__(self, llm) -> None:
        self._llm = llm

    def generate(self, prompt: str, max_tokens: int = 128) -> str:
        output = self._llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.3,
            stop=["<|end|>", "<|user|>"],
            echo=False,
        )
        choices = output.get("choices", [])
        if choices:
            return choices[0].get("text", "")
        return ""


class _LlamaCliBackend(_Backend):

    def __init__(self, cli_path: Path, model_file: Path, config: LLMConfig) -> None:
        self._cli_path = cli_path
        self._model_file = model_file
        self._config = config

    def generate(self, prompt: str, max_tokens: int = 128) -> str:
        cmd = [
            str(self._cli_path),
            "-m", str(self._model_file),
            "-p", prompt,
            "-n", str(max_tokens),
            "-t", str(self._config.n_threads),
            "-c", str(self._config.context_length),
            "--temp", str(self._config.temperature),
            "-e",
            "--no-display-prompt",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return proc.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.warning("llama-cli timed out after 120s")
            return ""
        except FileNotFoundError:
            logger.warning("llama-cli executable not found at %s", self._cli_path)
            return ""
