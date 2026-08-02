from __future__ import annotations

import html
import json
import logging
import re

from ..extractors import FileSignals
from .backends import _try_llama_cpp_python, _try_llama_cli
from .config import LLMConfig
from .downloader import model_path
from .prompts import SYSTEM_PROMPT, USER_TEMPLATE
from .result import LLMGenerationResult

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_snippet(text: str, max_chars: int = 600) -> str:
    """Strip markup, collapse whitespace, and bound the text to a fixed length."""
    if not text:
        return ""
    cleaned = _HTML_TAG_RE.sub(" ", text)
    cleaned = html.unescape(cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip()


class LLMEngine:

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        self._backend = None
        self._model_filename = ""

    def _resolve_model_filename(self) -> str:
        if self.config.model == "phi3":
            return "Phi-3-mini-4k-instruct-q4.gguf"
        elif self.config.model == "qwen2.5":
            return "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
        return self.config.model

    def _ensure_backend(self):
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
        try:
            raw = backend.generate(prompt, max_tokens=self.config.max_tokens)
            result = self._parse_output(raw)
            result.raw_output = raw
            result.success = bool(result.filename)
            return result
        except Exception as exc:
            logger.debug("LLM generation failed: %s", exc)
            return LLMGenerationResult(success=False, error=str(exc))

    def complete(
        self,
        user_text: str,
        max_tokens: int | None = None,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> LLMGenerationResult:
        """Run a raw chat request and return the raw model output.

        The caller owns parsing; ``raw_output`` carries the model's text.
        """
        if not self.config.enabled:
            return LLMGenerationResult(success=False, error="LLM disabled")

        backend = self._ensure_backend()
        if backend is None:
            return LLMGenerationResult(success=False, error="No LLM backend available")

        prompt = self.build_chat_prompt(user_text, system_prompt=system_prompt)
        tokens = max_tokens or self.config.max_tokens
        try:
            raw = backend.generate(prompt, max_tokens=tokens)
            result = LLMGenerationResult(raw_output=raw)
            result.success = bool(raw and raw.strip())
            return result
        except Exception as exc:
            logger.debug("LLM generation failed: %s", exc)
            return LLMGenerationResult(success=False, error=str(exc))

    def build_chat_prompt(self, user_text: str, system_prompt: str = SYSTEM_PROMPT) -> str:
        return (
            f"<|system|>\n{system_prompt}\n<|end|>\n"
            f"<|user|>\n{user_text}\n<|end|>\n<|assistant|>\n"
        )

    def _build_prompt(self, nlp_result, signals: FileSignals, base_folder: str = "") -> str:
        text_snippet = clean_snippet(signals.text)
        keywords = ", ".join(nlp_result.keywords[:8]) if nlp_result.keywords else ""

        user = USER_TEMPLATE.format(
            base_folder=base_folder,
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
        return self.build_chat_prompt(user)

    def _parse_output(self, raw: str) -> LLMGenerationResult:
        result = LLMGenerationResult()
        filename = ""
        destination = ""
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict):
                    filename = str(data.get("filename", "") or "").strip()
                    subfolder = str(data.get("subfolder", "") or "").strip()
                    destination = subfolder or str(data.get("destination", "") or "").strip()
            except (json.JSONDecodeError, ValueError):
                filename = destination = ""
        if not filename and not destination:
            for line in raw.strip().splitlines():
                line = line.strip()
                upper = line.upper()
                if upper.startswith("FILENAME:"):
                    filename = line.split(":", 1)[1].strip()
                elif upper.startswith("DESTINATION:"):
                    destination = line.split(":", 1)[1].strip()
        result.filename = filename
        result.destination = destination
        return result
