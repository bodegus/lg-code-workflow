"""Typed local workspace capabilities and ephemeral push authentication."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import SecretStr

from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig
from lgcw.models.issue import IssueRef


class PushAuth(Strict):
    """An ephemeral credential that must never be placed in argv or git config."""

    token: SecretStr

    def env(self) -> dict[str, str]:
        """Return git's process-only HTTPS authorization configuration."""
        encoded = base64.b64encode(
            f"x-access-token:{self.token.get_secret_value()}".encode()
        ).decode()
        return {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded}",
        }


class WorkspaceInfo(Strict):
    """A clone bound to one issue and its allowed remote branch."""

    repo_dir: Path
    branch: str
    base_sha: str
    resumed: bool
    created: bool = False


class CommandResult(Strict):
    """Gate/setup outcome with redacted evidence and its full local log."""

    ok: bool
    command: str
    code: int
    tail: str
    fingerprint: str | None
    duration_s: float
    log_path: Path


class PushRejectedError(RuntimeError):
    """The proposed push would violate branch ownership or its exact lease."""


@runtime_checkable
class WorkspacePort(Protocol):
    """Workspace operations available to plain-code graph nodes."""

    async def prepare(self, repo: RepoConfig, issue: IssueRef, branch: str) -> WorkspaceInfo:
        """Prepare or resume the issue's owned clone without discarding dirty state."""
        ...

    async def head_sha(self) -> str:
        """Read the local committed head for publish recovery without making another commit."""
        ...

    async def commit_message(self, sha: str) -> str:
        """Read an operation trailer for commit-before-receipt recovery."""
        ...

    async def run_commands(
        self, cwd: Path, commands: Sequence[str], timeout_s: float, log_path: Path
    ) -> CommandResult:
        """Run trusted setup/gate commands with a bound and redacted logs."""
        ...

    async def numstat(self, base_sha: str) -> str:
        """Return NUL-delimited counts including untracked changes."""
        ...

    async def changed_paths(self, base_sha: str) -> tuple[str, ...]:
        """Return all changed paths including untracked files."""
        ...

    async def commit_all(self, message: str, trailers: Mapping[str, str]) -> str | None:
        """Commit all changed files, returning None when clean."""
        ...

    async def commit_empty(self, message: str) -> str:
        """Create the initial empty checkpoint without running repository hooks."""
        ...

    async def push(self, branch: str, expected_remote_sha: str | None, auth: PushAuth) -> str:
        """Push only the owned branch using an explicit full-ref lease."""
        ...

    async def diff_text(self, from_sha: str, to_sha: str, max_bytes: int) -> str:
        """Return a byte-bounded committed diff."""
        ...

    async def adopt_remote_head(self, branch: str) -> str:
        """Explicitly adopt an owner head, refusing dirty local state."""
        ...

    async def reviewer_checkout(self, head_sha: str, base_sha: str) -> Path:
        """Create an isolated detached checkout with base agent instructions."""
        ...
