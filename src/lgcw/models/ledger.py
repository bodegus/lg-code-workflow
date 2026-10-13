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
    where: Literal["issue", "pr", "thread"]
    marker: Marker


class PrLedger(Strict):
    """Workflow facts; deterministic methods and counters are added in T3."""

    entries: tuple[LedgerEntry, ...]


class Command(Strict):
    """An authorized owner command without a workflow marker."""

    verb: Literal["answer", "retry", "abort"]
    text: str
    comment_id: int
    author: str
