"""Reconstruct each invocation from authenticated service facts and frozen command receipts."""

from __future__ import annotations

from typing import Any

from langgraph.runtime import Runtime

from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, labels, observe, post_once, sanitized
from lgcw.graph.reconcile import ReconcileView, next_step
from lgcw.ledger.commands import owner_commands
from lgcw.models.issue import IntakeResult
from lgcw.models.ledger import (
    AckMarker,
    AskMarker,
    BootstrapMarker,
    CommandDoneMarker,
    IntakeMarker,
    RunMarker,
)
from lgcw.models.state import RunState


async def reconcile(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Acknowledge authorized commands before routing and recover interrupted continuations."""
    ctx = runtime.context
    branch = f"lgcw/issue-{ctx.issue_ref.number}"
    pr = await ctx.github.find_open_pr(ctx.issue_ref.repo, branch)
    obs = await observe(ctx, pr)
    if pr is None:
        linked = obs.ledger.latest("bootstrap")
        if linked and isinstance(linked.marker, BootstrapMarker) and linked.marker.pr_number:
            pr = await ctx.github.get_pr(ctx.issue_ref.repo, linked.marker.pr_number)
            obs = await observe(ctx, pr)
    current = await ctx.github.get_issue(ctx.issue_ref)
    run_entry, intake_entry = obs.ledger.latest("run"), obs.ledger.latest("intake")
    run = run_entry.marker if run_entry and isinstance(run_entry.marker, RunMarker) else None
    original = run.snapshot if run else None
    criteria = run.criteria if run else ()
    if original is None and intake_entry and isinstance(intake_entry.marker, IntakeMarker):
        original, criteria = intake_entry.marker.snapshot, intake_entry.marker.criteria
    acks = [entry for entry in obs.ledger.of_kind("ack") if isinstance(entry.marker, AckMarker)]
    answer = run.owner_answer if run else None
    if answer is None:
        answer = next(
            (
                entry.marker.command_snapshot.text
                for entry in reversed(acks)
                if isinstance(entry.marker, AckMarker)
                and entry.marker.verb == "answer"
                and entry.marker.command_snapshot is not None
            ),
            None,
        )
    fields: dict[str, Any] = dict(
        pr=pr,
        ledger=obs.ledger,
        threads=obs.threads,
        issue=original or sanitized(current),
        branch=branch,
        base_sha=run.base_sha if run else None,
        intake=IntakeResult(
            status="ok" if criteria else "incomplete",
            acceptance_criteria=criteria,
            reason=None if criteria else "missing criteria",
        ),
        owner_answer=answer,
    )
    commands = owner_commands(obs.comments, ctx.repo.allowed_authors, after_comment_id=0)
    outcome = next_step(
        ReconcileView(
            issue=current, pr=pr, ledger=obs.ledger, threads=obs.threads, commands=tuple(commands)
        )
    )
    # Terminal facts win even over a command that was interrupted after its blocking write.
    number = pr.number if pr else ctx.issue_ref.number
    if outcome.reason in {"closed", "blocked"}:
        if outcome.reason == "blocked":
            await labels(
                ctx, number, ("lgcw:blocked",), ("lgcw:active", "lgcw:waiting", "lgcw:merge-ready")
            )
        return fields | {"next_step": "end", "outcome": outcome.reason}
    ack: AckMarker | None
    if outcome.command is not None:
        pending = obs.ledger.pending_ask()
        if pending is None or not isinstance(pending.marker, AskMarker):
            raise ValueError("command has no authoritative question")
        command = sanitized(outcome.command)
        ack = AckMarker(
            seq=pending.marker.seq,
            command_id=command.comment_id,
            verb=command.verb,
            step=outcome.step,
            command_snapshot=command,
            adopt=outcome.adopt,
        )
        target = pr.number if pending.where == "pr" and pr else ctx.issue_ref.number
        await post_once(ctx, target, ack, "Owner command acknowledged.")
    else:
        done = {
            entry.marker.command_id
            for entry in obs.ledger.of_kind("command_done")
            if isinstance(entry.marker, CommandDoneMarker)
        }
        latest = acks[-1].marker if acks and obs.ledger.pending_ask() is None else None
        ack = latest if isinstance(latest, AckMarker) and latest.command_id not in done else None
    if ack is not None:
        if ack.command_snapshot is None or ack.step is None:
            return fields | attention(
                "command_evidence_missing",
                "Acknowledged command lacks its frozen continuation.",
                "reconcile",
            )
        command = ack.command_snapshot
        fields.update(owner_command=command)
        if command.verb == "answer":
            fields["owner_answer"] = command.text
        if ack.adopt is not None:
            if pr is None or pr.head_sha != ack.adopt.head_sha:
                return fields | attention(
                    "head_moved",
                    "Head changed after acknowledgement. Retry to adopt the new head.",
                    "reconcile",
                )
            await ctx.workspace.prepare(ctx.repo, ctx.issue_ref, branch)
            adopted = await ctx.workspace.adopt_remote_head(branch)
            if adopted != ack.adopt.head_sha:
                return fields | attention(
                    "head_moved", "Head changed while fetching adoption.", "reconcile"
                )
            await post_once(
                ctx, pr.number, ack.adopt, "Owner authorized adoption of this exact head."
            )
            continuation = RunState.model_validate(state.model_dump() | fields)
            await finish_command(ctx, continuation, number)
            fields["owner_command"] = None
        return fields | {"next_step": ack.step}
    if outcome.reason == "waiting":
        await labels(ctx, number, ("lgcw:waiting",), ("lgcw:active", "lgcw:merge-ready"))
        return fields | {"next_step": "end", "outcome": "waiting"}
    if outcome.reason == "merge_ready":
        return fields | {"next_step": "end", "outcome": "merge_ready"}
    # Bootstrap completion may have been interrupted after PR/push receipt publication.
    bootstrap = obs.ledger.latest("bootstrap")
    if (
        pr
        and run
        and run.initial_sha == pr.head_sha
        and bootstrap
        and isinstance(bootstrap.marker, BootstrapMarker)
        and bootstrap.marker.phase == "intent"
    ):
        return fields | {"next_step": "open_pr"}
    return fields | {"next_step": outcome.step, "ask": outcome.ask}
