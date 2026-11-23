"""Lifecycle tests for the local LLM runtime managed by the desktop app."""

from __future__ import annotations

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.intelligence import runtime as runtime_module
from app.intelligence.runtime import LocalRuntime


class FakeProcess:
    pid = 4321

    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


def test_an_already_running_server_is_used_but_never_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalRuntime("http://127.0.0.1:11434")
    monkeypatch.setattr(runtime, "_reachable", lambda: True)

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("a running server must not be started again")

    monkeypatch.setattr(subprocess, "Popen", fail)

    assert runtime.start() is False
    runtime.stop()


def test_stop_before_start_prevents_popen(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LocalRuntime("http://127.0.0.1:11434")
    monkeypatch.setattr(runtime, "_reachable", lambda: False)

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("stopped runtime must not launch a process")

    monkeypatch.setattr(subprocess, "Popen", fail)
    runtime.stop()

    assert runtime.start() is False


def test_start_opens_the_headless_server_and_stop_kills_its_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalRuntime("http://127.0.0.1:11434", startup_seconds=1)
    probe = iter([False, True])
    monkeypatch.setattr(runtime, "_reachable", lambda: next(probe))
    monkeypatch.setattr(
        "app.intelligence.runtime._launch_command", lambda: ["ollama.exe", "serve"]
    )
    process = FakeProcess()
    launched: list[list[str]] = []
    stopped: list[list[str]] = []

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        launched.append(command)
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: stopped.append(command))

    assert runtime.start() is True
    assert launched == [["ollama.exe", "serve"]]

    runtime.stop()
    assert runtime.process is None
    if os.name == "nt":
        assert stopped == [["taskkill", "/PID", "4321", "/T", "/F"]]
        assert process.terminated is False
    else:
        assert stopped == []
        assert process.terminated is True
        assert process.killed is False


def test_stop_does_not_kill_a_pid_the_process_no_longer_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalRuntime("http://127.0.0.1:11434")
    process = FakeProcess()
    process.poll = lambda: 0
    runtime.process = process
    stopped: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: stopped.append(command))

    runtime.stop()

    assert runtime.process is None
    if os.name == "nt":
        assert stopped == []


def test_stop_during_popen_leaves_no_live_process(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LocalRuntime("http://127.0.0.1:11434", startup_seconds=1)
    probe = iter([False, True])
    monkeypatch.setattr(runtime, "_reachable", lambda: next(probe, True))
    monkeypatch.setattr("app.intelligence.runtime._launch_command", lambda: ["fake"])
    process = FakeProcess()
    popen_entered = threading.Event()
    release_popen = threading.Event()

    def blocking_popen(command: list[str], **kwargs: object) -> FakeProcess:
        popen_entered.set()
        assert release_popen.wait(timeout=5)
        return process

    stopped: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", blocking_popen)
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: stopped.append(command))
    result: dict[str, bool] = {}

    thread = threading.Thread(target=lambda: result.update(value=runtime.start()))
    thread.start()
    assert popen_entered.wait(timeout=5)
    runtime.stop()
    release_popen.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert result["value"] is False
    assert runtime.process is None
    if os.name == "nt":
        assert stopped == [["taskkill", "/PID", "4321", "/T", "/F"]]
    else:
        assert process.terminated is True


def test_reachable_detects_a_live_and_a_dead_endpoint() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            body = b'{"models": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        runtime = LocalRuntime(f"http://127.0.0.1:{server.server_port}")
        assert runtime._reachable() is True
    finally:
        server.shutdown()
        server.server_close()
    assert runtime._reachable() is False


def test_no_launch_command_means_no_process_and_no_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalRuntime("http://127.0.0.1:11434")
    monkeypatch.setattr(runtime, "_reachable", lambda: False)
    monkeypatch.setattr("app.intelligence.runtime._launch_command", lambda: None)

    assert runtime.start() is False
    runtime.stop()


def test_launch_command_uses_headless_server_on_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "Programs" / "Ollama"
    folder.mkdir(parents=True)
    headless = folder / "ollama.exe"
    headless.write_bytes(b"")
    (folder / "ollama app.exe").write_bytes(b"")
    monkeypatch.setattr(runtime_module.os, "name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(runtime_module.shutil, "which", lambda name: None)

    assert runtime_module._launch_command() == [str(headless), "serve"]
