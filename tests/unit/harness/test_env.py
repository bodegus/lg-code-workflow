"""Minimal child environment independent of inherited credentials."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.config import load_config
from lgcw.harness.env import build_codex_env


@pytest.mark.unit
def test_env_is_minimal(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path / "state")
    base = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "LANG": "en_US.UTF-8",
        "CODEX_HOME": "/wrong",
        "GH_TOKEN": "synthetic",
        "OPENAI_API_KEY": "synthetic",
        "LANGSMITH_TRACING": "true",
    }
    assert build_codex_env(config, base) == {
        "PATH": base["PATH"],
        "HOME": base["HOME"],
        "LANG": base["LANG"],
        "CODEX_HOME": str(config.codex_home),
    }
    assert base["CODEX_HOME"] == "/wrong"


@pytest.mark.unit
def test_env_defaults_are_explicit(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    env = build_codex_env(config, {})
    assert set(env) == {"PATH", "HOME", "LANG", "CODEX_HOME"}
    assert all(env.values())
