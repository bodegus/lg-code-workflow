"""One graph invocation with local evidence and caller-owned adapter lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from lgcw.graph.build_graph import NodeFn, build_graph
from lgcw.graph.context import RunContext
from lgcw.graph.policies import recursion_limit
from lgcw.models.base import Step
from lgcw.models.state import RunOutcome, RunState


async def run_issue(ctx: RunContext, *, nodes: Mapping[Step, NodeFn] | None = None) -> RunOutcome:
    """Execute from reconcile, record every update, and return the explicit terminal outcome."""
    state = RunState(issue_ref=ctx.issue_ref)
    ctx.log.event("run_start", issue_ref=f"{ctx.issue_ref.repo}#{ctx.issue_ref.number}")
    try:
        graph = build_graph(nodes, limits=ctx.config.limits)
        async for update in graph.astream(
            state,
            context=ctx,
            stream_mode="updates",
            config={"recursion_limit": recursion_limit(ctx.config.limits)},
        ):
            for name, delta in update.items():
                if delta is None:
                    continue
                state = RunState.model_validate({**state.model_dump(), **delta})
                values = state.model_dump(mode="json")
                ctx.log.event("graph_update", node=name, update={key: values[key] for key in delta})
        if state.outcome is None:
            raise RuntimeError("graph ended without an explicit outcome")
        outcome = state.outcome
    except asyncio.CancelledError:
        ctx.log.event("run_interrupted")
        ctx.log.write_report()
        raise
    except Exception as error:
        ctx.log.event("run_error", error_class=type(error).__name__)
        outcome = "error"
    ctx.log.event("run_end", outcome=outcome)
    ctx.log.write_report()
    return outcome
