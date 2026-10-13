"""Versioned durable marker union and ledger boundary records."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from lgcw.models.base import Step, Strict
from lgcw.models.ci import CiAction, CiClass, CiStatus
from lgcw.models.harness import Role
from lgcw.models.review import Lens, ReviewLevel


class RunMarker(Strict):
    """Issue pickup and draft-PR identity."""

    kind: Literal["run"] = "run"
    issue: str
    branch: str
    base_sha: str
    flow_version: Literal[1] = 1


class SessionMarker(Strict):
    """A persisted builder thread and its start reason."""

    kind: Literal["session"] = "session"
    role: Role
    session_id: str
    reason: Literal["initial", "fresh_restart"]


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


class AckMarker(Strict):
    """An owner command applied exactly once."""

    kind: Literal["ack"] = "ack"
    seq: int = Field(ge=1)
    command_id: int
    verb: Literal["answer", "retry", "abort"]


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
    | BlockedMarker,
    Field(discriminator="kind"),
]


class LedgerEntry(Strict):
    """A validated marker with its authoritative comment location."""

    comment_id: int
    created_at: datetime
    where: Literal["issue", "pr", "thread", "review"]
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
                return entry
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
        for entry in self.entries:
            marker = entry.marker
            if isinstance(marker, PushMarker):
                gate_fixes += marker.source == "gate_fix"
                ci_fixes += marker.source == "ci_fix"
                review_fixes += marker.source == "review_fix"
            elif isinstance(marker, CiMarker) and marker.action == "rerun":
                reruns_by_head[marker.head_sha] = reruns_by_head.get(marker.head_sha, 0) + 1
            elif isinstance(marker, ReviewMarker):
                review_rounds += 1
            elif isinstance(marker, SessionMarker) and marker.reason == "fresh_restart":
                fresh_restarts += 1
        return LedgerCounts(
            gate_fix_rounds=gate_fixes,
            ci_fix_rounds=ci_fixes,
            review_fix_rounds=review_fixes,
            reruns_by_head=reruns_by_head,
            reruns_total=sum(reruns_by_head.values()),
            review_rounds=review_rounds,
            fresh_restarts=fresh_restarts,
        )


class Command(Strict):
    """An authorized owner command without a workflow marker."""

    verb: Literal["answer", "retry", "abort"]
    text: str
    comment_id: int
    author: str
