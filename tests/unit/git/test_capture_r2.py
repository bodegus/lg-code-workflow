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


@pytest.mark.unit
@pytest.mark.parametrize("escaping_link", [False, True])
async def test_prepare_checks_complete_large_tracked_path_list(
    tmp_path: Path, escaping_link: bool
) -> None:
    from lgcw.git.run import git
    from tests.unit.git.helpers import checked

    remote = await origin(tmp_path)
    for index in range(1000):
        (remote.seed / (f"tracked-{index:04d}-" + "x" * 80)).write_text("fixture\n")
    if escaping_link:
        (remote.seed / "zzzz-escape").symlink_to(tmp_path / "outside")
    await checked(remote.seed, "add", "-A")
    await checked(remote.seed, "commit", "-m", "large tracked baseline")
    await checked(remote.seed, "push", "origin", "main")
    # The ordinary log capture remains bounded and cannot safely supply this listing.
    listing = await git("ls-files", "--cached", "-z", cwd=remote.seed)
    assert listing.code == 0 and listing.capture_truncated
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    issue = IssueRef(repo="fixture/sandbox", number=7)
    if escaping_link:
        with pytest.raises(ValueError, match="symlink escapes checkout: zzzz-escape"):
            await workspace.prepare(policy(), issue, "lgcw/issue-7")
    else:
        info = await workspace.prepare(policy(), issue, "lgcw/issue-7")
        assert info.branch == "lgcw/issue-7"
        assert (info.repo_dir / ("tracked-0999-" + "x" * 80)).read_text() == "fixture\n"


@pytest.mark.unit
@pytest.mark.parametrize(
    "baseline_large,head_large,instruction_alias",
    [(False, True, False), (True, False, False), (True, True, False), (True, True, True)],
    ids=["large-head", "large-base", "large-both", "large-instruction-alias"],
)
async def test_large_review_trees_preserve_trusted_instruction_boundary(
    tmp_path: Path, baseline_large: bool, head_large: bool, instruction_alias: bool
) -> None:
    import shutil

    from lgcw.git.run import git
    from tests.unit.git.helpers import checked

    remote = await origin(tmp_path)
    (remote.seed / "docs").mkdir()
    (remote.seed / "docs/AGENTS.md").write_text("Trusted nested instructions.\n")
    if baseline_large:
        (remote.seed / "data").mkdir()
        for index in range(1000):
            (remote.seed / "data" / (f"tracked-{index:04d}-" + "x" * 80)).write_text("fixture\n")
    await checked(remote.seed, "add", "-A")
    await checked(remote.seed, "commit", "-m", "review baseline")
    await checked(remote.seed, "push", "origin", "main")
    base = await checked(remote.seed, "rev-parse", "HEAD")
    workspace = GitWorkspace(tmp_path / "lgcw", origin=remote.bare)
    issue = IssueRef(repo="fixture/sandbox", number=7)
    info = await workspace.prepare(policy(), issue, "lgcw/issue-7")
    if head_large and not baseline_large:
        (info.repo_dir / "data").mkdir()
        for index in range(1000):
            (info.repo_dir / "data" / (f"tracked-{index:04d}-" + "x" * 80)).write_text("fixture\n")
    elif baseline_large and not head_large:
        shutil.rmtree(info.repo_dir / "data")
    (info.repo_dir / "AGENTS.md").write_text("Hostile head instructions.\n")
    (info.repo_dir / ".agents/guide.md").write_text("Hostile head skill.\n")
    (info.repo_dir / ".codex").mkdir()
    (info.repo_dir / ".codex/settings.json").write_text("{}\n")
    (info.repo_dir / "app.py").write_text("VERSION = '0.1.1'\n")
    if instruction_alias:
        shutil.rmtree(info.repo_dir / "docs")
        (info.repo_dir / "docs").symlink_to(".agents", target_is_directory=True)
    # Fixture commits bypass the intentionally small changed-path task limit, not any review check.
    await checked(info.repo_dir, "add", "-A")
    await checked(info.repo_dir, "commit", "-m", "review head")
    head = await checked(info.repo_dir, "rev-parse", "HEAD")
    for revision, large in ((base, baseline_large), (head, head_large)):
        ordinary = await git("ls-tree", "-r", "--name-only", "-z", revision, cwd=info.repo_dir)
        assert ordinary.code == 0 and ordinary.capture_truncated == large
    if instruction_alias:
        with pytest.raises(ValueError, match="base instruction parent symlink"):
            await workspace.reviewer_checkout(head, base)
    else:
        checkout = await workspace.reviewer_checkout(head, base)
        assert (checkout / "AGENTS.md").read_text() == "Trusted base instructions.\n"
        assert (checkout / ".agents/guide.md").read_text() == "Trusted skill.\n"
        assert (checkout / "docs/AGENTS.md").read_text() == "Trusted nested instructions.\n"
        assert not (checkout / ".codex").exists()
        assert (checkout / "app.py").read_text() == "VERSION = '0.1.1'\n"
        assert await checked(checkout, "rev-parse", "HEAD") == head
