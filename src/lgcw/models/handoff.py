"""Strict builder output; all fields must be present in every turn."""

from __future__ import annotations

from typing import Literal

from lgcw.models.base import Strict


class Decision(Strict):
    """A choice supported by evidence and rejected alternatives."""

    decision: str
    alternatives_rejected: list[str]
    reason: str
    evidence: str


class AcceptanceItem(Strict):
    """The builder's claimed evidence for one acceptance criterion."""

    criterion: str
    status: Literal["met", "partial", "not_met"]
    evidence: str


class FileNote(Strict):
    """A changed file and its reading-order explanation."""

    path: str
    why: str


class TestRun(Strict):
    """A builder test claim to be independently checked by the gate."""

    command: str
    result: Literal["pass", "fail", "not_run"]
    note: str


class Risk(Strict):
    """A risk that may raise the review level."""

    area: str
    why: str


class Disposition(Strict):
    """The builder's answer to one blocking finding."""

    finding_id: str
    decision: Literal["fixed", "wont_fix", "invalid"]
    note: str
    paths: list[str]


class BuildHandoff(Strict):
    """Complete structured builder output for publishing and review."""

    status: Literal["done", "blocked", "partial"]
    summary: list[str]
    approach: str
    decisions: list[Decision]
    assumptions: list[str]
    acceptance: list[AcceptanceItem]
    files: list[FileNote]
    tests: list[TestRun]
    not_done: list[str]
    risks: list[Risk]
    open_questions: list[str]
    followups: list[str]
    dispositions: list[Disposition]
