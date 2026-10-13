"""Typed, redacted run evidence with bounded paths and immutable atomic artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lgcw.models.base import Strict
from lgcw.models.harness import TurnInput, TurnOutcome, Usage
from lgcw.runlog import RunLog
from tests.fakes.clock import FakeClock


class Output(Strict):
    """Small structured output containing arbitrary evidence strings."""

    answer: str


def prompt() -> TurnInput:
    """Return a synthetic prompt without external services."""
    return TurnInput(skill="fixture", text="Return fixture output", data=None, data_label=None)


def outcome() -> TurnOutcome[Output]:
    """Return measured fixture usage, including cached and reasoning tokens."""
    return TurnOutcome[Output](
        session_id="fixture-session",
        output=Output(answer="fixture"),
        usage=Usage(
            input_tokens=100,
            cached_input_tokens=40,
            output_tokens=20,
            reasoning_output_tokens=8,
            context_window=1000,
        ),
        duration_s=1.5,
        rollout_path=None,
    )


@pytest.mark.unit
async def test_events_are_jsonl_with_timestamps(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 10, 13, tzinfo=UTC))
    log = RunLog(tmp_path, clock=clock)
    log.event("node_start", node="build", attempt=1)
    await clock.sleep(2)
    log.event("node_end", node="build", duration_s=2.0)
    records = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(records) == 2
    assert datetime.fromisoformat(records[1]["timestamp"]) > datetime.fromisoformat(
        records[0]["timestamp"]
    )
    assert records[0]["kind"] == "node_start" and records[0]["fields"]["attempt"] == 1


@pytest.mark.unit
def test_structured_authorization_redaction_preserves_json_and_neighbors(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.event(
        "error",
        node="build",
        message="Authorization: Bearer opaque-secret",
        neighbor="kept",
        headers={"Authorization": "Basic opaque-header", "Accept": "application/json"},
    )
    text = (tmp_path / "events.jsonl").read_text()
    record = json.loads(text)
    assert "opaque-secret" not in text and "opaque-header" not in text
    assert record["fields"]["neighbor"] == "kept"
    assert record["fields"]["headers"]["Accept"] == "application/json"


@pytest.mark.unit
def test_turn_records_output_usage_error_and_redacts(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    synthetic = "ghp_" + "A" * 36
    result = outcome().model_copy(
        update={"output": Output(answer=f"Authorization: Bearer {synthetic}")}
    )
    path = log.turn(1, "builder", prompt(), result, None)
    data = json.loads(path.read_text())
    assert data["outcome"]["usage"]["cached_input_tokens"] == 40
    assert data["outcome"]["output"]["answer"].endswith("[REDACTED]")
    assert synthetic not in path.read_text()
    failed = json.loads(log.turn(2, "reviewer", prompt(), None, "login expired").read_text())
    assert failed["outcome"] is None and failed["error"] == "login expired"
    with pytest.raises(FileExistsError):
        log.turn(1, "builder", prompt(), outcome(), None)


@pytest.mark.unit
def test_artifact_redacts_and_refuses_replacement(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    raw = "Authorization: Basic opaque-secret\nsecond line"
    path = log.artifact("ci/job-1.log", raw)
    assert path.read_text() == "Authorization: [REDACTED]\nsecond line"
    assert path.stat().st_mode & 0o077 == 0
    assert log.artifact("ci/job-1.log", raw) == path
    with pytest.raises(FileExistsError):
        log.artifact("ci/job-1.log", "different evidence")


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative", ["../outside", "/tmp/outside", "repo/app.py", "review-abc/AGENTS.md", "."]
)
def test_artifact_paths_are_bounded(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        RunLog(tmp_path).artifact(relative, "evidence")


@pytest.mark.unit
def test_artifact_does_not_follow_escape_symlink(tmp_path: Path) -> None:
    run_dir, outside = tmp_path / "run", tmp_path / "outside"
    run_dir.mkdir()
    outside.mkdir()
    (run_dir / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        RunLog(run_dir).artifact("alias/evidence", "must stay inside")
    assert not (outside / "evidence").exists()


@pytest.mark.unit
def test_posted_body_and_ids_are_retained(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    path = log.posted(
        "review",
        "Finding body\n-builder",
        {"review_id": 42, "url": "https://example.test/review/42"},
    )
    text = path.read_text()
    assert "Finding body\n-builder" in text and '"review_id": 42' in text
    assert path.parent == tmp_path / "github"
    again = log.posted("comment", "Another body\n-builder", {"comment_id": 43})
    assert again != path


@pytest.mark.unit
def test_recovered_posted_receipt_is_not_duplicated(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    first = log.posted("comment", "Canonical body", {"comment_id": 42})
    second = log.posted("comment", "Canonical body", {"comment_id": 42})
    assert first == second and len(list((tmp_path / "github").glob("*.md"))) == 1


@pytest.mark.unit
def test_nonfinite_json_is_rejected_without_writing_record(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    with pytest.raises(ValueError):
        log.event("invalid", seconds=float("nan"))
    assert not (tmp_path / "events.jsonl").exists()


@pytest.mark.unit
def test_posted_preserves_marker_after_semantic_header_redaction(tmp_path: Path) -> None:
    from lgcw.ledger.markers import parse_markers, render_marker
    from lgcw.models.ledger import BlockedMarker

    marker = BlockedMarker(reason="Authorization: Basic b3BhcXVlLXNlY3JldA==")
    path = RunLog(tmp_path).posted(
        "blocked", "Stopped\n" + render_marker(marker), {"comment_id": 1}
    )
    content = path.read_text()
    parsed = parse_markers(content)
    assert len(parsed) == 1 and isinstance(parsed[0], BlockedMarker)
    assert parsed[0].reason == "Authorization: [REDACTED]"
    assert "b3BhcXVlLXNlY3JldA==" not in content
