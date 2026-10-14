"""The product exposes no GitHub merge operation or shell merge path."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from lgcw.github.port import GitHubPort


def forbidden_name(name: str) -> bool:
    """Allow only explicit read-only metadata/readiness identifiers containing merge."""
    name = name.casefold()
    allowed = {"merge_ready", "merge-base", "merge_commit", "merge_state"}
    return "merge" in name and not (name.startswith("mergeable") or name in allowed)


def literal_text(node: ast.AST) -> str | None:
    """Resolve string constants/additions without evaluating candidate code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literal_text(node.left), literal_text(node.right)
        return left + right if left is not None and right is not None else None
    return None


def assert_no_merge(text: str) -> None:
    """Reject SDK, GraphQL, REST, argv and constant-constructed merge paths."""
    tokens = (
        "mergePullRequest",
        "enablePullRequestAutoMerge",
        "enqueuePullRequest",
        '/merge"',
        "/merge'",
        "gh pr merge",
    )
    for token in tokens:
        assert token not in text, token
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(token in node.value for token in tokens)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) > 1
        ):
            value = literal_text(node.args[1])
            assert value is None or not forbidden_name(value), value
        name = None
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.alias)):
            name = node.name.rsplit(".", 1)[-1]
        if name is not None:
            assert not forbidden_name(name), name
        if isinstance(node, (ast.Tuple, ast.List)):
            values = [literal_text(item) for item in node.elts]
            assert not any(
                a == "pr" and b == "merge" for a, b in zip(values, values[1:], strict=False)
            )
        if isinstance(node, ast.BinOp):
            value = literal_text(node)
            assert value is None or not forbidden_name(value), value


@pytest.mark.unit
def test_no_merge_calls() -> None:
    root = Path(__file__).parents[2] / "src" / "lgcw"
    forbidden = {"merge", "merge_pull_request", "mergePullRequest", "merge_pull"}
    assert not forbidden.intersection(vars(GitHubPort))
    for path in root.rglob("*.py"):
        assert_no_merge(path.read_text())


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "await client.rest.pulls.async_merge()",
        "await client.rest.pulls.merge_async()",
        "await client.rest.pulls.async_merge_async()",
        "client.graphql('mergePullRequest')",
        "client.graphql('enablePullRequestAutoMerge')",
        "client.graphql('enqueuePullRequest')",
        'client.put("/repos/o/r/pulls/1/merge")',
        "run(('gh', 'pr', 'merge', '1'))",
        "run(['gh', 'pr', 'merge', '1'])",
        "getattr(pulls, 'async_' + 'merge')()",
        "await client.rest.repos.async_merge()",
        "client.pulls.merge()",
        "client.graphql('enablePullRequestAuto' 'Merge')",
        "getattr(pulls, 'async_' 'merge')()",
    ],
)
def test_no_merge_guard_catches_injected_paths(tmp_path: Path, snippet: str) -> None:
    original = Path(__file__).parents[2] / "src/lgcw/github/client.py"
    candidate = tmp_path / "client.py"
    candidate.write_text(original.read_text() + "\n" + snippet + "\n")
    with pytest.raises(AssertionError):
        assert_no_merge(candidate.read_text())


@pytest.mark.unit
@pytest.mark.parametrize(
    "snippet",
    [
        "pr.mergeable",
        "pr.mergeable_state",
        "merge_ready(state)",
        "merge_commit = 'a'",
        "pr.merge_state",
        "git('merge' + '-base')",
    ],
)
def test_no_merge_guard_allows_read_only_metadata(snippet: str) -> None:
    assert_no_merge(snippet)
