"""The product exposes no GitHub merge operation or shell merge path."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lgcw.github.port import GitHubPort


@pytest.mark.unit
def test_no_merge_calls() -> None:
    root = Path(__file__).parents[2] / "src" / "lgcw"
    forbidden = {"merge", "merge_pull_request", "mergePullRequest", "merge_pull"}
    assert not forbidden.intersection(vars(GitHubPort))
    for path in root.rglob("*.py"):
        text = path.read_text()
        assert "mergePullRequest" not in text and "gh pr merge" not in text
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden, (path, node.lineno)
