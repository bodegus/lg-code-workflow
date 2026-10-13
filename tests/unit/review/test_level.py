"""Review thresholds, trusted overrides, risks and monotonic fix deltas."""

from __future__ import annotations

import pytest

from lgcw.models.config import Limits, ReviewThresholds, RiskClass
from lgcw.models.handoff import Risk
from lgcw.models.review import DiffStat, FileChange, Lens, LevelDecision, ReviewLevel
from lgcw.review.level import pick_level
from tests.unit.ci.cases import repo


def diff(*paths: str, lines: int = 40) -> DiffStat:
    """Return synthetic changed paths with a known total size."""
    return DiffStat(
        files=tuple(
            FileChange(path=path, added=lines if i == 0 else 0, deleted=0)
            for i, path in enumerate(paths)
        )
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "change,expected,lenses",
    [
        (diff("README.md"), "none", ()),
        (diff("tests/test_a.py"), "none", ()),
        (diff("src/a.py", "tests/test_a.py"), "light", ("general",)),
        (diff("src/a.py", "tests/test_a.py", lines=120), "standard", ("general",)),
        (diff("src/a.py"), "standard", ("general", "tests")),
        (diff(".github/workflows/ci.yml"), "deep", ("general", "security", "tests")),
        (diff(".agents/skills/test/SKILL.md"), "deep", ("general", "security", "tests")),
        (diff("nested/AGENTS.md"), "deep", ("general", "security", "tests")),
        (diff("pyproject.toml"), "deep", ("general", "security", "tests")),
        (diff("src/a.py", "tests/test_a.py", lines=500), "deep", ("general", "security", "tests")),
        (diff(*(f"docs/{i}.md" for i in range(8))), "standard", ("general",)),
    ],
)
def test_level(change: DiffStat, expected: ReviewLevel, lenses: tuple[Lens, ...]) -> None:
    result = pick_level(change, (), (), repo(), ReviewThresholds(), Limits())
    assert result.level == expected and result.lenses == lenses
    assert result.fix_round_cap == Limits().review_fix_rounds[expected]


@pytest.mark.unit
def test_owner_override_and_previous_floor() -> None:
    previous = LevelDecision(
        level="deep", lenses=("general", "security", "tests"), reasons=("prior",), fix_round_cap=2
    )
    change = diff(".github/workflows/ci.yml")
    initial = pick_level(change, ("lgcw:review-light",), (), repo(), ReviewThresholds(), Limits())
    assert initial.level == "light"
    later = pick_level(
        change, ("lgcw:review-light",), (), repo(), ReviewThresholds(), Limits(), previous=previous
    )
    assert later.level == "deep" and "prior" in later.reasons and "security" in later.lenses


@pytest.mark.unit
def test_builder_risk_raises_and_owner_wins() -> None:
    risks = (Risk(area="boundary", why="new parsing input"),)
    change = diff("src/a.py", "tests/test_a.py")
    assert pick_level(change, (), risks, repo(), ReviewThresholds(), Limits()).level == "standard"
    assert (
        pick_level(change, ("lgcw:review-none",), risks, repo(), ReviewThresholds(), Limits()).level
        == "none"
    )


@pytest.mark.unit
def test_configured_ops_and_security_paths() -> None:
    policy = repo().model_copy(
        update={
            "risk_classes": (
                RiskClass(name="deploy_ops", globs=("deploy/**",)),
                RiskClass(name="secrets_auth", globs=("auth/**",)),
            )
        }
    )
    ops = pick_level(diff("deploy/release.yml"), (), (), policy, ReviewThresholds(), Limits())
    assert ops.level == "standard" and "ops" in ops.lenses
    auth = pick_level(diff("auth/login.py"), (), (), policy, ReviewThresholds(), Limits())
    assert auth.level == "deep"


@pytest.mark.unit
def test_conflicting_labels_choose_stronger() -> None:
    result = pick_level(
        diff("README.md"),
        ("lgcw:review-none", "lgcw:review-deep"),
        (),
        repo(),
        ReviewThresholds(),
        Limits(),
    )
    assert result.level == "deep"


@pytest.mark.unit
def test_deep_keeps_three_lenses_even_when_ops_also_changed() -> None:
    policy = repo().model_copy(
        update={"risk_classes": (RiskClass(name="deploy_ops", globs=("deploy/**",)),)}
    )
    previous = LevelDecision(
        level="standard", lenses=("general", "ops"), reasons=("ops",), fix_round_cap=2
    )
    result = pick_level(
        diff("deploy/release.yml", lines=500),
        (),
        (),
        policy,
        ReviewThresholds(),
        Limits(),
        previous=previous,
    )
    assert result.level == "deep" and result.lenses == ("general", "security", "tests")


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    [
        "package-lock.json",
        "nested/uv.lock",
        "Cargo.lock",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
    ],
)
def test_excluded_lockfile_is_dependency_evidence(name: str) -> None:
    from lgcw.review.diffstat import parse_numstat

    stat = parse_numstat(f"1\t1\t{name}\n", ("**/*",))
    assert pick_level(stat, (), (), repo(), ReviewThresholds(), Limits()).level == "deep"
    assert stat.changed_lines == 0


@pytest.mark.unit
def test_fully_excluded_diff_is_not_no_review() -> None:
    from lgcw.review.diffstat import parse_numstat

    stat = parse_numstat("1\t0\tgenerated/data.json\n", ("**/*",))
    assert pick_level(stat, (), (), repo(), ReviewThresholds(), Limits()).level != "none"
