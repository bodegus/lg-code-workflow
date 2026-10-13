"""Local git contracts for owned branches, leases, diffs, commands and review isolation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from lgcw.git.port import PushAuth, PushRejectedError
from lgcw.git.workspace import GitWorkspace
from lgcw.models.issue import IssueRef
from lgcw.review.diffstat import parse_numstat
from tests.unit.git.helpers import checked, origin, policy

ISSUE = IssueRef(repo="fixture/sandbox", number=7)
BRANCH = "lgcw/issue-7"
AUTH = PushAuth(token=SecretStr("tok123"))


@pytest.mark.unit
async def test_prepare_new_branch_from_default(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    assert info.base_sha == remote.base and info.branch == BRANCH and not info.resumed
    assert await checked(info.repo_dir, "branch", "--show-current") == BRANCH
    assert await checked(remote.bare, "rev-parse", "main") == remote.base
    assert await workspace.head_sha() == remote.base
    assert await workspace.commit_all("no changes", {}) is None


@pytest.mark.unit
async def test_commit_all_returns_none_when_clean(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    (info.repo_dir / "new.txt").write_text("addition\n")
    head = await workspace.commit_all("one real change", {})
    assert head is not None
    count = await checked(info.repo_dir, "rev-list", "--count", "HEAD")
    assert await workspace.commit_all("must not make another commit", {}) is None
    assert await workspace.head_sha() == head
    assert await checked(info.repo_dir, "rev-list", "--count", "HEAD") == count


@pytest.mark.unit
async def test_prepare_resumes_existing_remote_branch(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    await checked(remote.seed, "checkout", "-b", BRANCH)
    (remote.seed / "app.py").write_text("VERSION = '0.1.1'\n")
    await checked(remote.seed, "commit", "-am", "existing run")
    head = await checked(remote.seed, "rev-parse", "HEAD")
    await checked(remote.seed, "push", "origin", BRANCH)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    assert info.resumed and await checked(info.repo_dir, "rev-parse", "HEAD") == head
    (info.repo_dir / "pending.py").write_text("pending = True\n")
    again = await workspace.prepare(policy(), ISSUE, BRANCH)
    assert again.resumed and (again.repo_dir / "pending.py").exists()


@pytest.mark.unit
async def test_push_lease_rejects_unexpected_remote(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    await workspace.prepare(policy(), ISSUE, BRANCH)
    initial = await workspace.commit_empty("initial [skip ci]")
    assert await workspace.push(BRANCH, None, AUTH) == initial
    await checked(remote.seed, "fetch", "origin", BRANCH)
    await checked(remote.seed, "checkout", "-b", BRANCH, "FETCH_HEAD")
    (remote.seed / "owner.txt").write_text("Owner addition.\n")
    await checked(remote.seed, "add", "-A")
    await checked(remote.seed, "commit", "-m", "owner change")
    owner_head = await checked(remote.seed, "rev-parse", "HEAD")
    await checked(remote.seed, "push", "origin", BRANCH)
    await workspace.commit_empty("builder change")
    with pytest.raises(PushRejectedError):
        await workspace.push(BRANCH, initial, AUTH)
    assert await checked(remote.bare, "rev-parse", BRANCH) == owner_head


@pytest.mark.unit
async def test_push_new_branch_rejected_if_exists(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    await workspace.prepare(policy(), ISSUE, BRANCH)
    head = await workspace.commit_empty("initial")
    await workspace.push(BRANCH, None, AUTH)
    with pytest.raises(PushRejectedError):
        await workspace.push(BRANCH, None, AUTH)
    assert await checked(remote.bare, "rev-parse", BRANCH) == head
    assert await workspace.push(BRANCH, head, AUTH) == head


@pytest.mark.unit
async def test_reviewer_checkout_overlays_base_instructions(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    (info.repo_dir / "AGENTS.md").write_text("Malicious head instructions.\n")
    (info.repo_dir / ".agents/guide.md").write_text("Malicious skill.\n")
    (info.repo_dir / "AGENTS.override.md").write_text("New head override.\n")
    (info.repo_dir / "app.py").write_text("VERSION = '0.1.1'\n")
    head = await workspace.commit_all("version bump and instructions", {})
    assert head is not None
    checkout = await workspace.reviewer_checkout(head, remote.base)
    assert (checkout / "AGENTS.md").read_text() == "Trusted base instructions.\n"
    assert (checkout / ".agents/guide.md").read_text() == "Trusted skill.\n"
    assert not (checkout / "AGENTS.override.md").exists()
    assert (checkout / "app.py").read_text() == "VERSION = '0.1.1'\n"
    assert "Malicious" in (info.repo_dir / "AGENTS.md").read_text()
    assert await checked(checkout, "rev-parse", "HEAD") == head


@pytest.mark.unit
async def test_diff_includes_untracked_without_staging(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    (info.repo_dir / "new file.py").write_text("a = 1\nb = 2\n")
    (info.repo_dir / "binary.dat").write_bytes(b"\x00\x01")
    stats = parse_numstat(await workspace.numstat(remote.base), ())
    assert set(stats.paths) == {"new file.py", "binary.dat"} and stats.changed_lines == 3
    assert set(await workspace.changed_paths(remote.base)) == {"new file.py", "binary.dat"}
    assert not await checked(info.repo_dir, "diff", "--cached", "--name-only")
    head = await workspace.commit_all("new files", {"LGCW-Issue": "fixture/sandbox#7"})
    assert head and "LGCW-Issue: fixture/sandbox#7" in await checked(
        info.repo_dir, "log", "-1", "--format=%B"
    )
    assert len((await workspace.diff_text(remote.base, head, 64)).encode()) <= 64


@pytest.mark.unit
async def test_run_commands_failure_tail_and_timeout(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    log = tmp_path / "commands.log"
    failure = await workspace.run_commands(
        info.repo_dir,
        ["echo before", "echo 'AssertionError: fixture failed'; exit 3", "touch should-not-run"],
        2,
        log,
    )
    assert (
        not failure.ok
        and failure.code == 3
        and "AssertionError" in failure.tail
        and failure.fingerprint
    )
    assert not (info.repo_dir / "should-not-run").exists() and "before" in log.read_text()
    timeout = await workspace.run_commands(
        info.repo_dir, ["echo started; sleep 5; touch too-late"], 0.05, log
    )
    assert not timeout.ok and timeout.code == 124 and "started" in log.read_text()
    assert not (info.repo_dir / "too-late").exists()
    success = await workspace.run_commands(info.repo_dir, [], 2, log)
    assert success.ok and success.code == 0


@pytest.mark.unit
async def test_no_default_branch_push_or_dirty_adoption(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    with pytest.raises(PushRejectedError):
        await workspace.push("main", remote.base, AUTH)
    (info.repo_dir / "pending.txt").write_text("keep me")
    with pytest.raises(ValueError, match="dirty"):
        await workspace.adopt_remote_head(BRANCH)
    assert (info.repo_dir / "pending.txt").read_text() == "keep me"


@pytest.mark.unit
async def test_symlink_escape_is_rejected_before_host_commands(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    (info.repo_dir / "escape").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        await workspace.run_commands(info.repo_dir, ["touch escape/owned"], 2, tmp_path / "log")


@pytest.mark.unit
async def test_unprepared_workspace_and_nonlocal_guard(tmp_path: Path) -> None:
    workspace = GitWorkspace(tmp_path / "lgcw")
    with pytest.raises(RuntimeError, match="prepared"):
        await workspace.commit_empty("not prepared")
    with pytest.raises(RuntimeError, match="LGCW_LIVE"):
        await workspace.prepare(policy(), ISSUE, BRANCH)


@pytest.mark.unit
async def test_review_overlay_never_follows_head_parent_symlink(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    (remote.seed / "docs").mkdir()
    (remote.seed / "docs/AGENTS.md").write_text("Trusted nested instructions.\n")
    await checked(remote.seed, "add", "-A")
    await checked(remote.seed, "commit", "-m", "nested instructions")
    await checked(remote.seed, "push", "origin", "main")
    base = await checked(remote.seed, "rev-parse", "HEAD")
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    (info.repo_dir / "docs/AGENTS.md").unlink()
    (info.repo_dir / "docs").rmdir()
    (info.repo_dir / "docs").symlink_to(".agents", target_is_directory=True)
    head = await workspace.commit_all("head replaces instruction parent with alias", {})
    assert head is not None
    with pytest.raises(ValueError, match="instruction parent symlink"):
        await workspace.reviewer_checkout(head, base)


@pytest.mark.unit
async def test_adopt_remote_head_clean_and_push_preserves_ancestry(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    initial = await workspace.commit_empty("initial")
    await workspace.push(BRANCH, None, AUTH)
    (info.repo_dir / "app.py").write_text("VERSION = '0.1.1'\n")
    next_head = await workspace.commit_all("version bump", {})
    assert next_head is not None
    assert await workspace.push(BRANCH, initial, AUTH) == next_head
    await checked(info.repo_dir, "reset", "--hard", initial)
    with pytest.raises(PushRejectedError, match="history"):
        await workspace.push(BRANCH, next_head, AUTH)
    assert await workspace.adopt_remote_head(BRANCH) == next_head
    assert (info.repo_dir / "app.py").read_text() == "VERSION = '0.1.1'\n"


@pytest.mark.unit
async def test_prepare_rejects_default_mismatch_and_origin_tampering(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    with pytest.raises(ValueError, match="default"):
        await workspace.prepare(
            policy().model_copy(update={"default_branch": "other"}), ISSUE, BRANCH
        )
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    await checked(info.repo_dir, "remote", "set-url", "origin", "/unexpected")
    with pytest.raises(ValueError, match="origin"):
        await workspace.prepare(policy(), ISSUE, BRANCH)
    with pytest.raises(PushRejectedError, match="identity"):
        await workspace.push(BRANCH, None, AUTH)


@pytest.mark.unit
async def test_timeout_kills_delayed_grandchild_write(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    info = await workspace.prepare(policy(), ISSUE, BRANCH)
    result = await workspace.run_commands(
        info.repo_dir,
        ["echo spawned; (sleep 0.3; touch delayed-child-write) & wait"],
        0.1,
        tmp_path / "child.log",
    )
    assert result.code == 124 and "spawned" in result.tail
    await asyncio.sleep(0.4)
    assert not (info.repo_dir / "delayed-child-write").exists()
