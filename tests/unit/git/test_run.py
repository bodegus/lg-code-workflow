"""Subprocess boundaries, credential safety, hooks and process lifetime."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from lgcw.git.port import PushAuth
from lgcw.git.run import git
from tests.unit.git.helpers import checked, origin


@pytest.mark.unit
async def test_token_never_in_argv_or_config(tmp_path: Path) -> None:
    await checked(tmp_path, "init")
    auth = PushAuth(token=SecretStr("tok123"))
    result = await git(
        "config", "--get", "http.https://github.com/.extraheader", cwd=tmp_path, env=auth.env()
    )
    assert result.code == 0
    assert "tok123" not in " ".join(result.argv)
    assert "tok123" not in (tmp_path / ".git/config").read_text()
    assert "Authorization" not in (tmp_path / ".git/config").read_text()
    assert "[REDACTED]" in result.out
    assert auth.env()["GIT_CONFIG_VALUE_0"] not in result.out
    assert "tok123" not in repr(auth)


@pytest.mark.unit
async def test_hooks_disabled(tmp_path: Path) -> None:
    await checked(tmp_path, "init")
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\ntouch hook-ran\n")
    hook.chmod(0o755)
    await checked(tmp_path, "commit", "--allow-empty", "-m", "fixture")
    assert not (tmp_path / "hook-ran").exists()


@pytest.mark.unit
async def test_git_environment_does_not_inherit_secret_or_redirect_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await checked(tmp_path, "init")
    monkeypatch.setenv("GH_TOKEN", "synthetic-secret")
    monkeypatch.setenv("GIT_DIR", "/missing/foreign.git")
    result = await git("-c", "alias.env=!env", "env", cwd=tmp_path)
    assert result.code == 0 and "synthetic-secret" not in result.out
    assert "GIT_TERMINAL_PROMPT=0" in result.out


@pytest.mark.unit
async def test_git_timeout_and_cancellation_kill_children(tmp_path: Path) -> None:
    await checked(tmp_path, "init")
    timeout = await git("-c", "alias.slow=!sleep 5", "slow", cwd=tmp_path, timeout_s=0.05)
    assert timeout.code == 124 and "timed out" in timeout.err
    task = asyncio.create_task(git("-c", "alias.slow=!sleep 5", "slow", cwd=tmp_path))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.unit
async def test_auth_rejected_in_argv(tmp_path: Path) -> None:
    auth = PushAuth(token=SecretStr("tok123"))
    with pytest.raises(ValueError, match="credential"):
        await git("config", "unsafe", "tok123", cwd=tmp_path, env=auth.env())


@pytest.mark.unit
async def test_token_shaped_literal_rejected_before_process_start(tmp_path: Path) -> None:
    synthetic = "ghp_" + "A" * 36
    with pytest.raises(ValueError, match="credential"):
        await git("config", "unsafe", synthetic, cwd=tmp_path)


@pytest.mark.unit
async def test_missing_git_executable_has_safe_error(tmp_path: Path) -> None:
    result = await git("status", cwd=tmp_path, env={"PATH": str(tmp_path)})
    assert result.code == 127 and result.err


@pytest.mark.unit
async def test_native_force_lease_rejects_stale_head(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    branch = "lgcw/issue-7"
    await checked(remote.seed, "checkout", "-b", branch)
    await checked(remote.seed, "push", "origin", branch)
    await checked(remote.seed, "commit", "--allow-empty", "-m", "owner advances")
    owner_head = await checked(remote.seed, "rev-parse", "HEAD")
    await checked(remote.seed, "push", "origin", branch)
    result = await git(
        "push",
        f"--force-with-lease=refs/heads/{branch}:{remote.base}",
        "origin",
        f"{remote.base}:refs/heads/{branch}",
        cwd=remote.seed,
    )
    assert result.code != 0 and "stale info" in result.err
    assert await checked(remote.bare, "rev-parse", branch) == owner_head


@pytest.mark.unit
async def test_success_kills_background_process_group(tmp_path: Path) -> None:
    from lgcw.git.run import run_process

    result = await run_process(
        ("/bin/sh", "-c", "(sleep 0.3; touch escaped) >/dev/null 2>&1 & exit 0"), cwd=tmp_path
    )
    assert result.code == 0
    await asyncio.sleep(0.5)
    assert not (tmp_path / "escaped").exists()


@pytest.mark.unit
async def test_timeout_does_not_wait_on_escaped_child_pipe(tmp_path: Path) -> None:
    import os
    import signal
    import sys

    from lgcw.git.run import run_process

    # The child leaves the process group and retains stdout. Parent group kill cannot close
    # that pipe; the runner must bound capture draining independently. Cleanup owns the PID.
    code = (
        "import os,time; pid=os.fork(); "
        "os.setsid() if pid == 0 else None; "
        "open('child.pid','w').write(str(os.getpid())) if pid == 0 else None; "
        "time.sleep(10)"
    )
    try:
        async with asyncio.timeout(2):
            result = await run_process((sys.executable, "-c", code), cwd=tmp_path, timeout_s=0.2)
        assert result.code == 124
    finally:
        pid_file = tmp_path / "child.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
