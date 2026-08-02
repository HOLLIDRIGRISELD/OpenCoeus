from .config import LLMConfig
from .downloader import (
    BIN_DIR,
    MODELS_DIR,
    PHI3_GGUF_FILENAME,
    Qwen25_GGUF_FILENAME,
    is_llama_cli_downloaded,
    is_model_downloaded,
    llama_cli_path,
    model_path,
)
from .engine import LLMEngine
from .prompts import USER_TEMPLATE
from .result import LLMGenerationResult


def build_llm_engine(profile) -> LLMEngine | None:
    """Build an enabled LLM engine from a profile, or None when disabled."""
    if profile is None or not getattr(profile, "llm_enabled", False):
        return None
    return LLMEngine(
        LLMConfig(
            enabled=True,
            model=getattr(profile, "llm_model", "phi3"),
            temperature=getattr(profile, "llm_temperature", 0.3),
        )
    )


__all__ = [
    "BIN_DIR",
    "LLMConfig",
    "LLMEngine",
    "LLMGenerationResult",
    "MODELS_DIR",
    "PHI3_GGUF_FILENAME",
    "Qwen25_GGUF_FILENAME",
    "USER_TEMPLATE",
    "build_llm_engine",
    "is_llama_cli_downloaded",
    "is_model_downloaded",
    "llama_cli_path",
    "model_path",
]
