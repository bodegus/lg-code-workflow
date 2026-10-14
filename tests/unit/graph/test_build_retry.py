"""Question-specific retry grants are an explicit, exhaustive build continuation contract."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lgcw.graph.retry import RETRY_POLICIES


@pytest.mark.unit
@pytest.mark.parametrize(
    "code,policy",
    [
        ("build_unknown", "resume"),
        ("harness_auth", "resume"),
        ("harness_quota", "resume"),
        ("harness_error", "resume"),
        ("harness_session_lost", "fresh"),
        ("builder_restart_limit", "fresh"),
        ("gate_fix_limit", "fix"),
        ("no_changes", "fix"),
        ("handoff_incomplete", "resume"),
        ("protected_path", "resume"),
        ("workspace_changed", "rebuild"),
        ("build_evidence_missing", "rebuild"),
        ("local_head_changed", "inspect"),
        ("handoff_too_large", "inspect"),
        ("node_error", "resume"),
    ],
)
def test_build_retry_policy_table(code: str, policy: str) -> None:
    assert RETRY_POLICIES[code] == policy


@pytest.mark.unit
def test_every_literal_build_question_has_a_retry_policy() -> None:
    root = Path(__file__).parents[3] / "src/lgcw/graph"
    found: set[str] = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "attention"
                and len(node.args) >= 3
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[2], ast.Constant)
                and node.args[2].value == "build"
            ):
                found.add(str(node.args[0].value))
    assert found <= RETRY_POLICIES.keys()
