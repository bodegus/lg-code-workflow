"""Opt-in, read-only qualification of branch-required check discovery."""

from __future__ import annotations

import pytest

from lgcw.github.client import GitHubClient
from lgcw.github.token import GhCliTokenProvider


@pytest.mark.live
async def test_required_policy_read() -> None:
    """Exercise real paginated rules and classic protection without writing to GitHub."""
    client = GitHubClient(GhCliTokenProvider())
    for repo in ("bodegus/lg-code-workflow", "bodegus/family-calendar"):
        contexts = await client.required_check_contexts(repo, "main")
        assert tuple(sorted(set(contexts))) == contexts
        assert all(context for context in contexts)
        print(repo, "required contexts:", contexts)
