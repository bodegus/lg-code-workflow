"""Real local git fixture and injected complete graph for the implemented intake nodes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime
from pydantic import ConfigDict

from lgcw.graph.build_graph import STEPS, NodeFn
from lgcw.graph.context import RunContext
from lgcw.graph.nodes import DEFAULT_NODES
from lgcw.graph.runner import run_issue
from lgcw.models.base import Step, Strict
from lgcw.models.state import RunOutcome, RunState
from tests.fakes.github import FakeGitHub
from tests.fakes.workspace import RecordingWorkspace
from tests.unit.git.helpers import LocalOrigin, origin
from tests.unit.graph.cases import context
from tests.unit.harness.cases import issue


class FixtureTokens:
    """Synthetic code-side credential; never a real token or agent input."""

    def token(self) -> str:
        """Return the public unit fixture value."""
        return "tok123"


class GraphCase(Strict):
    """Typed test dependencies with a reusable service backend."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    ctx: RunContext
    github: FakeGitHub
    workspace: RecordingWorkspace
    origin: LocalOrigin

    async def run(self) -> RunOutcome:
        """Run real registered nodes and stop at an explicit unit-only build checkpoint."""

        async def checkpoint(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
            runtime.context.log.event("unit_checkpoint", node="build")
            return {"next_step": "end", "outcome": "waiting"}

        mapping: dict[Step, NodeFn] = {step: checkpoint for step in STEPS if step != "end"}
        real_steps: tuple[Step, ...] = ("reconcile", "intake", "open_pr", "ask", "blocked")
        mapping.update({step: DEFAULT_NODES[step] for step in real_steps})
        return await run_issue(self.ctx, nodes=mapping)


@pytest.fixture
async def graph_case(tmp_path: Path) -> GraphCase:
    remote = await origin(tmp_path)
    ctx = context(tmp_path / "lgcw")
    github = FakeGitHub(clock=ctx.clock, login=ctx.workflow_login)
    snapshot = issue().model_copy(
        update={"repo": ctx.issue_ref.repo, "number": ctx.issue_ref.number}
    )
    github.issues[(snapshot.repo, snapshot.number)] = snapshot
    workspace = RecordingWorkspace(ctx.config.home, remote.bare, github, ctx.repo.full_name)
    ctx = ctx.model_copy(
        update={"github": github, "workspace": workspace, "tokens": FixtureTokens()}
    )
    return GraphCase(ctx=ctx, github=github, workspace=workspace, origin=remote)
