"""Real adapter admission and session-specific rollout discovery without service calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.config import load_config
from lgcw.harness.codex import CodexHarness, rollout_path
from lgcw.live import LiveAdapterDisabledError

SESSION = "01a136dd-565b-7440-93b4-6acd056fc399"


@pytest.mark.unit
def test_codex_harness_refuses_without_live(tmp_path: Path) -> None:
    config = load_config(Path(__file__).parents[3], home=tmp_path)
    with pytest.raises(LiveAdapterDisabledError, match="CodexHarness"):
        CodexHarness(config)
    assert not config.codex_home.exists()


@pytest.mark.unit
def test_rollout_path_found(tmp_path: Path) -> None:
    folder = tmp_path / "sessions/2026/10/13"
    folder.mkdir(parents=True)
    own = folder / f"rollout-2026-10-13T20-00-00-{SESSION}.jsonl"
    own.write_text("{}\n")
    (folder / "rollout-other.jsonl").write_text("{}\n")
    assert rollout_path(tmp_path, SESSION) == own
    assert rollout_path(tmp_path, "01a136dd-565b-7440-93b4-6acd056fc398") is None


@pytest.mark.unit
@pytest.mark.parametrize("session_id", ["*", "../auth", "", SESSION + "*"])
def test_rollout_path_rejects_glob_or_traversal(tmp_path: Path, session_id: str) -> None:
    with pytest.raises(ValueError, match="session"):
        rollout_path(tmp_path, session_id)


@pytest.mark.unit
def test_rollout_path_refuses_symlink_escape(tmp_path: Path) -> None:
    folder = tmp_path / "sessions"
    folder.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n")
    (folder / f"rollout-{SESSION}.jsonl").symlink_to(outside)
    with pytest.raises(ValueError, match="escape"):
        rollout_path(tmp_path, SESSION)
