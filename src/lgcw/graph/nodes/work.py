"""Shared code-only observations for content-bound build and publication journals."""

from __future__ import annotations

from typing import Any

from lgcw.git.port import WorkspaceInfo
from lgcw.graph.claims import ClaimsResult, check_claims
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import finish_command, observe, post_once, sanitized
from lgcw.ledger.commands import owner_commands
from lgcw.models.approval import ApprovalRevocation, ProtectedApproval
from lgcw.models.handoff import BuildHandoff
from lgcw.models.ledger import AckMarker, AskMarker, BuildMarker, GateMarker, PublishMarker
from lgcw.models.state import PendingAsk, RunState


async def load_work(state: RunState, ctx: RunContext) -> tuple[RunState, WorkspaceInfo | None]:
    """Refresh the PR ledger and prepare its owned workspace without replacing local edits."""
    if state.pr is None or state.branch is None or state.issue is None or state.intake is None:
        raise ValueError("build requires a journaled PR and frozen intake")
    pr = await ctx.github.get_pr(ctx.issue_ref.repo, state.pr.number)
    obs = await observe(ctx, pr)
    current = state.model_copy(update={"pr": pr, "ledger": obs.ledger, "threads": obs.threads})
    if pr.state != "OPEN":
        return current, None
    info = await ctx.workspace.prepare(ctx.repo, ctx.issue_ref, state.branch)
    return current, info


def latest_build(state: RunState, parent: str | None = None) -> BuildMarker | None:
    """Return the latest journal phase, optionally for the current published parent."""
    return next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, BuildMarker)
            and (parent is None or entry.marker.parent_sha == parent)
        ),
        None,
    )


def latest_gate(state: RunState, build_id: str) -> GateMarker | None:
    """Return the last observed gate phase for an exact build operation."""
    return next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, GateMarker) and entry.marker.build_id == build_id
        ),
        None,
    )


def latest_publish(state: RunState, build_id: str) -> PublishMarker | None:
    """Return the last observed publish phase for an exact build operation."""
    return next(
        (
            entry.marker
            for entry in reversed(state.ledger.entries)
            if isinstance(entry.marker, PublishMarker) and entry.marker.build_id == build_id
        ),
        None,
    )


async def current_parent(state: RunState, ctx: RunContext) -> str | None:
    """Require the last owned push to match both live GitHub branch and PR heads."""
    push = state.ledger.last_push()
    if state.pr is None or push is None or state.pr.state != "OPEN":
        return None
    remote = await ctx.github.branch_head(ctx.issue_ref.repo, state.pr.head_ref)
    return push.head_sha if state.pr.head_sha == remote == push.head_sha else None


async def check_work_claims(
    state: RunState, ctx: RunContext, handoff: BuildHandoff, parent: str
) -> ClaimsResult:
    """Check actual paths and content against the issue or a question-bound owner approval."""
    if state.issue is None:
        raise ValueError("claims require frozen issue")
    approval: ProtectedApproval | None = None
    approved_ack: AckMarker | None = None
    observations = await observe(ctx, state.pr)
    questions = {
        entry.marker.seq: entry.marker
        for entry in observations.ledger.entries
        if isinstance(entry.marker, AskMarker)
    }
    latest = next(
        (
            entry.marker
            for entry in reversed(observations.ledger.entries)
            if isinstance(entry.marker, AckMarker)
            and entry.marker.seq is not None
            and entry.marker.seq in questions
            and questions[entry.marker.seq].code == "protected_path"
        ),
        None,
    )
    if latest is not None and latest.seq is not None:
        question = questions[latest.seq]
        if (
            latest.verb == "answer"
            and latest.command_snapshot is not None
            and latest.command_snapshot.text.strip() == "approve"
            and question.protected_paths
            and question.tree_fingerprint is not None
            and latest.step == question.step
        ):
            approval = ProtectedApproval(
                paths=question.protected_paths, tree_fingerprint=question.tree_fingerprint
            )
            approved_ack = latest
    revocation = None
    if approved_ack is not None:
        later = owner_commands(
            observations.comments, ctx.repo.allowed_authors, approved_ack.command_id
        )
        if later:
            command = next((command for command in later if command.verb == "abort"), later[-1])
            revocation = ApprovalRevocation(seq=approved_ack.seq, command=sanitized(command))
            approval = None
    result = check_claims(
        handoff,
        await ctx.workspace.changed_paths(parent),
        ctx.repo,
        state.issue.body,
        tree_fingerprint=await ctx.workspace.worktree_fingerprint(parent),
        approval=approval,
    )
    return result.model_copy(update={"revocation": revocation})


async def claims_interruption(
    result: ClaimsResult, state: RunState, ctx: RunContext
) -> dict[str, Any] | None:
    """Acknowledge revocation before asking again or making an abort terminal."""
    revoked = result.revocation
    if revoked is None:
        return None
    if state.pr is None:
        raise ValueError("protected approval requires a PR")
    command = revoked.command
    await post_once(
        ctx,
        state.pr.number,
        AckMarker(
            seq=revoked.seq,
            command_id=command.comment_id,
            verb=command.verb,
            step="blocked" if command.verb == "abort" else "build",
            command_snapshot=command,
            adopt=None,
        ),
        "Later owner command revoked protected-path approval.",
    )
    await finish_command(ctx, state, state.pr.number)
    continuation = state.model_copy(update={"owner_command": command})
    if command.verb == "abort":
        return {"owner_command": command, "next_step": "blocked", "ask": None}
    await finish_command(ctx, continuation, state.pr.number)
    question = result.ask or PendingAsk(
        code="protected_path",
        return_to="build",
        question="Owner revoked protected-path approval; inspect the proposal and answer again.",
    )
    return {"owner_command": None, "ask": question, "next_step": "ask"}
