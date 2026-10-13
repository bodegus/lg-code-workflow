"""Real adapters refuse to open their live capability accidentally."""

from __future__ import annotations

import pytest

from lgcw.github.client import GitHubClient
from lgcw.live import LiveAdapterDisabledError, require_live


class NeverToken:
    """A provider that proves the guard precedes credential access."""

    def token(self) -> str:
        """Fail if a disabled client tries to read credentials."""
        raise AssertionError("credential provider was reached")


@pytest.mark.unit
def test_client_refuses_without_live() -> None:
    with pytest.raises(LiveAdapterDisabledError, match="GitHubClient"):
        GitHubClient(NeverToken())


@pytest.mark.unit
@pytest.mark.parametrize("value", ["0", "true", "", "yes"])
def test_live_requires_exact_opt_in(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LGCW_LIVE", value)
    with pytest.raises(LiveAdapterDisabledError):
        require_live("synthetic", False)


@pytest.mark.unit
def test_live_guard_accepts_explicit_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    require_live("synthetic", True)
    monkeypatch.setenv("LGCW_LIVE", "1")
    require_live("synthetic", False)
