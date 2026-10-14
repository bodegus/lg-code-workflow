"""Compiled graph context, routing, error fallback and runner evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langgraph.runtime import Runtime
from pydantic import TypeAdapter

from lgcw.graph.build_graph import STEPS, NodeFn, build_graph
from lgcw.graph.context import RunContext
from lgcw.graph.policies import agent_timeout, is_transient, retry_policy
from lgcw.graph.runner import run_issue
from lgcw.models.base import Step
from lgcw.models.config import Limits
from lgcw.models.state import RunState
from tests.unit.graph.cases import context


async def end(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Finish a synthetic complete-node fixture without live operations."""
    return {"next_step": "end", "outcome": "merge_ready"}


def nodes() -> dict[Step, NodeFn]:
    """Supply every declared node for compiled skeleton contracts."""
    return {step: end for step in STEPS if step != "end"}


@pytest.mark.unit
def test_every_router_target_is_a_node() -> None:
    compiled = build_graph(nodes())
    actual = compiled.get_graph()
    assert set(STEPS) == set(TypeAdapter(Step).json_schema()["enum"])
    assert set(STEPS) <= set(actual.nodes)
    assert {edge.target for edge in actual.edges} <= set(actual.nodes)


@pytest.mark.unit
async def test_runner_uses_context_and_logs_every_update(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def reconcile(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        assert runtime.context is ctx
        return {"next_step": "intake"}

    mapping = nodes()
    mapping["reconcile"] = reconcile
    result = await run_issue(ctx, nodes=mapping)
    assert result == "merge_ready"
    events = (ctx.log.run_dir / "events.jsonl").read_text()
    assert '"kind":"graph_update"' in events and '"kind":"run_end"' in events
    assert (ctx.log.run_dir / "report.md").exists()


@pytest.mark.unit
async def test_default_error_handler_asks_with_node_and_class(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def broken(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        raise ValueError("untrusted private diagnostic")

    async def ask(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        assert (
            state.ask and "reconcile" in state.ask.question and "ValueError" in state.ask.question
        )
        assert "untrusted private diagnostic" not in state.ask.question
        return {"next_step": "end", "outcome": "waiting"}

    mapping = nodes()
    mapping["reconcile"] = broken
    mapping["ask"] = ask
    assert await run_issue(ctx, nodes=mapping) == "waiting"


@pytest.mark.unit
async def test_ask_failure_terminates_without_recursion(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def reconcile(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        return {"next_step": "ask"}

    async def broken(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        raise ValueError("cannot publish question")

    mapping = nodes()
    mapping["reconcile"] = reconcile
    mapping["ask"] = broken
    assert await run_issue(ctx, nodes=mapping) == "error"


@pytest.mark.unit
def test_missing_default_nodes_fail_explicitly() -> None:
    from lgcw.graph.nodes import DEFAULT_NODES

    with pytest.raises(ValueError, match="missing"):
        build_graph({name: node for name, node in DEFAULT_NODES.items() if name != "review"})


@pytest.mark.unit
def test_complete_default_registry_compiles() -> None:
    assert set(STEPS) <= set(build_graph().get_graph().nodes)


@pytest.mark.unit
@pytest.mark.parametrize(
    "error,expected",
    [
        (ConnectionError(), True),
        (TimeoutError(), True),
        (ValueError(), False),
        (PermissionError(), False),
    ],
)
def test_retry_policy_is_transient_only(error: Exception, expected: bool) -> None:
    assert is_transient(error) == expected
    assert retry_policy("intake").max_attempts == 4 and retry_policy("intake").initial_interval == 2
    assert retry_policy("build").max_attempts == 1


@pytest.mark.unit
def test_agent_timeouts_are_explicit_and_configured() -> None:
    build = agent_timeout("build", Limits())
    review = agent_timeout("review", Limits())
    assert build and (build.run_timeout, build.idle_timeout, build.refresh_on) == (
        3600,
        600,
        "heartbeat",
    )
    assert review and (review.run_timeout, review.idle_timeout) == (1200, 300)
    assert agent_timeout("intake", Limits()) is None


@pytest.mark.unit
async def test_missing_next_step_never_repeats_a_paid_node(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    calls = 0

    async def reconcile(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        return {"next_step": "build"}

    async def broken(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    async def ask(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        assert state.ask and state.ask.code == "node_error"
        return {"next_step": "end", "outcome": "waiting"}

    mapping = nodes() | {"reconcile": reconcile, "build": broken, "ask": ask}
    assert await run_issue(ctx, nodes=mapping) == "waiting"
    assert calls == 1


@pytest.mark.unit
async def test_node_error_records_redacted_traceback(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    synthetic = "ghp_" + "A" * 36

    async def broken(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        raise ValueError("diagnostic " + synthetic)

    assert await run_issue(ctx, nodes=nodes() | {"reconcile": broken}) == "merge_ready"
    events = (ctx.log.run_dir / "events.jsonl").read_text()
    assert "Traceback (most recent call last)" in events and "in broken" in events
    assert "ValueError: diagnostic" in events and synthetic not in events


@pytest.mark.unit
async def test_run_error_records_traceback(tmp_path: Path) -> None:
    from lgcw.graph.nodes import DEFAULT_NODES

    ctx = context(tmp_path)
    incomplete: dict[Step, NodeFn] = {
        name: node for name, node in DEFAULT_NODES.items() if name != "review"
    }
    assert await run_issue(ctx, nodes=incomplete) == "error"
    events = (ctx.log.run_dir / "events.jsonl").read_text()
    assert '"kind":"run_error"' in events and "Traceback (most recent call last)" in events
    assert "in build_graph" in events


@pytest.mark.unit
def test_shared_graph_names_are_exported() -> None:
    import lgcw.graph as graph

    for name in (
        "RunContext",
        "ReconcileView",
        "ReconcileOutcome",
        "next_step",
        "build_graph",
        "run_issue",
    ):
        assert getattr(graph, name, None) is not None
