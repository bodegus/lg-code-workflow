"""Select review depth from trusted paths, labels, risks and a monotonic floor."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from lgcw.models.config import Limits, RepoConfig, ReviewThresholds
from lgcw.models.handoff import Risk
from lgcw.models.review import DiffStat, Lens, LevelDecision, ReviewLevel

_ORDER: tuple[ReviewLevel, ...] = ("none", "light", "standard", "deep")
_DEEP_GLOBS = (
    "**/.github/workflows/**",
    "**/.agents/**",
    "**/.claude/**",
    "**/AGENTS.md",
    "**/CLAUDE.md",
    "**/pyproject.toml",
    "**/package.json",
    "**/requirements*.txt",
    "**/Cargo.toml",
    "**/go.mod",
    "**/Gemfile",
    "**/pom.xml",
    "**/build.gradle*",
)


def pick_level(
    diff: DiffStat,
    owner_labels: Sequence[str],
    builder_risks: Sequence[Risk],
    repo: RepoConfig,
    thresholds: ReviewThresholds,
    limits: Limits,
    *,
    previous: LevelDecision | None = None,
) -> LevelDecision:
    """Select the first matching review tier, respecting owner overrides and previous depth."""
    paths = [PurePosixPath(path) for path in diff.paths]

    def matches(globs: Sequence[str]) -> bool:
        return any(path.full_match(pattern) for path in paths for pattern in globs)

    risks = [risk.name for risk in repo.risk_classes if matches(risk.globs)]
    source_without_tests = matches(repo.source_globs) and not matches(repo.tests_globs)
    ops = "deploy_ops" in risks
    level: ReviewLevel
    reasons: list[str] = []
    if (
        matches(_DEEP_GLOBS)
        or any(risk != "deploy_ops" for risk in risks)
        or (diff.changed_lines > thresholds.standard_max_lines)
    ):
        level = "deep"
        reasons.append("sensitive path, dependency manifest, risk class or large diff")
    elif (
        diff.changed_lines > thresholds.light_max_lines
        or len(diff.files) >= thresholds.many_files
        or ops
        or source_without_tests
    ):
        level = "standard"
        reasons.append("diff size, operations risk or source changed without tests")
    elif all(
        any(
            path.full_match(pattern)
            for pattern in (*repo.docs_globs, *repo.tests_globs, *repo.excluded_globs)
        )
        for path in paths
    ):
        level = "none"
        reasons.append("only docs, tests or generated paths; CI qualification remains required")
    else:
        level = "light"
        reasons.append("small code change")
    if builder_risks and _ORDER.index(level) < _ORDER.index("standard"):
        level = "standard"
        reasons.append("builder declared risk")
    overrides = [name for name in _ORDER if f"lgcw:review-{name}" in owner_labels]
    if overrides:
        level = overrides[-1]
        reasons.append(f"owner override: {level}")
    if previous is not None:
        if _ORDER.index(previous.level) > _ORDER.index(level):
            level = previous.level
            reasons.append("previous review level is a floor")
        reasons.extend(previous.reasons)
    lenses: list[Lens] = []
    if level != "none":
        lenses.append("general")
    if level == "deep":
        lenses.extend(("security", "tests"))
    elif level == "standard" and source_without_tests:
        lenses.append("tests")
    if level == "standard" and ops:
        lenses.append("ops")
    if previous is not None and level != "deep":
        lenses.extend(previous.lenses)
    return LevelDecision(
        level=level,
        lenses=tuple(dict.fromkeys(lenses)),
        reasons=tuple(dict.fromkeys(reasons)),
        fix_round_cap=limits.review_fix_rounds[level],
    )
