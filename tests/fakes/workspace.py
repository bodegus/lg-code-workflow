"""Recording workspace port over real temp git, with post-effect crash injection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from lgcw.git.port import CommandResult, PushAuth, WorkspaceInfo
from lgcw.git.workspace import GitWorkspace
from lgcw.models.config import RepoConfig
from lgcw.models.issue import IssueRef
from tests.fakes.github import FakeGitHub


class InjectedCrash(BaseException):
    """Simulated process loss that bypasses normal exception-to-question handling."""


class RecordingWorkspace(GitWorkspace):
    """Record public port effects; no patch inside the production adapter."""

    def __init__(self, home: Path, origin: Path, github: FakeGitHub, repo: str) -> None:
        super().__init__(home, origin=origin)
        self.github = github
        self.repo = repo
        self.pushes: list[str] = []
        self.prepares: list[WorkspaceInfo] = []
        self.empty_commits: list[str] = []
        self.commits: list[str] = []
        self.restores: list[tuple[str, str]] = []
        self.commit_edits: dict[str, str] = {}
        self.command_runs: list[tuple[str, ...]] = []
        self.crash_after: str | None = None

    def _done(self, name: str) -> None:
        if self.crash_after == name:
            self.crash_after = None
            raise InjectedCrash(name)

    async def prepare(self, repo: RepoConfig, issue: IssueRef, branch: str) -> WorkspaceInfo:
        """Record actual preparations for pre-clone guard assertions."""
        result = await super().prepare(repo, issue, branch)
        self.prepares.append(result)
        return result

    async def commit_empty(self, message: str) -> str:
        result = await super().commit_empty(message)
        self.empty_commits.append(result)
        self._done("commit_empty")
        return result

    async def commit_all(self, message: str, trailers: Mapping[str, str]) -> str | None:
        """Record actual commits and inject loss before the caller's commit receipt."""
        for name, content in self.commit_edits.items():
            (self.prepares[-1].repo_dir / name).write_text(content)
        self.commit_edits.clear()
        result = await super().commit_all(message, trailers)
        if result is not None:
            self.commits.append(result)
            self._done("commit_all")
        return result

    async def push(
        self,
        branch: str,
        expected_remote_sha: str | None,
        auth: PushAuth,
        *,
        head_sha: str | None = None,
    ) -> str:
        result = await super().push(branch, expected_remote_sha, auth, head_sha=head_sha)
        self.github.branch_heads[(self.repo, branch)] = result
        self.pushes.append(result)
        self._done("push")
        return result

    async def restore_owned_commit(
        self, expected_head: str, target_head: str, operation: str, parent_sha: str
    ) -> str:
        result = await super().restore_owned_commit(
            expected_head, target_head, operation, parent_sha
        )
        self.restores.append((expected_head, target_head))
        self._done("restore_owned_commit")
        return result

    async def run_commands(
        self, cwd: Path, commands: Sequence[str], timeout_s: float, log_path: Path
    ) -> CommandResult:
        result = await super().run_commands(cwd, commands, timeout_s, log_path)
        self.command_runs.append(tuple(commands))
        self._done("run_commands")
        return result
