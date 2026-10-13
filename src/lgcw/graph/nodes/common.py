"""Code-only observation, marker and label helpers shared by real graph nodes."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from lgcw.github.render import render_event, render_question
from lgcw.graph.context import RunContext
from lgcw.ledger.ledger import build_ledger
from lgcw.ledger.markers import parse_markers
from lgcw.models.base import Step, Strict
from lgcw.models.github import IssueComment, PrSnapshot, ReviewThread
from lgcw.models.ledger import AckMarker, CommandDoneMarker, Marker, PrLedger
from lgcw.models.state import PendingAsk, RunState
from lgcw.runlog import redact, redact_data


class Observations(Strict):
    """Authenticated facts plus raw comments for separately authorized command parsing."""

    ledger: PrLedger
    threads: tuple[ReviewThread, ...]
    comments: tuple[IssueComment, ...]


def sanitized[M: BaseModel](model: M) -> M:
    """Redact structured strings before serializing a canonical workflow record."""
    return type(model).model_validate(redact_data(model.model_dump(mode="json")))


def attention(code: str, question: str, step: Step) -> dict[str, object]:
    """Return a typed owner question destination, never an agent routing decision."""
    return {"ask": PendingAsk(code=code, question=question, return_to=step), "next_step": "ask"}


async def observe(ctx: RunContext, pr: PrSnapshot | None) -> Observations:
    """Read all durable record surfaces before choosing or repeating an effect."""
    issue_comments = await ctx.github.list_issue_comments(ctx.issue_ref.repo, ctx.issue_ref.number)
    if pr is None:
        return Observations(
            ledger=build_ledger(issue_comments, [], [], ctx.workflow_login),
            threads=(),
            comments=tuple(issue_comments),
        )
    comments, threads, reviews, document = await asyncio.gather(
        ctx.github.list_issue_comments(ctx.issue_ref.repo, pr.number),
        ctx.github.list_review_threads(ctx.issue_ref.repo, pr.number),
        ctx.github.list_pr_reviews(ctx.issue_ref.repo, pr.number),
        ctx.github.get_pr_document(ctx.issue_ref.repo, pr.number),
    )
    ledger = build_ledger(
        issue_comments, comments, threads, ctx.workflow_login, reviews=reviews, pr_document=document
    )
    return Observations(
        ledger=ledger, threads=tuple(threads), comments=tuple([*issue_comments, *comments])
    )


async def post_once(
    ctx: RunContext, number: int, marker: Marker, text: str, *, question: bool = False
) -> IssueComment:
    """Recover or publish one marker in its specific conversation, then retain its receipt."""
    from lgcw.models.ledger import AskMarker

    clean = sanitized(marker)
    if question and isinstance(clean, AskMarker):
        body = render_question(redact(text), clean)
    else:
        body = render_event(redact(text), clean)
    if len(body) > 60000:
        raise ValueError("canonical workflow record exceeds the GitHub comment bound")
    comments = await ctx.github.list_issue_comments(ctx.issue_ref.repo, number)
    existing = next(
        (
            comment
            for comment in comments
            if comment.author == ctx.workflow_login and clean in parse_markers(comment.body)
        ),
        None,
    )
    comment = (
        existing
        if existing is not None
        else await ctx.github.create_issue_comment(ctx.issue_ref.repo, number, body)
    )
    ctx.log.posted(clean.kind, comment.body, {"comment_id": comment.id, "number": number})
    return comment


async def labels(
    ctx: RunContext, number: int, add: tuple[str, ...], remove: tuple[str, ...]
) -> None:
    """Repair only missing/extra workflow labels, using observed state as the receipt."""
    if number == ctx.issue_ref.number:
        snapshot = await ctx.github.get_issue(ctx.issue_ref)
        present = set(snapshot.labels)
    else:
        pr = await ctx.github.get_pr(ctx.issue_ref.repo, number)
        present = set(pr.labels)
    missing = tuple(label for label in add if label not in present)
    obsolete = tuple(label for label in remove if label in present)
    if missing or obsolete:
        await ctx.github.set_labels(ctx.issue_ref.repo, number, missing, obsolete)


async def finish_command(ctx: RunContext, state: RunState, number: int) -> None:
    """Mark a restored command complete only after its target's durable effects exist."""
    if state.owner_command is not None:
        observations = await observe(ctx, state.pr)
        ack = next(
            (
                entry
                for entry in reversed(observations.ledger.of_kind("ack"))
                if isinstance(entry.marker, AckMarker)
                and entry.marker.command_id == state.owner_command.comment_id
            ),
            None,
        )
        if ack is not None:
            number = state.pr.number if ack.where == "pr" and state.pr else ctx.issue_ref.number
        await post_once(
            ctx,
            number,
            CommandDoneMarker(command_id=state.owner_command.comment_id),
            "Owner command continuation completed.",
        )
