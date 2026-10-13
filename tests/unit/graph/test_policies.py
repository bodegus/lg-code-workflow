"""SDK status/cause classification and configured runtime timeout behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from githubkit.exception import RequestError, RequestFailed, RequestTimeout
from githubkit.response import Response
from langgraph.runtime import Runtime

from lgcw.graph.context import RunContext
from lgcw.graph.policies import default_error_handler, is_transient
from lgcw.graph.runner import run_issue
from lgcw.models.state import RunState
from tests.unit.graph.cases import context
from tests.unit.graph.test_wiring import nodes


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,expected",
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (429, False),
        (500, True),
        (502, True),
        (503, True),
    ],
)
def test_sdk_status_retry_whitelist(status: int, expected: bool) -> None:
    request = httpx.Request("GET", "https://example.test/fixture")
    response = Response(httpx.Response(status, request=request), dict)
    assert is_transient(RequestFailed(response)) == expected


@pytest.mark.unit
def test_wrapped_transport_and_programming_errors_are_distinct() -> None:
    assert is_transient(RequestTimeout(httpx.ReadTimeout("synthetic timeout")))
    assert is_transient(RequestError(ConnectionError("synthetic connection")))
    assert not is_transient(RequestError(ValueError("bad payload")))
    wrapped = RuntimeError("transport wrapper")
    wrapped.__cause__ = ConnectionError("connection lost")
    assert is_transient(RequestError(wrapped))
    cycle = RuntimeError("cycle")
    cycle.__cause__ = cycle
    assert not is_transient(RequestError(cycle))


@pytest.mark.unit
async def test_error_handler_without_injection_fails_closed(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    with pytest.raises(RuntimeError, match="context was not injected"):
        await default_error_handler(RunState(issue_ref=ctx.issue_ref), runtime=Runtime(context=ctx))


@pytest.mark.unit
async def test_configured_agent_timeout_routes_to_ask_once(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    limits = ctx.config.limits.model_copy(
        update={"build_run_timeout_s": 1, "build_idle_timeout_s": 1}
    )
    ctx = ctx.model_copy(update={"config": ctx.config.model_copy(update={"limits": limits})})
    calls: list[str] = []

    async def reconcile(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        return {"next_step": "build"}

    async def slow(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        calls.append("build")
        await asyncio.sleep(5)
        return {"next_step": "end", "outcome": "merge_ready"}

    async def ask(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        assert state.ask and "NodeTimeoutError" in state.ask.question
        return {"next_step": "end", "outcome": "waiting"}

    mapping = nodes()
    mapping.update({"reconcile": reconcile, "build": slow, "ask": ask})
    assert await run_issue(ctx, nodes=mapping) == "waiting"
    assert calls == ["build"]


@pytest.mark.unit
async def test_runner_cancellation_keeps_incomplete_evidence(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    entered = asyncio.Event()

    async def hold(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        entered.set()
        await asyncio.Event().wait()
        return {}

    mapping = nodes()
    mapping["reconcile"] = hold
    task = asyncio.create_task(run_issue(ctx, nodes=mapping))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    report = (ctx.log.run_dir / "report.md").read_text()
    assert "Outcome: incomplete" in report
    assert '"kind":"run_interrupted"' in (ctx.log.run_dir / "events.jsonl").read_text()


@pytest.mark.unit
async def test_runner_refuses_implicit_success(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def no_outcome(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        return {"next_step": "end"}

    mapping = nodes()
    mapping["reconcile"] = no_outcome
    assert await run_issue(ctx, nodes=mapping) == "error"
