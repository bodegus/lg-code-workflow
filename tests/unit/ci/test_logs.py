"""Bounded error evidence, Unicode caps and stable failure identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgcw.ci.logs import failure_fingerprint, trim_job_log
from lgcw.models.github import JobView


@pytest.mark.unit
def test_trim_keeps_errors_and_caps_size() -> None:
    raw = (Path(__file__).parents[2] / "fixtures" / "ci" / "big.log").read_text()
    output = trim_job_log(raw, ["Run tests"])
    assert len(raw.splitlines()) == 2900
    assert len(output.encode()) <= 8192
    assert "##[error]fixture failure" in output
    assert "FAILING-STEP-TAIL" in output
    assert "CLEANUP-END" not in output
    assert "\x1b[" not in output and "2026-10-13T" not in output


@pytest.mark.unit
@pytest.mark.parametrize("cap", [0, 1, 64, 512, 8192])
def test_utf8_cap(cap: int) -> None:
    output = trim_job_log("##[error]failure αβγ\n" + "雪" * 10000, ["Test"], max_bytes=cap)
    assert len(output.encode()) <= cap


@pytest.mark.unit
def test_empty_log_and_redaction() -> None:
    assert len(trim_job_log("", []).encode()) <= 8192
    synthetic = "ghp_" + "A" * 36
    assert synthetic not in trim_job_log("##[error]" + synthetic, ["Test"])


@pytest.mark.unit
def test_fingerprint_normalises_error_paths_and_digits() -> None:
    first = failure_fingerprint("CI", "Node 24", "Test", "error /tmp/first.py:12 expected 3")
    second = failure_fingerprint("CI", "Node 24", "Test", "error /work/second.py:99 expected 4")
    assert first == second
    assert first != failure_fingerprint(
        "CI", "Node 26", "Test", "error /tmp/first.py:12 expected 3"
    )


@pytest.mark.unit
def test_synthetic_job_boundary_fixture() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "ci" / "job.json"
    record = JobView.model_validate_json(fixture.read_text())
    assert record.failed_steps == ("Run tests",)


@pytest.mark.unit
def test_unnamed_error_group_is_retained_before_cleanup() -> None:
    raw = "##[group]Unknown\n##[error]broken\nexit code 1\n##[endgroup]\n##[group]Cleanup\ndone"
    output = trim_job_log(raw, ["Other"])
    assert "broken" in output and "exit code 1" in output and "done" not in output


@pytest.mark.unit
@pytest.mark.parametrize("failed_steps", [("npm test",), ("Post cleanup",), ("unknown",)])
def test_real_layout_keeps_output_after_endgroup(failed_steps: tuple[str, ...]) -> None:
    path = Path(__file__).parents[2] / "fixtures" / "ci" / "real-layout.log"
    output = trim_job_log(path.read_text(), failed_steps)
    assert "FAILED actual_test" in output
    assert "Process completed with exit code 1" in output
    assert "CLEANUP-SHOULD-NOT-APPEAR" not in output
    assert "\ufeff" not in output


@pytest.mark.unit
@pytest.mark.parametrize(
    "sequence", ["\x1b]52;c;clipboard-payload\x07", "\x1bPdevice-payload\x1b\\"]
)
def test_terminal_sequences_are_removed_with_their_payload(sequence: str) -> None:
    result = trim_job_log(sequence + "\nError: retained failure\n\x00", ["Run tests"])
    assert "payload" not in result and "\x1b" not in result and "\x00" not in result
    assert "retained failure" in result
