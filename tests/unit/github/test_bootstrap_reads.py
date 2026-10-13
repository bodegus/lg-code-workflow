"""Bootstrap read capabilities preserve the remote head and original draft body."""

from __future__ import annotations

import pytest

from tests.fakes.github import FakeGitHub


@pytest.mark.unit
async def test_branch_head_and_pr_document_round_trip() -> None:
    github = FakeGitHub()
    assert await github.branch_head("example/sandbox", "lgcw/issue-1") is None
    github.branch_heads[("example/sandbox", "lgcw/issue-1")] = "a" * 40
    pr = await github.create_draft_pr(
        "example/sandbox", "lgcw/issue-1", "main", "Fixture", "original body"
    )
    document = await github.get_pr_document("example/sandbox", pr.number)
    assert document.body == "original body" and document.author == github.login
    assert await github.branch_head("example/sandbox", "lgcw/issue-1") == pr.head_sha
