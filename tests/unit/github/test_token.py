"""Code-only CLI credentials, expiry and failure without a real login."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from lgcw.github.token import GhCliTokenProvider, TokenUnavailableError
from lgcw.runlog import redact
from tests.fakes.clock import FakeClock


def _fake_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str, *, failure: bool = False
) -> Path:
    command = tmp_path / "gh"
    calls = tmp_path / "calls"
    command.write_text(
        '#!/bin/sh\n[ "$1" = auth ] && [ "$2" = token ] || exit 2\n'
        'printf "call\\n" >> "$LGCW_TEST_GH_CALLS"\n'
        + ("exit 1\n" if failure else 'printf "%s\\n" "$LGCW_TEST_TOKEN"\n')
    )
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("LGCW_TEST_GH_CALLS", str(calls))
    monkeypatch.setenv("LGCW_TEST_TOKEN", output)
    return calls


@pytest.mark.unit
def test_token_from_fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    synthetic = "ghp_" + "A" * 36
    _fake_gh(tmp_path, monkeypatch, synthetic)
    token = GhCliTokenProvider().token()
    assert token == synthetic
    assert synthetic not in redact(f"synthetic captured output: {token}")


@pytest.mark.unit
async def test_token_cached_fifty_minutes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_gh(tmp_path, monkeypatch, "synthetic-value")
    clock = FakeClock(datetime(2026, 10, 13, tzinfo=UTC))
    provider = GhCliTokenProvider(clock=clock)
    assert provider.token() == "synthetic-value"
    await clock.sleep(2999)
    assert provider.token() == "synthetic-value"
    assert calls.read_text().count("call") == 1
    await clock.sleep(1)
    assert provider.token() == "synthetic-value"
    assert calls.read_text().count("call") == 2


@pytest.mark.unit
@pytest.mark.parametrize("failure", [False, True])
def test_token_failure_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    _fake_gh(tmp_path, monkeypatch, "", failure=failure)
    with pytest.raises(TokenUnavailableError, match="gh auth login"):
        GhCliTokenProvider().token()
