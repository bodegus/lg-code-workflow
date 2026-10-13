"""Compile complete node registries with explicit routing and runtime policies."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from lgcw.graph.context import NodeFn as NodeFn
from lgcw.graph.context import RunContext
from lgcw.graph.policies import agent_timeout, default_error_handler, retry_policy
from lgcw.graph.routes import route_after_reconcile
from lgcw.models.base import Step
from lgcw.models.config import Limits
from lgcw.models.state import RunState

STEPS: tuple[Step, ...] = (
    "reconcile",
    "intake",
    "open_pr",
    "build",
    "gate",
    "publish",
    "ci_wait",
    "review",
    "merge_ready",
    "ask",
    "blocked",
    "end",
)
type WorkflowGraph = CompiledStateGraph[RunState, RunContext, RunState, RunState]


class LoggedNode(Protocol):
    """Preserve the keyword runtime parameter in LangGraph's typed registration boundary."""

    def __call__(
        self, state: RunState, *, runtime: Runtime[RunContext]
    ) -> Awaitable[dict[str, Any]]: ...


def _logged(step: Step, node: NodeFn) -> LoggedNode:
    async def invoke(state: RunState, *, runtime: Runtime[RunContext]) -> dict[str, Any]:
        started = runtime.context.clock.now()
        attempt = runtime.execution_info.node_attempt if runtime.execution_info else 1
        runtime.context.log.event("node_start", node=step, attempt=attempt)
        try:
            return await node(state, runtime)
        finally:
            duration = (runtime.context.clock.now() - started).total_seconds()
            runtime.context.log.event("node_end", node=step, attempt=attempt, duration_s=duration)

    return invoke


async def _end(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    return {}


def build_graph(
    nodes: Mapping[Step, NodeFn] | None = None, *, limits: Limits | None = None
) -> WorkflowGraph:
    """Compile a complete workflow, refusing missing nodes instead of successful placeholders."""
    if nodes is None:
        from lgcw.graph.nodes import DEFAULT_NODES

        nodes = DEFAULT_NODES
    required = set(STEPS) - {"end"}
    missing = required - set(nodes)
    if missing or set(nodes) - required:
        raise ValueError(f"missing or unexpected workflow nodes: {sorted(missing)}")
    policy = limits if limits is not None else Limits()
    builder = StateGraph(RunState, context_schema=RunContext)
    builder.set_node_defaults(error_handler=default_error_handler)
    for step in STEPS:
        if step == "end":
            builder.add_node(step, _end)
            continue
        builder.add_node(
            step,
            _logged(step, nodes[step]),
            retry_policy=retry_policy(step),
            timeout=agent_timeout(step, policy),
        )
        builder.add_conditional_edges(
            step, route_after_reconcile, {target: target for target in STEPS}
        )
    builder.add_edge(START, "reconcile")
    builder.add_edge("end", END)
    return builder.compile()
