"""Execution lanes and isolated per-test workflow environments."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


def pytest_configure(config: pytest.Config) -> None:
    """Register lanes even when this conftest runs in an isolated pytester project."""
    config.addinivalue_line("markers", "unit: isolated execution without network or LLM calls")
    config.addinivalue_line("markers", "live: real services; requires LGCW_LIVE=1")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Reject ambiguous lanes before filtering; require opt-in for live execution."""
    for item in items:
        lanes = [mark for mark in item.iter_markers() if mark.name in {"unit", "live"}]
        if len(lanes) != 1:
            raise pytest.UsageError(
                f"{item.nodeid}: exactly one explicit execution lane (unit or live) is required"
            )
        if lanes[0].name == "live" and os.environ.get("LGCW_LIVE") != "1":
            item.add_marker(pytest.mark.skip(reason="live lane requires LGCW_LIVE=1"))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate local workflow state and remove inherited credentials and tracing."""
    monkeypatch.setenv("LGCW_HOME", str(tmp_path / "lgcw"))
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
