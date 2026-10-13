"""Bounded transient retries, explicit agent timeouts and safe error routing."""

from __future__ import annotations

import traceback

from githubkit.exception import RequestError, RequestFailed, RequestTimeout
from langgraph.errors import NodeError
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy, TimeoutPolicy

from lgcw.graph.context import RunContext
from lgcw.models.base import Step
from lgcw.models.config import Limits
from lgcw.models.state import PendingAsk, RunState

_MISSING_ERROR = NodeError(node="", error=RuntimeError("missing handler context"))


def is_transient(error: Exception) -> bool:
    """Retry transport causes and HTTP 5xx, never schema/auth/quota/client-status failures."""
    if isinstance(error, RequestFailed):
        return 500 <= error.response.status_code < 600
    if isinstance(error, RequestTimeout):
        return True
    if isinstance(error, RequestError):
        cause: BaseException | None = error.exc
        seen: set[int] = set()
        while cause is not None and id(cause) not in seen:
            if isinstance(cause, (ConnectionError, TimeoutError)):
                return True
            seen.add(id(cause))
            cause = cause.__cause__
        return False
    return isinstance(error, (ConnectionError, TimeoutError))


def retry_policy(step: Step) -> RetryPolicy:
    """Keep paid agent dispatch single-attempt; retry only guarded code-side effects."""
    return RetryPolicy(
        max_attempts=1 if step in {"build", "review"} else 4,
        initial_interval=2.0,
        retry_on=is_transient,
    )


def agent_timeout(step: Step, limits: Limits) -> TimeoutPolicy | None:
    """Compile the configured role's run/idle bounds with explicit-only heartbeats."""
    if step == "build":
        return TimeoutPolicy(
            run_timeout=limits.build_run_timeout_s,
            idle_timeout=limits.build_idle_timeout_s,
            refresh_on="heartbeat",
        )
    if step == "review":
        return TimeoutPolicy(
            run_timeout=limits.review_run_timeout_s,
            idle_timeout=limits.review_idle_timeout_s,
            refresh_on="heartbeat",
        )
    return None


def recursion_limit(limits: Limits) -> int:
    """Allow declared finite fix loops without relying on LangGraph's default 25 steps."""
    return 32 + 8 * (
        limits.gate_fix_rounds
        + limits.ci_fix_rounds
        + max(limits.review_fix_rounds.values(), default=0)
        + limits.reruns_per_pr
        + 4
    )


async def default_error_handler(
    state: RunState,
    *,
    runtime: Runtime[RunContext],
    error: NodeError = _MISSING_ERROR,
) -> Command[Step]:
    """Ask with a safe node/class diagnosis; failed terminal writers end with error."""
    if not error.node:
        raise RuntimeError("node error context was not injected")
    name = error.node
    classification = type(error.error).__name__
    runtime.context.log.event(
        "node_error",
        node=name,
        error_class=classification,
        traceback="".join(traceback.format_exception(error.error)),
    )
    if name in {"ask", "blocked"}:
        return Command(update={"outcome": "error", "next_step": "end"}, goto="end")
    destination: Step = next(
        (
            step
            for step in (
                "reconcile",
                "intake",
                "open_pr",
                "build",
                "gate",
                "publish",
                "ci_wait",
                "review",
                "merge_ready",
            )
            if step == name
        ),
        "reconcile",
    )
    question = PendingAsk(
        question=f"Step {name} failed with {classification}; inspect the run evidence and retry.",
        return_to=destination,
        code="node_error",
    )
    return Command(update={"ask": question, "next_step": "ask"}, goto="ask")
