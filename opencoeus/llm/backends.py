from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import LLMConfig
from .downloader import llama_cli_path

logger = logging.getLogger(__name__)


class _Backend:

    def generate(self, prompt: str, max_tokens: int = 128) -> str:
        raise NotImplementedError


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
