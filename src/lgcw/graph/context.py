"""Frozen per-invocation dependencies; adapters are owned by the caller."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Self

from langgraph.runtime import Runtime
from pydantic import ConfigDict, Field, SecretStr, model_validator

from lgcw.clock import Clock
from lgcw.git.port import PushAuth, WorkspacePort
from lgcw.github.port import GitHubPort, TokenProvider
from lgcw.harness.port import HarnessPort
from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig, WorkflowConfig
from lgcw.models.issue import IssueRef
from lgcw.models.state import RunState
from lgcw.runlog import RunLog


class RunContext(Strict):
    """Trusted configuration and explicitly injected capabilities for one issue."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)
    config: WorkflowConfig
    repo: RepoConfig
    issue_ref: IssueRef
    github: GitHubPort
    workspace: WorkspacePort
    harness: HarnessPort
    clock: Clock
    log: RunLog
    workflow_login: str
    tokens: TokenProvider | None = Field(default=None, exclude=True, repr=False)

    def push_auth(self) -> PushAuth:
        """Read a code-only credential immediately before a guarded push."""
        if self.tokens is None:
            raise RuntimeError("code-side token provider is missing")
        return PushAuth(token=SecretStr(self.tokens.token()))

    @model_validator(mode="after")
    def consistent_target(self) -> Self:
        """Refuse a mismatched policy or target outside the configured allowlist."""
        if (
            self.issue_ref.repo != self.repo.full_name
            or self.config.repo(self.issue_ref.repo) != self.repo
        ):
            raise ValueError("run context target/policy mismatch")
        if not self.workflow_login:
            raise ValueError("workflow login must be established before running")
        return self


type NodeFn = Callable[[RunState, Runtime[RunContext]], Awaitable[dict[str, Any]]]
