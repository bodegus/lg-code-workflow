"""Trusted step templates with explicitly fenced external evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from importlib.resources import files
from types import MappingProxyType

from lgcw.harness.skills import skill_path
from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig
from lgcw.models.handoff import BuildHandoff, Decision, FileNote, Risk
from lgcw.models.harness import TurnInput
from lgcw.models.issue import IntakeResult, IssueSnapshot
from lgcw.models.review import GatedFinding, Lens, LevelDecision
from lgcw.models.state import Feedback

_TEMPLATES = MappingProxyType(
    {
        name: files("lgcw.harness").joinpath("templates", f"{name}.md").read_text()
        for name in ("build", "fix", "restart", "review", "verify")
    }
)


class ReviewPacket(Strict):
    """Review context deliberately excluding builder self-grades and test claims."""

    issue_title: str
    criteria: tuple[str, ...]
    base_sha: str
    head_sha: str
    range_from: str
    diffstat: str
    level: LevelDecision
    lens: Lens
    ci_summary: str
    gate_summary: str
    approach: str
    decisions: list[Decision]
    assumptions: list[str]
    not_done: list[str]
    risks: list[Risk]
    files: list[FileNote]
    acceptance_evidence: list[str]
    open_findings: list[GatedFinding]
    do_not_repeat: list[str]


def fence(data: str, label: str) -> str:
    """Fence arbitrary evidence with a delimiter longer than every backtick run.

    Raises:
        ValueError: The label could inject another line or delimiter.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", label):
        raise ValueError("invalid external-data label")
    length = max(3, 1 + max((len(run) for run in re.findall(r"`+", data)), default=0))
    delimiter = "`" * length
    return f"{delimiter}{label}\n{data}\n{delimiter}"


def _turn(
    template: str, skill: str, data: dict[str, object], owner: str | None = None
) -> TurnInput:
    encoded = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)
    text = _TEMPLATES[template].rstrip() + "\n\n" + fence(encoded, "external-json")
    if owner is not None:
        text += "\n\nAuthenticated owner instruction:\n" + owner
    return TurnInput(skill=str(skill_path(skill)), text=text, data=None, data_label=None)


def render_build_turn(
    issue: IssueSnapshot, intake: IntakeResult, repo: RepoConfig, owner_answer: str | None
) -> TurnInput:
    """Render the initial build task from snapshotted issue data and trusted repo policy."""
    return _turn(
        "build",
        "build",
        {
            "issue": issue.model_dump(mode="json"),
            "intake": intake.model_dump(mode="json"),
            "repository_policy": repo.model_dump(mode="json"),
        },
        owner_answer,
    )


def render_fix_turn(
    feedback: Feedback,
    criteria: Sequence[str],
    open_findings: Sequence[GatedFinding],
    handoff: BuildHandoff | None,
    owner_answer: str | None,
) -> TurnInput:
    """Restate every criterion, open finding and latest failure for a resumed builder."""
    return _turn(
        "fix",
        "fix",
        {
            "feedback": feedback.model_dump(mode="json"),
            "criteria": list(criteria),
            "open_findings": [item.model_dump(mode="json") for item in open_findings],
            "previous_handoff": handoff.model_dump(mode="json") if handoff else None,
        },
        owner_answer,
    )


def render_restart_turn(
    issue: IssueSnapshot,
    criteria: Sequence[str],
    handoff: BuildHandoff | None,
    open_findings: Sequence[GatedFinding],
    feedback: Feedback | None,
    owner_answer: str | None = None,
) -> TurnInput:
    """Seed a fresh builder using all durable context without requiring old conversation history."""
    return _turn(
        "restart",
        "build",
        {
            "issue": issue.model_dump(mode="json"),
            "criteria": list(criteria),
            "previous_handoff": handoff.model_dump(mode="json") if handoff else None,
            "open_findings": [item.model_dump(mode="json") for item in open_findings],
            "feedback": feedback.model_dump(mode="json") if feedback else None,
            "owner_answer": owner_answer,
        },
        owner_answer,
    )


def render_review_turn(packet: ReviewPacket) -> TurnInput:
    """Render a fresh review with its exact lens and independently produced gate/CI evidence."""
    skill = {
        "general": "review",
        "security": "review-security",
        "tests": "review-tests",
        "ops": "review",
    }[packet.lens]
    return _turn("review", skill, packet.model_dump(mode="json"))


def render_verify_turn(finding: GatedFinding, hunk: str) -> TurnInput:
    """Ask an independent verifier to check one potential blocker against the changed hunk."""
    return _turn(
        "verify", "verify-finding", {"finding": finding.model_dump(mode="json"), "hunk": hunk}
    )
