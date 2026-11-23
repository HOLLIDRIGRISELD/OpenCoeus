"""Data directory precedence and read-only fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import AppConfig
from app.core.exceptions import ConfigurationError


def test_env_data_dir_overrides_default(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "env"
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(target))
    assert AppConfig.load().data_dir == target


def test_explicit_data_dir_beats_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(tmp_path / "env"))
    explicit = tmp_path / "explicit"
    assert AppConfig.load(explicit).data_dir == explicit


def test_json_data_dir_recomputes_db_url(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "from_json"
    (tmp_path / "config.json").write_text(
        json.dumps({"data_dir": str(target)}), encoding="utf-8"
    )
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path)
    config = AppConfig.load()
    assert config.data_dir == target
    assert config.db_path == target / "opencoeus.db"


def test_env_beats_json_data_dir(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / "env"
    (tmp_path / "config.json").write_text(
        json.dumps({"data_dir": str(tmp_path / "from_json")}), encoding="utf-8"
    )
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path)
    monkeypatch.setenv("OPENCOEUS_DATA_DIR", str(env))
    assert AppConfig.load().data_dir == env


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://example.com:11434",
        "https://user:secret@127.0.0.1:11434",
        "ftp://127.0.0.1:11434",
        "http://127.0.0.1.evil.test:11434",
        "http://[::2]:11434",
        "http://localhost:not-a-port",
    ],
)
def test_config_rejects_non_loopback_llm_url(
    tmp_path: Path, monkeypatch, url: str
) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"llm_base_url": url}), encoding="utf-8"
    )
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path)

    with pytest.raises(ConfigurationError, match="llm.base_url"):
        AppConfig.load()


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
def test_config_accepts_loopback_llm_url(tmp_path: Path, monkeypatch, url: str) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"llm_base_url": url}), encoding="utf-8"
    )
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path)

    assert AppConfig.load().llm_base_url == url


@pytest.mark.parametrize(
    ("payload", "key"),
    [
        ({"max_file_size_mb": "large"}, "max_file_size_mb"),
        ({"scan_batch_size": 0}, "scan_batch_size"),
        ({"max_folder_depth": -1}, "max_folder_depth"),
        ({"high_confidence": 1.5}, "high_confidence"),
        ({"low_confidence": 0.9, "high_confidence": 0.5}, "low_confidence"),
        ({"enable_llm": "perhaps"}, "enable_llm"),
        ({"supported_extensions": ".pdf"}, "supported_extensions"),
        ({"excluded_directories": [1]}, "excluded_directories"),
    ],
)
def test_config_rejects_invalid_values_with_key_specific_error(
    tmp_path: Path, monkeypatch, payload: dict[str, object], key: str
) -> None:
    (tmp_path / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path)

    with pytest.raises(ConfigurationError, match=key):
        AppConfig.load()


def test_unwritable_dir_falls_back(tmp_path: Path, monkeypatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: tmp_path / "fallback")
    assert AppConfig.load(blocker / "child").data_dir == tmp_path / "fallback"


def test_all_unwritable_raises(tmp_path: Path, monkeypatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.delenv("OPENCOEUS_DATA_DIR", raising=False)
    monkeypatch.setattr("app.core.config.default_data_dir", lambda: blocker / "child")
    with pytest.raises(ConfigurationError):
        AppConfig.load(blocker / "child")
