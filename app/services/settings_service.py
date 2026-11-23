"""Typed application settings backed by the ``settings`` table."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import AppConfig, validate_loopback_url
from app.core.constants import MAX_FILENAME_LENGTH
from app.infrastructure.repositories.settings import SettingsRepository

_DEFAULTS: dict[str, Any] = {
    "app.theme": "dark",
    "app.naming_template": "{title}",
    "naming.use_conventions": False,
    "app.high_confidence": 0.85,
    "app.low_confidence": 0.60,
    "app.enable_llm": True,
    "app.prefer_transformer": True,
    "app.max_file_size_mb": 200,
    "app.scan_batch_size": 25,
    "search.alpha": 0.40,
    "search.beta": 0.60,
    "llm.model": "qwen2.5:3b-instruct",
    "llm.base_url": "http://127.0.0.1:11434",
    "embeddings.model": "sentence-transformers/all-MiniLM-L6-v2",
    "organisation.root": "",
}


class SettingsService:
    """Converts between the string key/value table and typed settings.

    All writes are validated before they are applied; an invalid update changes
    nothing and returns a list of human-readable problems.
    """

    def __init__(self, repository: SettingsRepository, config: AppConfig) -> None:
        self._repository = repository
        self._config = config

    @property
    def theme(self) -> str:
        return self._get("app.theme", str)

    @property
    def naming_template(self) -> str:
        return self._get("app.naming_template", str)

    @property
    def use_conventions(self) -> bool:
        return self._get("naming.use_conventions", bool)

    @property
    def high_confidence(self) -> float:
        return self._get("app.high_confidence", float)

    @property
    def low_confidence(self) -> float:
        return self._get("app.low_confidence", float)

    @property
    def enable_llm(self) -> bool:
        return self._get("app.enable_llm", bool)

    @property
    def prefer_transformer(self) -> bool:
        return self._get("app.prefer_transformer", bool)

    @property
    def max_file_size_mb(self) -> int:
        return self._get("app.max_file_size_mb", int)

    @property
    def scan_batch_size(self) -> int:
        return self._get("app.scan_batch_size", int)

    @property
    def search_alpha(self) -> float:
        return self._get("search.alpha", float)

    @property
    def search_beta(self) -> float:
        return self._get("search.beta", float)

    @property
    def llm_model(self) -> str:
        return self._get("llm.model", str)

    @property
    def llm_base_url(self) -> str:
        return self._get("llm.base_url", str)

    @property
    def embedding_model(self) -> str:
        return self._get("embeddings.model", str)

    @property
    def organisation_root(self) -> Path | None:
        raw = self._repository.get("organisation.root", "")
        if not raw or not raw.strip():
            return None
        return Path(raw).expanduser()

    def set_organisation_root(self, root: Path | None) -> None:
        self._repository.set(
            "organisation.root", str(Path(root).expanduser().resolve()) if root else ""
        )

    def snapshot(self) -> dict[str, Any]:
        values = dict(_DEFAULTS)
        values.update(
            {
                "app.theme": self.theme,
                "app.naming_template": self.naming_template,
                "naming.use_conventions": self.use_conventions,
                "app.high_confidence": self.high_confidence,
                "app.low_confidence": self.low_confidence,
                "app.enable_llm": self.enable_llm,
                "app.prefer_transformer": self.prefer_transformer,
                "app.max_file_size_mb": self.max_file_size_mb,
                "app.scan_batch_size": self.scan_batch_size,
                "search.alpha": self.search_alpha,
                "search.beta": self.search_beta,
                "llm.model": self.llm_model,
                "llm.base_url": self.llm_base_url,
                "embeddings.model": self.embedding_model,
                "organisation.root": str(self.organisation_root or ""),
            }
        )
        return values

    def update(self, values: Mapping[str, Any]) -> list[str]:
        """Validate and persist several settings atomically.

        Returns:
            A list of problems. When non-empty, nothing was written.
        """

        problems: list[str] = []
        parsed: dict[str, Any] = {}

        for key, raw in values.items():
            if key not in _DEFAULTS:
                problems.append(f"Unknown setting '{key}'.")
                continue
            try:
                if key == "organisation.root" and raw is None:
                    parsed[key] = ""
                else:
                    parsed[key] = self._coerce(key, raw)
            except (TypeError, ValueError) as exc:
                problems.append(f"{key}: {exc}")

        if "llm.base_url" in parsed:
            problem = validate_loopback_url(str(parsed["llm.base_url"]))
            if problem:
                problems.append(f"llm.base_url: {problem}")
        if "organisation.root" in parsed and str(parsed["organisation.root"]):
            root_text = str(parsed["organisation.root"])
            root = Path(root_text).expanduser()
            if (
                not root_text
                or not root.is_absolute()
                or ".." in root.parts
                or not root.resolve().is_dir()
            ):
                problems.append(
                    "organisation.root must be an existing absolute directory."
                )
            else:
                parsed["organisation.root"] = str(root.resolve())

        low = float(parsed.get("app.low_confidence", self.low_confidence))
        high = float(parsed.get("app.high_confidence", self.high_confidence))
        if not 0 < low < high < 1:
            problems.append("The review threshold must be lower than the high-confidence threshold.")
        for key in ("search.alpha", "search.beta"):
            if key in parsed and not 0 <= float(parsed[key]) <= 1:
                problems.append(f"{key} must be between 0 and 1.")
        if parsed.get("search.alpha", self.search_alpha) + parsed.get(
            "search.beta", self.search_beta
        ) <= 0:
            problems.append("At least one search weight must be greater than zero.")
        template = str(parsed.get("app.naming_template", self.naming_template))
        if "{title}" not in template and "{original}" not in template:
            problems.append("The naming template must contain {title} or {original}.")
        if len(template) > MAX_FILENAME_LENGTH:
            problems.append("The naming template is too long.")
        if "app.max_file_size_mb" in parsed and int(parsed["app.max_file_size_mb"]) < 1:
            problems.append("The maximum file size must be at least 1 MB.")
        if "app.scan_batch_size" in parsed and int(parsed["app.scan_batch_size"]) < 1:
            problems.append("The scan batch size must be at least 1.")

        if problems:
            return problems

        self._repository.set_many({key: self._serialise(value) for key, value in parsed.items()})
        self._apply_to_config(parsed)
        return []

    def _get(self, key: str, kind: type) -> Any:
        raw = self._repository.get(key)
        default = _DEFAULTS[key]
        if raw is None:
            return self._config_default(key, default)
        try:
            if kind is bool:
                return raw.strip().lower() in {"1", "true", "yes", "on"}
            if kind is int:
                return int(raw)
            if kind is float:
                return float(raw)
            return str(raw)
        except ValueError:
            return default

    def _config_default(self, key: str, default: Any) -> Any:
        mapping = {
            "app.naming_template": self._config.naming_template,
            "app.high_confidence": self._config.high_confidence,
            "app.low_confidence": self._config.low_confidence,
            "app.enable_llm": self._config.enable_llm,
            "app.prefer_transformer": self._config.prefer_transformer,
            "app.max_file_size_mb": self._config.max_file_size_mb,
            "app.scan_batch_size": self._config.scan_batch_size,
            "llm.model": self._config.llm_model,
            "llm.base_url": self._config.llm_base_url,
            "embeddings.model": self._config.embedding_model,
        }
        return mapping.get(key, default)

    @staticmethod
    def _coerce(key: str, raw: Any) -> Any:
        default = _DEFAULTS[key]
        if isinstance(default, bool):
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            raise ValueError("expected a yes/no value")
        if isinstance(default, int) and not isinstance(default, bool):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        return str(raw).strip()

    @staticmethod
    def _serialise(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value)

    def _apply_to_config(self, values: Mapping[str, Any]) -> None:
        for key, attribute in (
            ("app.naming_template", "naming_template"),
            ("app.max_file_size_mb", "max_file_size_mb"),
            ("app.scan_batch_size", "scan_batch_size"),
            ("app.low_confidence", "low_confidence"),
            ("app.high_confidence", "high_confidence"),
            ("app.enable_llm", "enable_llm"),
            ("app.prefer_transformer", "prefer_transformer"),
            ("llm.model", "llm_model"),
            ("llm.base_url", "llm_base_url"),
        ):
            if key in values:
                setattr(self._config, attribute, values[key])
