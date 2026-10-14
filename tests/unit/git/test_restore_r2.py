"""Owned publication ancestry must be exact even when trailers are copied."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.git.workspace import GitWorkspace
from lgcw.models.issue import IssueRef
from tests.unit.git.helpers import checked, origin, policy


@pytest.mark.unit
@pytest.mark.parametrize("merge", [False, True])
async def test_restore_requires_exact_single_parent(tmp_path: Path, merge: bool) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(
        policy(), IssueRef(repo="fixture/sandbox", number=7), "lgcw/issue-7"
    )
    operation = "a" * 16
    trailers = {"LGCW-Operation": operation, "LGCW-Parent": remote.base}
    (info.repo_dir / "new.txt").write_text("fixture\n")
    candidate = await workspace.commit_all("owned candidate", trailers)
    assert candidate is not None
    message = await workspace.commit_message(candidate)
    if merge:
        tree = await checked(info.repo_dir, "rev-parse", candidate + "^{tree}")
        wrong = await checked(
            info.repo_dir, "commit-tree", tree, "-p", remote.base, "-p", candidate, "-m", message
        )
        await checked(info.repo_dir, "reset", "--hard", wrong)
    else:
        await checked(info.repo_dir, "commit", "--allow-empty", "-m", message)
        wrong = await workspace.head_sha()
    with pytest.raises(ValueError, match="publication proof"):
        await workspace.restore_owned_commit(wrong, wrong, operation, remote.base)
    assert await workspace.head_sha() == wrong
