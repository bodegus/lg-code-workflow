"""Builder evidence and fresh-thread policy are deterministic and table driven."""

from __future__ import annotations

import pytest

from lgcw.graph.claims import check_claims, should_restart_builder
from lgcw.models.handoff import FileNote
from lgcw.models.harness import Usage
from tests.unit.ci.cases import repo
from tests.unit.harness.cases import handoff


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,changed,claimed,body,code",
    [
        ("done", ("app.py",), ("app.py",), "bump version", None),
        ("done", (), (), "bump version", "no_changes"),
        ("done", ("app.py",), ("other.py",), "bump version", "claims_mismatch"),
        ("done", ("AGENTS.md",), ("AGENTS.md",), "bump version", "protected_path"),
        ("done", ("AGENTS.md",), ("AGENTS.md",), "Update AGENTS.md instructions", None),
        ("partial", ("app.py",), ("app.py",), "bump version", "handoff_incomplete"),
        ("blocked", (), (), "bump version", "handoff_incomplete"),
    ],
)
def test_check_claims(
    status: str, changed: tuple[str, ...], claimed: tuple[str, ...], body: str, code: str | None
) -> None:
    output = handoff().model_copy(
        update={
            "status": status,
            "files": [FileNote(path=path, why="fixture change") for path in claimed],
            "open_questions": ["Which supported release?"] if status != "done" else [],
        }
    )
    policy = repo().model_copy(update={"protected_globs": ("AGENTS.md", ".github/**")})
    result = check_claims(output, changed, policy, body)
    assert result.ok == (code is None)
    if code in {"no_changes", "claims_mismatch"}:
        assert result.feedback is not None and result.feedback.fingerprint
        assert result.feedback.source in {"no_changes", "gate"}
    elif code:
        assert result.ask is not None and result.ask.code == code
        if code == "handoff_incomplete":
            assert "Which supported release?" in result.ask.question


@pytest.mark.unit
@pytest.mark.parametrize(
    "context,counts,expected",
    [
        (700, {}, "context"),
        (500, {}, None),
        (700, {"context": 1}, None),
    ],
)
def test_context_restart_uses_latest_context_not_billed_sum(
    context: int, counts: dict[str, int], expected: str | None
) -> None:
    usage = Usage(
        input_tokens=10000,
        cached_input_tokens=0,
        output_tokens=20,
        reasoning_output_tokens=0,
        context_window=1000,
        context_input_tokens=context,
    )
    assert should_restart_builder(usage, [], counts, 0.6) == expected


@pytest.mark.unit
def test_repeat_failure_restart_once() -> None:
    assert should_restart_builder(None, ["one", "one"], {}, 0.6) == "failure:one"
    assert should_restart_builder(None, ["one", "one"], {"failure:one": 1}, 0.6) is None
    assert should_restart_builder(None, ["one", "two"], {}, 0.6) is None
    assert should_restart_builder(None, [], {}, 0.6) is None
