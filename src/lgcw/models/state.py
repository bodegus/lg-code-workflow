"""Mutable graph state with counters derived from the durable ledger."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from lgcw.models.base import Step as Step
from lgcw.models.base import Strict
from lgcw.models.ci import CiDecision
from lgcw.models.feedback import Feedback as Feedback
from lgcw.models.github import PrSnapshot, ReviewThread
from lgcw.models.handoff import BuildHandoff
from lgcw.models.harness import SessionRef
from lgcw.models.issue import IntakeResult, IssueRef, IssueSnapshot
from lgcw.models.ledger import Command, PrLedger
from lgcw.models.review import GateResult, LevelDecision

type RunOutcome = Literal["merge_ready", "waiting", "blocked", "closed", "error"]


class PendingAsk(Strict):
    """A question to publish with a typed continuation destination."""

    question: str
    return_to: Step
    code: str
    protected_paths: tuple[str, ...] = ()
    tree_fingerprint: str | None = None


class RunState(Strict):
    """One invocation's state; durable progress is reconstructed from GitHub."""

    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)

    issue_ref: IssueRef
    issue: IssueSnapshot | None = None
    intake: IntakeResult | None = None
    branch: str | None = None
    base_sha: str | None = None
    pr: PrSnapshot | None = None
    ledger: PrLedger = Field(default_factory=lambda: PrLedger(entries=()))
    threads: tuple[ReviewThread, ...] = ()
    builder_session: SessionRef | None = None
    handoff: BuildHandoff | None = None
    feedback: Feedback | None = None
    ci: CiDecision | None = None
    level: LevelDecision | None = None
    gated: GateResult | None = None
    last_reviewed_sha: str | None = None
    ask: PendingAsk | None = None
    owner_answer: str | None = None
    owner_command: Command | None = None
    next_step: Step = "reconcile"
    outcome: RunOutcome | None = None
