"""Live assertions use actual same-call-ID shell receipts, never model claims."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.live.test_codex_smoke import tool_receipts


@pytest.mark.unit
@pytest.mark.parametrize(
    "output_id,exit_code,matched", [("call-1", 1, True), ("other", 1, False), ("call-1", 0, True)]
)
def test_shell_evidence_requires_matching_call_output(
    tmp_path: Path, output_id: str, exit_code: int, matched: bool
) -> None:
    path = tmp_path / "own-rollout.jsonl"
    receipt = {
        "chunk_id": "fixture",
        "wall_time_seconds": 0.1,
        "exit_code": exit_code,
        "original_token_count": 2,
        "output": "operation not permitted: denied.txt",
    }
    records = [
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "call-1",
                "input": 'exec_command({cmd:"printf denied > denied.txt"})',
                "name": "exec",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": output_id,
                "output": [{"type": "input_text", "text": json.dumps(receipt)}],
            },
        },
        {"type": "response_item", "payload": {"type": "message", "text": json.dumps(receipt)}},
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    calls, receipts = tool_receipts(path, "denied.txt")
    assert len(calls) == 1
    assert bool(receipts) is matched
    if matched:
        assert receipts[0].exit_code == exit_code
    assert tool_receipts(path, "not-attempted.txt") == ([], [])
