"""Optional local language-model integration.

OpenCoeus uses a local, instruction-following model for tasks where ordinary
language helps: extracting a document title, summarising context and proposing a
readable name. It is *never* allowed to touch the filesystem, and its output is
treated as a suggestion that must pass the same validation as any other.

The client speaks the Ollama HTTP API (``/api/tags`` and ``/api/generate``),
which is the most common way to run quantised local models. Any runtime that
implements the same endpoints can be substituted.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.config import validate_loopback_url
from app.core.exceptions import ConfigurationError
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_PROMPT_DIR = Path(__file__).parent / "prompts"
_INJECTION_PATTERN = re.compile(
    r"(?:\b(?:ignore|disregard|forget)\b[\s*_`~-]*"
    r"(?:(?:all|any|the|your|these|those)\b[\s*_`~-]*)*"
    r"(?:previous|prior|above|earlier|preceding)\b[\s*_`~-]*(?:instructions|directives)\b)"
    r"|\b(?:please|kindly)\b[^.\n]{0,80}\b"
    r"(?:include|return|respond|output|answer|write|say|mention|mark|label|classify|choose|select|set|treat|use)\b"
    r"|\b(?:for your response|in your response|your task is|you must|you should|when summarizing|when classifying)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=16)
def _read_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


@dataclass(slots=True)
class LocalLLMResult:
    """Validated structured output from a local language model."""

    title: str | None = None
    document_type: str | None = None
    primary_category: str | None = None
    secondary_category: str | None = None
    organisation: str | None = None
    document_date: str | None = None
    confidence: float | None = None
    tags: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    raw: dict[str, object] = field(default_factory=dict)


class LocalLLMClient:
    """Small JSON-only client for a local Ollama-compatible runtime.

    Args:
        base_url: Runtime base URL (default ``http://127.0.0.1:11434``).
        model: Model identifier available in the runtime.
        timeout: Request timeout in seconds.
        enabled: When False every call returns ``None`` without network access.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b-instruct",
        *,
        timeout: float = 60.0,
        enabled: bool = True,
    ) -> None:
        problem = validate_loopback_url(base_url)
        if problem:
            raise ConfigurationError(problem)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.enabled = enabled

    def _request(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data else "GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - loopback URL validated in __init__
            body = response.read().decode("utf-8")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("Unexpected response shape")
        return parsed

    def health(self) -> tuple[bool, str]:
        """Return ``(available, detail)`` without raising."""

        if not self.enabled:
            return False, "Local language model disabled in settings."
        try:
            payload = self._request("/api/tags")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return False, f"Runtime not reachable at {self.base_url} ({exc})."
        models = payload.get("models")
        if not isinstance(models, list):
            return True, "Runtime reachable; installed models could not be listed."
        names = {str(item.get("name", "")) for item in models if isinstance(item, dict)}
        if self.model in names or any(name.startswith(f"{self.model}:") for name in names):
            return True, f"Model '{self.model}' is installed."
        return False, f"Runtime reachable, but model '{self.model}' is not installed."

    def analyze_document(self, text: str, categories: list[str]) -> LocalLLMResult | None:
        """Ask the model for a structured document description.

        Returns ``None`` when the runtime is unavailable or the response cannot
        be validated. Malformed output is never partially trusted.
        """

        if not self.enabled:
            return None
        if _INJECTION_PATTERN.search(text):
            logger.warning("Document contains instruction-like text; refusing LLM analysis.")
            return LocalLLMResult(
                uncertainties=[
                    "Document contained instruction-like text; it was not sent to the language model."
                ]
            )

        prompt = self._render_prompt(
            "document_analysis.txt",
            {
                "categories": "\n".join(f"- {category}" for category in categories),
                "document_text": f"<document_data>\n{text[:6000]}\n</document_data>",
            },
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 600},
        }
        try:
            response = self._request("/api/generate", payload)
            raw_text = response.get("response")
            if not isinstance(raw_text, str):
                return None
            data = self._parse_json(raw_text)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            logger.warning("Local LLM analysis failed: %s", exc)
            return None

        allowed = set(categories)
        category = self._string(data.get("primary_category"))
        if category not in allowed:
            category = None
        confidence = data.get("confidence")
        try:
            confidence_value = max(0.0, min(1.0, float(confidence))) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None

        result = LocalLLMResult(
            title=self._string(data.get("title")),
            document_type=self._string(data.get("document_type")),
            primary_category=category,
            secondary_category=self._string(data.get("secondary_category")),
            organisation=self._string(data.get("organisation")),
            document_date=self._string(data.get("document_date")),
            confidence=confidence_value,
            tags=self._string_list(data.get("tags")),
            evidence=self._string_list(data.get("evidence")),
            uncertainties=self._string_list(data.get("uncertainties")),
            raw=data,
        )
        return result

    @staticmethod
    def _render_prompt(name: str, values: dict[str, object]) -> str:
        template = _read_prompt(name)
        for key, value in values.items():
            template = template.replace("{" + key + "}", str(value))
        return template

    @staticmethod
    def _parse_json(text: str) -> dict[str, object]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("Model did not return a JSON object")
        return data

    @staticmethod
    def _string(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:200]
        return None

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:200] for item in value if str(item).strip()][:12]
