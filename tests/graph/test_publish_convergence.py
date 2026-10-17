"""Post-push lag must not cause another push or adoption of foreign work."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

import pytest

from tests.fakes.clock import FakeClock
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import execute, markers, output, setup
from tests.unit.git.helpers import checked


class PublishClock(FakeClock):
    """Advance fake time and optionally push competing work during backoff."""

    callback: Callable[[], Awaitable[None]] | None = None

    async def sleep(self, seconds: float) -> None:
        await super().sleep(seconds)
        if self.callback is not None:
            callback, self.callback = self.callback, None
            await callback()


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["lag", "foreign", "timeout"])
@pytest.mark.parametrize("crash", [False, True])
async def test_post_push_convergence(
    graph_case: GraphCase, mode: Literal["lag", "foreign", "timeout"], crash: bool
) -> None:
    ctx, harness = await setup(graph_case, [{"app.py": "VERSION = '0.1.1'\n"}], [output("app.py")])
    github, workspace = graph_case.github, graph_case.workspace
    key = (ctx.issue_ref.repo, 100)
    parent = github.prs[key].head_sha
    branch = github.prs[key].head_ref
    clock = PublishClock(ctx.clock.now())
    github.clock = clock
    ctx = ctx.model_copy(update={"clock": clock})
    started = clock.now()
    pushed = False
    foreign = ""

    async def compete() -> None:
        nonlocal foreign
        await checked(graph_case.origin.seed, "fetch", "origin", branch)
        await checked(graph_case.origin.seed, "checkout", "--detach", "FETCH_HEAD")
        await checked(graph_case.origin.seed, "commit", "--allow-empty", "-m", "foreign work")
        foreign = await checked(graph_case.origin.seed, "rev-parse", "HEAD")
        await checked(graph_case.origin.seed, "push", "origin", f"HEAD:refs/heads/{branch}")
        github.branch_heads[(ctx.issue_ref.repo, branch)] = foreign
        github.pr_head_overrides[key] = foreign

    def after_push(head: str) -> None:
        nonlocal pushed
        pushed = True
        github.pr_head_overrides[key] = parent
        if mode == "foreign":
            clock.callback = compete
        if crash:
            github.fail_after("get_pr", 1, InjectedCrash("post-push read lost"))

    def after_read(method: str) -> None:
        if pushed and mode == "lag" and (clock.now() - started).total_seconds() >= 3:
            github.pr_head_overrides.pop(key, None)

    workspace.after_push = after_push
    github.after_call = after_read
    if crash:
        with pytest.raises(InjectedCrash):
            await execute(ctx)
    assert await execute(ctx) == "waiting"
    assert len(workspace.pushes) == 2  # initial checkpoint + exactly one publication
    assert len(workspace.commits) == 1 and len(harness.turns) == 1
    candidate = workspace.pushes[-1]
    assert await workspace.head_sha() == candidate  # never adopt competing work
    elapsed = (clock.now() - started).total_seconds()
    if mode == "lag":
        assert not markers(graph_case, "ask")
        assert markers(graph_case, "publish")[-1].phase == "complete"
        assert 3 <= elapsed <= 10
        assert await execute(ctx) == "waiting"
        assert len(workspace.pushes) == 2 and len(harness.turns) == 1
    else:
        assert markers(graph_case, "ask")[-1].code == "head_moved"
        assert markers(graph_case, "publish")[-1].phase == "committed"
        assert not [m for m in markers(graph_case, "push") if m.source != "initial"]
        assert elapsed == (1 if mode == "foreign" else 10)
        if mode == "foreign":
            assert foreign != candidate
            assert await checked(graph_case.origin.bare, "rev-parse", branch) == foreign
