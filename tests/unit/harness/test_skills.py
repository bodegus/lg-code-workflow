"""Packaged skill names, frontmatter, size and traversal rejection."""

from __future__ import annotations

import pytest

from lgcw.git.run import git
from lgcw.harness.skills import skill_path

SKILLS = ("build", "fix", "review", "review-security", "review-tests", "verify-finding")


@pytest.mark.unit
@pytest.mark.parametrize("name", SKILLS)
def test_skills_have_frontmatter_and_budget(name: str) -> None:
    path = skill_path(name)
    data = path.read_bytes()
    text = data.decode()
    assert path.is_absolute() and path.name == "SKILL.md"
    assert text.startswith(f"---\nname: {name}\n") and "\ndescription: " in text
    assert len(data) < 5000 and "TODO" not in text


@pytest.mark.unit
@pytest.mark.parametrize("name", ["../build", "/tmp/build", "unknown", "build/SKILL.md"])
def test_skill_path_rejects_unregistered_name(name: str) -> None:
    with pytest.raises(ValueError):
        skill_path(name)


@pytest.mark.unit
async def test_packaged_build_skill_is_not_ignored_as_a_build_artifact() -> None:
    path = skill_path("build")
    root = path.parents[4]
    result = await git("check-ignore", "--no-index", "--", str(path.relative_to(root)), cwd=root)
    assert result.code == 1, "required build skill is excluded from packaging by gitignore"
