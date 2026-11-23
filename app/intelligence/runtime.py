"""Owns the local Ollama runtime for the lifetime of the desktop app.

OpenCoeus opens the Ollama desktop app (tray icon) when it starts and closes it,
including the server it spawns, when OpenCoeus closes. A runtime that is already
listening (started by the user or another app) is reused and never stopped.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.core.logging_config import get_logger

logger = get_logger(__name__)


def _launch_command() -> list[str] | None:
    if os.name == "nt":
        app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
        if app.is_file():
            return [str(app)]
    cli = shutil.which("ollama")
    return [cli, "serve"] if cli else None


class LocalRuntime:
    """Starts one Ollama runtime process and stops its process tree."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        startup_seconds: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.startup_seconds = startup_seconds
        self.process: subprocess.Popen[bytes] | None = None
        self._stopped = False

    def _reachable(self) -> bool:
        try:
            with urllib.request.urlopen(  # noqa: S310 - localhost only
                f"{self.base_url}/api/tags", timeout=2
            ):
                return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def start(self) -> bool:
        """Ensure the runtime answers; return True only if we started it."""

        if self._reachable() or self._stopped:
            return False
        command = _launch_command()
        if command is None:
            logger.info("Local language model runtime not installed; using templates.")
            return False
        kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        if self._stopped:
            return False
        try:
            process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
        except OSError as exc:
            logger.warning("Could not start the local language model runtime: %s", exc)
            return False
        self.process = process
        if self._stopped:
            self.stop()
            return False

        deadline = time.monotonic() + self.startup_seconds
        while time.monotonic() < deadline:
            if self._reachable():
                logger.info("Local language model runtime started (%s).", self.base_url)
                return True
            if self.process.poll() is not None:
                break
            time.sleep(0.2)
        logger.warning("Local language model runtime did not answer within startup time.")
        self.stop()
        return False

    def stop(self) -> None:
        """Stop the runtime we started; leave a foreign server alone."""

        self._stopped = True
        process = self.process
        if process is None:
            return
        self.process = None
        if os.name == "nt":
            if process.poll() is not None:
                return
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


__all__ = ["LocalRuntime"]
