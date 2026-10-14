"""Versioned durable marker union and ledger boundary records."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from lgcw.models.base import Step, Strict
from lgcw.models.ci import CiAction, CiClass, CiStatus
from lgcw.models.feedback import Feedback
from lgcw.models.handoff import BuildHandoff
from lgcw.models.harness import Role, Usage
from lgcw.models.issue import IssueSnapshot
from lgcw.models.review import GatedFinding, Lens, ReviewLevel


class Command(Strict):
    """An authorized owner command without a workflow marker."""

    verb: Literal["answer", "retry", "abort"]
    text: str
    comment_id: int
    author: str


class IntakeMarker(Strict):
    """Original issue snapshot and accepted criteria before any clone or agent dispatch."""

    kind: Literal["intake"] = "intake"
    snapshot: IssueSnapshot
    criteria: tuple[str, ...]
    command_id: int | None


class BootstrapMarker(Strict):
    """Initial branch operation journal, completed after observed PR effects."""

    kind: Literal["bootstrap"] = "bootstrap"
    operation_id: str
    branch: str
    base_sha: str
    phase: Literal["intent", "complete"]
    head_sha: str | None
    pr_number: int | None = None


class SetupMarker(Strict):
    """Setup intent or measured result; an unknown result never authorizes replay."""

    kind: Literal["setup"] = "setup"
    operation_id: str
    phase: Literal["intent", "complete"]
    code: int | None
    tail: str | None
    fingerprint: str | None


class CommandDoneMarker(Strict):
    """An acknowledged command's continuation completed its durable step."""

    kind: Literal["command_done"] = "command_done"
    command_id: int


class RunMarker(Strict):
    """Issue pickup and draft-PR identity."""

    kind: Literal["run"] = "run"
    issue: str
    branch: str
    base_sha: str
    flow_version: Literal[1] = 1
    snapshot: IssueSnapshot | None = None
    criteria: tuple[str, ...] = ()
    initial_sha: str | None = None
    operation_id: str | None = None
    owner_answer: str | None = None
    body_operation_id: str | None = None
    body_head_sha: str | None = None
    body_step: Step | None = None

    @model_validator(mode="after")
    def coherent_body_receipt(self) -> Self:
        """An atomic body effect names its operation, exact head and code step together."""
        values = (self.body_operation_id, self.body_head_sha, self.body_step)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("incomplete PR body effect receipt")
        return self


class SessionMarker(Strict):
    """A persisted builder thread and its start reason."""

    kind: Literal["session"] = "session"
    role: Role
    session_id: str
    reason: Literal["initial", "fresh_restart"]
    cause: str | None = None


type BuildSource = Literal["build", "gate_fix", "ci_fix", "review_fix"]


class BuildMarker(Strict):
    """Write-ahead paid dispatch and its recoverable validated handoff/error receipt."""

    kind: Literal["build"] = "build"
    operation_id: str
    parent_sha: str
    session_id: str
    source: BuildSource
    publish_source: BuildSource | None = None
    pending_feedback: Feedback | None = None
    phase: Literal["intent", "complete"]
    command_id: int | None
    handoff: BuildHandoff | None
    usage: Usage | None
    tree_fingerprint: str | None
    feedback: Feedback | None
    error: str | None

    @model_validator(mode="after")
    def coherent_phase(self) -> Self:
        """Admit only empty intents or complete handoff/error receipts."""
        if self.phase == "intent" and any(
            value is not None
            for value in (
                self.handoff,
                self.usage,
                self.tree_fingerprint,
                self.feedback,
                self.error,
            )
        ):
            raise ValueError("build intent cannot claim completion")
        if self.phase == "complete" and (self.handoff is None) == (self.error is None):
            raise ValueError("build completion needs exactly a handoff or error")
        if self.handoff is not None and (self.usage is None or self.tree_fingerprint is None):
            raise ValueError("validated handoff needs measured usage and content fingerprint")
        return self


class GateMarker(Strict):
    """A journaled gate command and its content-bound measured verdict."""

    kind: Literal["gate"] = "gate"
    operation_id: str
    build_id: str
    parent_sha: str
    phase: Literal["intent", "complete"]
    code: int | None
    fingerprint: str | None
    tree_fingerprint: str | None
    feedback: Feedback | None

    @model_validator(mode="after")
    def coherent_phase(self) -> Self:
        """Keep unknown command results distinguishable from success."""
        if self.phase == "intent" and any(
            value is not None
            for value in (self.code, self.fingerprint, self.tree_fingerprint, self.feedback)
        ):
            raise ValueError("gate intent cannot claim a result")
        if self.phase == "complete" and (self.code is None or self.tree_fingerprint is None):
            raise ValueError("gate completion needs code and actual tree fingerprint")
        if self.phase == "complete" and self.code != 0 and self.feedback is None:
            raise ValueError("failed gate completion needs actionable feedback")
        if self.feedback is not None and self.fingerprint != self.feedback.fingerprint:
            raise ValueError("gate fingerprint differs from its feedback")
        return self


class PublishMarker(Strict):
    """Commit/push operation identity closes commit-before-receipt and push-before-marker gaps."""

    kind: Literal["publish"] = "publish"
    operation_id: str
    build_id: str
    parent_sha: str
    head_sha: str | None
    phase: Literal["intent", "committed", "complete", "reset_intent", "abandoned"]
    reset_to: str | None = None
    reset_command_id: int | None = None
    reset_tree_fingerprint: str | None = None
    source: BuildSource
    round: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent_phase(self) -> Self:
        """A commit receipt always names its exact proposed head."""
        if (self.phase == "intent") != (self.head_sha is None):
            raise ValueError("publish phase disagrees with committed head")
        reset = (self.reset_to, self.reset_command_id, self.reset_tree_fingerprint)
        if any(value is not None for value in reset) and any(value is None for value in reset):
            raise ValueError("restore receipt needs target, owner command and observed content")
        if self.phase in {"reset_intent", "abandoned"} and self.reset_to is None:
            raise ValueError("restore phase needs an exact authorized target")
        return self


class FeedbackMarker(Strict):
    """Durable code feedback and exact open findings for CI/review fix recovery."""

    kind: Literal["feedback"] = "feedback"
    head_sha: str
    feedback: Feedback
    findings: tuple[GatedFinding, ...] = ()


class PushMarker(Strict):
    """A workflow-owned or explicitly adopted branch head."""

    kind: Literal["push"] = "push"
    head_sha: str
    source: Literal["initial", "build", "gate_fix", "ci_fix", "review_fix", "human"]
    round: int = Field(ge=0)


class CiMarker(Strict):
    """A CI verdict and its deterministic action."""

    kind: Literal["ci"] = "ci"
    head_sha: str
    status: CiStatus
    klass: CiClass | None
    action: CiAction
    fingerprint: str | None


class ReviewMarker(Strict):
    """A completed review round, including skipped review at level none."""

    kind: Literal["review"] = "review"
    head_sha: str
    level: ReviewLevel
    round: int = Field(ge=0)
    lenses: tuple[Lens, ...]
    blocking: int = Field(ge=0)
    nonblocking: int = Field(ge=0)
    review_id: int | None


class FindingMarker(Strict):
    """Stable finding identity attached to a review thread."""

    kind: Literal["finding"] = "finding"
    id: str
    priority: int = Field(ge=0, le=3)
    lens: Lens
    head_sha: str


class AskMarker(Strict):
    """A question and its resume destination."""

    kind: Literal["ask"] = "ask"
    seq: int = Field(ge=1)
    step: Step
    code: str
    supersedes: tuple[int, ...] = ()
    protected_paths: tuple[str, ...] = ()
    tree_fingerprint: str | None = None


class AckMarker(Strict):
    """An owner command applied exactly once."""

    kind: Literal["ack"] = "ack"
    seq: int = Field(ge=1)
    command_id: int
    verb: Literal["answer", "retry", "abort"]
    step: Step | None = None
    command_snapshot: Command | None = None
    adopt: PushMarker | None = None

    @model_validator(mode="after")
    def consistent_command(self) -> Self:
        """Reject a snapshot differing from the acknowledged command identity."""
        if self.command_snapshot is not None and (
            self.command_snapshot.comment_id != self.command_id
            or self.command_snapshot.verb != self.verb
        ):
            raise ValueError("acknowledgement command snapshot mismatch")
        return self


class ReadyMarker(Strict):
    """An exact head has passed the merge-ready gate."""

    kind: Literal["ready"] = "ready"
    head_sha: str


class BlockedMarker(Strict):
    """A terminal stop reason."""

    kind: Literal["blocked"] = "blocked"
    reason: str


type Marker = Annotated[
    RunMarker
    | SessionMarker
    | PushMarker
    | CiMarker
    | ReviewMarker
    | FindingMarker
    | AskMarker
    | AckMarker
    | ReadyMarker
    | BlockedMarker
    | IntakeMarker
    | BootstrapMarker
    | SetupMarker
    | CommandDoneMarker
    | BuildMarker
    | GateMarker
    | PublishMarker
    | FeedbackMarker,
    Field(discriminator="kind"),
]


class LedgerEntry(Strict):
    """A validated marker with its authoritative comment location."""

    comment_id: int
    created_at: datetime
    where: Literal["issue", "pr", "thread", "review", "pr_body"]
    marker: Marker


class LedgerCounts(Strict):
    """Derived activity counts; no counter is persisted separately from PR facts."""

    gate_fix_rounds: int = Field(default=0, ge=0)
    ci_fix_rounds: int = Field(default=0, ge=0)
    review_fix_rounds: int = Field(default=0, ge=0)
    reruns_by_head: dict[str, int] = Field(default_factory=dict)
    reruns_total: int = Field(default=0, ge=0)
    review_rounds: int = Field(default=0, ge=0)
    fresh_restarts: int = Field(default=0, ge=0)
    retry_grants: dict[Step, dict[str, int]] = Field(default_factory=dict)


class PrLedger(Strict):
    """Workflow facts and pure lookups over the reconstructed event order."""

    entries: tuple[LedgerEntry, ...]

    def latest(self, kind: str) -> LedgerEntry | None:
        """Return the latest fact of the requested marker kind."""
        return next((entry for entry in reversed(self.entries) if entry.marker.kind == kind), None)

    def of_kind(self, kind: str) -> list[LedgerEntry]:
        """Return facts of the requested marker kind in ledger order."""
        return [entry for entry in self.entries if entry.marker.kind == kind]

    def pending_ask(self) -> LedgerEntry | None:
        """Find the latest question without a later acknowledgement of its sequence."""
        acknowledged: set[int] = set()
        for entry in reversed(self.entries):
            marker = entry.marker
            if isinstance(marker, AckMarker):
                acknowledged.add(marker.seq)
            elif isinstance(marker, AskMarker) and marker.seq not in acknowledged:
                acknowledged.update(marker.supersedes)
                return entry
            elif isinstance(marker, AskMarker):
                acknowledged.update(marker.supersedes)
        return None

    def last_push(self) -> PushMarker | None:
        """Return the most recently published or explicitly adopted head."""
        entry = self.latest("push")
        return entry.marker if entry is not None and isinstance(entry.marker, PushMarker) else None

    def ci_for(self, head_sha: str) -> CiMarker | None:
        """Return the latest CI decision for an exact head."""
        return next(
            (
                entry.marker
                for entry in reversed(self.entries)
                if isinstance(entry.marker, CiMarker) and entry.marker.head_sha == head_sha
            ),
            None,
        )

    def reviews_for(self, head_sha: str) -> list[ReviewMarker]:
        """Return all review rounds for an exact head."""
        return [
            entry.marker
            for entry in self.entries
            if isinstance(entry.marker, ReviewMarker) and entry.marker.head_sha == head_sha
        ]

    def counts(self) -> LedgerCounts:
        """Recompute all activity counts from markers, without mutating the ledger."""
        gate_fixes = ci_fixes = review_fixes = review_rounds = fresh_restarts = 0
        reruns_by_head: dict[str, int] = {}
        questions: dict[int, AskMarker] = {}
        granted_commands: set[int] = set()
        granted_questions: set[int] = set()
        grants: dict[Step, dict[str, int]] = {}
        for entry in self.entries:
            marker = entry.marker
            if isinstance(marker, AskMarker):
                questions[marker.seq] = marker
            elif (
                isinstance(marker, AckMarker)
                and marker.verb == "retry"
                and marker.command_id not in granted_commands
                and marker.seq not in granted_questions
                and marker.seq in questions
            ):
                question = questions[marker.seq]
                codes = grants.setdefault(question.step, {})
                codes[question.code] = codes.get(question.code, 0) + 1
                granted_commands.add(marker.command_id)
                granted_questions.add(marker.seq)
            elif isinstance(marker, PushMarker):
                gate_fixes += marker.source == "gate_fix"
                ci_fixes += marker.source == "ci_fix"
                review_fixes += marker.source == "review_fix"
            elif isinstance(marker, CiMarker) and marker.action == "rerun":
                reruns_by_head[marker.head_sha] = reruns_by_head.get(marker.head_sha, 0) + 1
            elif isinstance(marker, ReviewMarker):
                review_rounds += 1
            elif isinstance(marker, SessionMarker) and marker.reason == "fresh_restart":
                fresh_restarts += 1
        unusable_attempts = {
            entry.marker.operation_id
            for entry in self.entries
            if isinstance(entry.marker, BuildMarker)
            and entry.marker.phase == "complete"
            and entry.marker.error
            in {"HarnessSessionLostError", "HarnessAuthError", "HarnessQuotaError"}
        }
        gate_attempts = {
            entry.marker.operation_id
            for entry in self.entries
            if isinstance(entry.marker, BuildMarker)
            and entry.marker.phase == "intent"
            and entry.marker.source == "gate_fix"
            and entry.marker.operation_id not in unusable_attempts
        }
        return LedgerCounts(
            gate_fix_rounds=max(gate_fixes, len(gate_attempts)),
            ci_fix_rounds=ci_fixes,
            review_fix_rounds=review_fixes,
            reruns_by_head=reruns_by_head,
            reruns_total=sum(reruns_by_head.values()),
            review_rounds=review_rounds,
            fresh_restarts=fresh_restarts,
            retry_grants=grants,
        )
