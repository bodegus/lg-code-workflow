"""Reports retain per-turn measured usage, unknowns and malformed-record warnings."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.runlog import RunLog, render_report
from tests.unit.runlog.test_log import outcome, prompt


@pytest.mark.unit
def test_report_has_timeline_turns_and_totals(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.event("node_start", node="build", attempt=1)
    log.event("node_end", node="build", duration_s=1.5)
    log.turn(1, "builder", prompt(), outcome(), None)
    log.turn(
        2, "reviewer", prompt(), outcome().model_copy(update={"session_id": "fresh-review"}), None
    )
    log.event("loop_round", node="build", loop="ci_fix", round=1)
    log.event("ci_decision", node="ci_wait", action="rerun", klass="infra", head_sha="a" * 40)
    log.event("finding", node="review", finding_id="F-1", blocking=True)
    log.event("disposition", node="publish", finding_id="F-1", decision="fixed")
    log.event("run_end", outcome="merge_ready")
    report = render_report(tmp_path)
    for value in (
        "merge_ready",
        "Timeline",
        "Agent turns",
        "builder",
        "reviewer",
        "ci_fix",
        "infra",
        "rerun",
        "F-1",
        "fixed",
    ):
        assert value in report
    assert "| Total known usage | 200 | 80 | 40 | 16 |" in report
    assert "| 1 | builder | fixture-session | 100 | 40 | 20 | 8 |" in report
    assert "| 2 | reviewer | fresh-review | 100 | 40 | 20 | 8 |" in report


@pytest.mark.unit
def test_report_empty_run(tmp_path: Path) -> None:
    report = render_report(tmp_path)
    assert "No events recorded" in report and "No agent turns recorded" in report
    assert "Outcome: unknown" in report


@pytest.mark.unit
def test_report_unknown_usage_is_not_zero(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.turn(1, "builder", prompt(), None, "login expired")
    report = render_report(tmp_path)
    assert "Usage unavailable for 1 turn" in report and "login expired" in report
    assert "| 1 | builder | — | — | — | — | — |" in report


@pytest.mark.unit
def test_report_warns_about_truncated_records_and_escapes_prose(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.event("node_end", node="build|<bad>", duration_s=1.0)
    with (tmp_path / "events.jsonl").open("a") as stream:
        stream.write('{"interrupted":')
    (tmp_path / "turns").mkdir()
    (tmp_path / "turns/1-builder.json").write_text('{"interrupted":')
    report = render_report(tmp_path)
    assert "malformed event line 2" in report and "malformed turn" in report
    assert "build\\|&lt;bad&gt;" in report


@pytest.mark.unit
def test_report_preserves_neighbor_after_authorization_redaction(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.event("error", message="Authorization: Bearer opaque-secret", neighbor="NEIGHBOR_RETAINED")
    report = render_report(tmp_path)
    assert "opaque-secret" not in report and "NEIGHBOR_RETAINED" in report


@pytest.mark.unit
def test_derived_report_view_can_be_regenerated(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    first = log.artifact("report.md", render_report(tmp_path))
    log.event("run_end", outcome="waiting")
    second = log.artifact("report.md", render_report(tmp_path))
    assert first == second and "Outcome: waiting" in second.read_text()


@pytest.mark.unit
def test_report_does_not_read_turn_symlink_outside_run(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    run_dir = tmp_path / "run"
    private = RunLog(outside).turn(
        1,
        "builder",
        prompt(),
        outcome().model_copy(update={"session_id": "OUTSIDE_PRIVATE_SESSION"}),
        None,
    )
    (run_dir / "turns").mkdir(parents=True)
    (run_dir / "turns/0001-builder.json").symlink_to(private)
    report = render_report(run_dir)
    assert "OUTSIDE_PRIVATE_SESSION" not in report and "outside run directory" in report


@pytest.mark.unit
def test_report_marks_unfinished_invocation_incomplete(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.event("run_end", outcome="merge_ready")
    log.event("run_start")
    report = render_report(tmp_path)
    assert "Outcome: incomplete" in report and "execution status is unproven" in report


@pytest.mark.unit
def test_saved_report_preserves_neighbor_after_semantic_redaction(tmp_path: Path) -> None:
    log = RunLog(tmp_path)
    log.event("error", message="Authorization: Bearer opaque-secret", neighbor="SAVED_NEIGHBOR")
    saved = log.artifact("report.md", render_report(tmp_path))
    assert "SAVED_NEIGHBOR" in saved.read_text()
    path = log.write_report()
    assert "opaque-secret" not in path.read_text() and "SAVED_NEIGHBOR" in path.read_text()
