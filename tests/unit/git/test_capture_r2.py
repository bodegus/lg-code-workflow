"""Real subprocess redaction and complete git-metadata boundary regressions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lgcw.git.run import run_process
from lgcw.git.workspace import GitWorkspace
from lgcw.models.issue import IssueRef
from tests.unit.git.helpers import origin, policy


@pytest.mark.unit
@pytest.mark.parametrize("margin_scale", [1, 2])
async def test_redaction_margin_survives_shrinking_windows(
    tmp_path: Path, margin_scale: int
) -> None:
    size = 200000
    marker = f"\n[... capture truncated; original stream {size} bytes ...]\n"
    head = (65536 - len(marker.encode())) // 2
    tail = 65536 - len(marker.encode()) - head
    token = ("ghp_" + "A" * 36).encode()
    block = b"\n" + (token + b"\n") * 100
    data = bytearray(b"x" * size)
    data[: len(block)] = block
    prefix_end = head + margin_scale * 1024
    data[prefix_end - 4 : prefix_end - 4 + len(token)] = token
    suffix_start = size - tail - margin_scale * 1024
    data[suffix_start - 1 : suffix_start - 1 + len(token)] = token
    data[suffix_start + len(token) : suffix_start + len(token) + len(block)] = block
    path = tmp_path / "synthetic-output.bin"
    path.write_bytes(data)
    result = await run_process(
        (
            sys.executable,
            "-c",
            "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())",
            str(path),
        ),
        cwd=tmp_path,
    )
    assert result.code == 0 and len(result.out.encode()) <= 65536
    assert "ghp_" not in result.out
    assert "hp_" + "A" * 36 not in result.out
    assert "[REDACTED]" in result.out


@pytest.mark.unit
async def test_truncated_git_paths_are_never_parsed_as_complete(tmp_path: Path) -> None:
    remote = await origin(tmp_path)
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    issue = IssueRef(repo="fixture/sandbox", number=7)
    info = await workspace.prepare(policy(), issue, "lgcw/issue-7")
    for index in range(1000):
        (info.repo_dir / (str(index) + "-" + "x" * 80)).write_text("fixture\n")
    with pytest.raises(ValueError, match="truncated|incomplete"):
        await workspace.changed_paths(remote.base)


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["ghp_", "github_pat_", "sk-", "jwt"])
def test_embedded_credential_shapes_are_redacted(kind: str) -> None:
    from lgcw.runlog import redact

    token = kind + "A" * 40 if kind != "jwt" else "eyJ" + "A" * 24 + "." + "B" * 24 + "." + "C" * 24
    result = redact("padding" + token + "suffix")
    assert token not in result and "[REDACTED]" in result


@pytest.mark.unit
@pytest.mark.parametrize("text", ["task-oriented-long-helper.py", "task-prefixed-workflow-name"])
def test_ordinary_task_paths_are_not_mistaken_for_embedded_api_keys(text: str) -> None:
    from lgcw.runlog import redact

    assert redact(text) == text
