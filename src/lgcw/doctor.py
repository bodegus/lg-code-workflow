"""Bounded host prerequisites without a paid turn or credential output."""

from __future__ import annotations

import fcntl
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from codex_cli_bin import bundled_codex_path

from lgcw.harness.env import build_codex_env
from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig, WorkflowConfig


class Check(Strict):
    """A printable prerequisite result without command output or credentials."""

    name: str
    ok: bool
    detail: str


class ProbeResult(Strict):
    """Only the status of a privately captured host command."""

    code: int
    version: tuple[int, int, int] | None = None


class DoctorPort(Protocol):
    """Inject executable discovery and bounded commands at the host boundary."""

    def which(self, name: str) -> Path | None:
        """Locate one executable without invoking it."""
        ...

    def run(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> ProbeResult:
        """Capture command output privately; return only its status."""
        ...


class HostProbe:
    """Standard-library host probes; never print auth command stdout/stderr."""

    def which(self, name: str) -> Path | None:
        """Locate an installed executable."""
        found = shutil.which(name)
        return Path(found) if found else None

    def run(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> ProbeResult:
        """Run one bounded prerequisite probe without exposing its output."""
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                env=dict(env) if env is not None else None,
                timeout=20,
                check=False,
            )
            match = (
                re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
                if argv[-1] == "--version"
                else None
            )
            version = (int(match[1]), int(match[2]), int(match[3])) if match else None
            return ProbeResult(code=result.returncode, version=version)
        except (OSError, subprocess.TimeoutExpired):
            return ProbeResult(code=-1)


def doctor(
    config: WorkflowConfig, repo: RepoConfig | None, *, probe: DoctorPort | None = None
) -> list[Check]:
    """Check configured tools, owner login, dedicated Codex login and writable local state."""
    host = probe if probe is not None else HostProbe()
    checks: list[Check] = []
    try:
        config.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryFile(dir=config.home):
            pass
        checks.append(Check(name="home", ok=True, detail=str(config.home)))
    except OSError:
        checks.append(Check(name="home", ok=False, detail="Workflow home is not writable."))
        return checks
    repos = [repo] if repo is not None else list(config.repos.values())
    tools = {"git", "gh"}
    for policy in repos:
        tools.update(policy.tool_minimums)
        tools.update(policy.tool_maximums)
        for command in (*policy.setup, *policy.gate):
            words = shlex.split(command)
            if words:
                tools.add(words[0])
    if "npm" in tools:
        tools.add("node")
    found = {name: host.which(name) for name in sorted(tools)}
    checks.extend(
        Check(
            name="tool:" + name,
            ok=path is not None,
            detail="Available" if path else "Install " + name,
        )
        for name, path in found.items()
    )
    for policy in repos:
        for name in sorted(policy.tool_minimums.keys() | policy.tool_maximums.keys()):
            if found[name] is None:
                continue
            result = host.run((name, "--version"))
            minimum, maximum = policy.tool_minimums.get(name), policy.tool_maximums.get(name)
            version = result.version
            ok = (
                result.code == 0
                and version is not None
                and (minimum is None or version >= minimum)
                and (maximum is None or version < maximum)
            )
            requirements = []
            if minimum is not None:
                requirements.append(">=" + ".".join(str(part) for part in minimum))
            if maximum is not None:
                requirements.append("<" + ".".join(str(part) for part in maximum))
            current = ".".join(str(part) for part in version) if version else "unavailable"
            checks.append(
                Check(
                    name="version:" + name,
                    ok=ok,
                    detail=f"{current}; needs {' and '.join(requirements)}",
                )
            )
    if found["git"] is not None:
        checks.append(
            Check(name="git", ok=host.run(("git", "--version")).code == 0, detail="git --version")
        )
    if found["gh"] is not None:
        checks.append(
            Check(
                name="github_login",
                ok=host.run(("gh", "auth", "status")).code == 0,
                detail="Run gh auth login if this check fails.",
            )
        )
    binary = host.which(str(bundled_codex_path()))
    if binary is None:
        checks.append(
            Check(name="codex_login", ok=False, detail="Pinned Codex runtime missing; uv sync.")
        )
        return checks
    config.codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (config.codex_home / "lgcw-server.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            checks.append(
                Check(name="codex_login", ok=False, detail="Dedicated Codex profile is busy.")
            )
            return checks
        env = build_codex_env(config, os.environ)
        result = host.run((str(binary), "login", "status"), env)
        sandbox = host.run(
            (str(binary), "sandbox", "-P", ":workspace", "--", "gh", "auth", "status"), env
        )
        checks.append(
            Check(
                name="github_sandbox_isolation",
                ok=sandbox.code == 1,
                detail="Builder sandbox must deny the owner's GitHub login.",
            )
        )
    checks.append(
        Check(
            name="codex_login",
            ok=result.code == 0,
            detail=f"Dedicated profile: {config.codex_home}; login there if this fails.",
        )
    )
    return checks
