"""Pure rendering from package templates and validated records."""

from __future__ import annotations

from importlib.resources import files
from string import Template

from lgcw.ledger.markers import render_marker
from lgcw.models.base import Strict
from lgcw.models.handoff import BuildHandoff
from lgcw.models.issue import IssueSnapshot
from lgcw.models.ledger import AskMarker, Marker

_PR_TEMPLATE = files("lgcw.github").joinpath("templates/pr_body.md").read_text()
_EVENT_TEMPLATE = files("lgcw.github").joinpath("templates/event.md").read_text()
_QUESTION_TEMPLATE = files("lgcw.github").joinpath("templates/question.md").read_text()
_BODY_LIMIT = 60000


class PrStatus(Strict):
    """Code-produced gates and notes kept separate from builder claims."""

    checklist: tuple[tuple[str, bool], ...]
    ci: str
    review: str
    notes: tuple[str, ...]


def render_pr_body(issue: IssueSnapshot, handoff: BuildHandoff | None, status: PrStatus) -> str:
    """Render a bounded PR body, preserving the handoff delimiters and status section."""
    status_text = _trim(_render_status(status), _BODY_LIMIT // 3)
    template = Template(_PR_TEMPLATE)
    fixed = template.substitute(issue_number=issue.number, handoff="", status=status_text)
    model_text = _trim(_render_handoff(handoff), _BODY_LIMIT - len(fixed))
    return template.substitute(issue_number=issue.number, handoff=model_text, status=status_text)


def render_event(text: str, marker: Marker) -> str:
    """Render event prose with exactly its trusted marker at the end."""
    return Template(_EVENT_TEMPLATE).substitute(text=_safe_text(text), marker=render_marker(marker))


def render_question(question: str, marker: AskMarker) -> str:
    """Render an owner question with all three allowed response commands."""
    return Template(_QUESTION_TEMPLATE).substitute(
        question=_safe_text(question), marker=render_marker(marker)
    )


def _safe_text(text: str) -> str:
    return text.replace("<!--", "&lt;!--")


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    suffix = "\n\n_more omitted_"
    return text[: max(0, limit - len(suffix))] + suffix[:limit]


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"## {title}\n\n" + "\n".join(f"- {_safe_text(item)}" for item in items) + "\n\n"


def _render_handoff(handoff: BuildHandoff | None) -> str:
    if handoff is None:
        return "_The builder has not returned a handoff yet._"
    sections = [
        _section("Summary", handoff.summary),
        _section("Approach", [handoff.approach]),
        _section(
            "Decisions",
            [
                f"{decision.decision}: {decision.reason}. Evidence: {decision.evidence}. "
                f"Alternatives rejected: {', '.join(decision.alternatives_rejected)}"
                for decision in handoff.decisions
            ],
        ),
        _section("Assumptions", handoff.assumptions),
        _section(
            "Acceptance evidence (builder claims)",
            [f"{item.criterion}: {item.status}; {item.evidence}" for item in handoff.acceptance],
        ),
        _section("Files", [f"{file.path}: {file.why}" for file in handoff.files]),
        _section(
            "Builder test claims",
            [f"{test.command}: {test.result}; {test.note}" for test in handoff.tests],
        ),
        _section("Not done", handoff.not_done),
        _section("Risks", [f"{risk.area}: {risk.why}" for risk in handoff.risks]),
        _section("Open questions", handoff.open_questions),
        _section("Follow-ups", handoff.followups),
        _section(
            "Finding dispositions",
            [
                f"{item.finding_id}: {item.decision}; {item.note}; paths: {', '.join(item.paths)}"
                for item in handoff.dispositions
            ],
        ),
    ]
    return "".join(sections).rstrip()


def _render_status(status: PrStatus) -> str:
    checklist = "\n".join(
        f"- [{'x' if done else ' '}] {_safe_text(label)}" for label, done in status.checklist
    )
    notes = "\n".join(f"- {_safe_text(note)}" for note in status.notes)
    return (
        f"{checklist}\n\nCI: {_safe_text(status.ci)}\n"
        f"Review: {_safe_text(status.review)}\n\n{notes}"
    )
