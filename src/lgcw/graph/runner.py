"""One graph invocation with local evidence and caller-owned adapter lifetime."""

from __future__ import annotations

import asyncio
import traceback
from collections.abc import Mapping

from langgraph.errors import GraphRecursionError
from langgraph.runtime import Runtime

from lgcw.graph.build_graph import NodeFn, build_graph
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.ask import ask
from lgcw.graph.nodes.common import finish_command
from lgcw.graph.policies import recursion_limit
from lgcw.ledger.markers import fingerprint
from lgcw.models.base import Step
from lgcw.models.state import PendingAsk, RunOutcome, RunState


async def run_issue(ctx: RunContext, *, nodes: Mapping[Step, NodeFn] | None = None) -> RunOutcome:
    """Execute from reconcile, record every update, and return the explicit terminal outcome."""
    state = RunState(issue_ref=ctx.issue_ref)
    ctx.log.event("run_start", issue_ref=f"{ctx.issue_ref.repo}#{ctx.issue_ref.number}")
    try:
        graph = build_graph(nodes, limits=ctx.config.limits)
        seen: set[tuple[str, str]] = set()
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
                progress = (name, fingerprint(state.model_dump_json()))
                if progress in seen and state.outcome is None:
                    raise GraphRecursionError(f"No progress: repeated state at {name}.")
                seen.add(progress)
        if state.outcome is None:
            raise RuntimeError("graph ended without an explicit outcome")
        outcome = state.outcome
    except asyncio.CancelledError:
        ctx.log.event("run_interrupted")
        ctx.log.write_report()
        raise
    except GraphRecursionError as error:
        ctx.log.event("run_error", error_class=type(error).__name__, detail=str(error))
        question = PendingAsk(
            code="node_error",
            return_to="reconcile",
            question="Workflow made no progress or reached its graph limit; "
            "inspect the run evidence, then retry or abort.",
        )
        try:
            recovered = await ask(state.model_copy(update={"ask": question}), Runtime(context=ctx))
            await finish_command(ctx, state, state.pr.number if state.pr else ctx.issue_ref.number)
            state = RunState.model_validate(state.model_dump() | recovered)
            outcome = state.outcome or "error"
        except Exception as recovery_error:
            ctx.log.event("recovery_error", error_class=type(recovery_error).__name__)
            outcome = "error"
    except Exception as error:
        ctx.log.event(
            "run_error",
            error_class=type(error).__name__,
            traceback="".join(traceback.format_exception(error)),
        )
        outcome = "error"
    ctx.log.event("run_end", outcome=outcome)
    ctx.log.write_report()
    return outcome
