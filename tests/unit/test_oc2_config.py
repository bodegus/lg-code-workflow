"""Long-run target policy must cover all unit tests and retain protected boundaries."""

from __future__ import annotations

import fnmatch
import shlex
from pathlib import Path

import pytest

from lgcw.config import load_config

ROOT = Path(__file__).parents[2]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("PLAN.md", False),
        (".github/workflows/ci.yml", True),
        ("AGENTS.md", True),
        ("CLAUDE.md", True),
        ("versions.lock.json", True),
        ("agents/active/main/SOUL.md", True),
        (".agents/skills/build/SKILL.md", True),
        (".claude/settings.json", True),
        (".codex/config.toml", True),
        (".env.example", True),
    ],
)
def test_oc2_long_run_protection(path: str, protected: bool) -> None:
    repo = load_config(ROOT).repo("bodegus/openclaw2-deploy")
    assert any(fnmatch.fnmatchcase(path, glob) for glob in repo.protected_globs) is protected


@pytest.mark.unit
def test_oc2_gate_runs_whole_portable_files_and_keeps_full_native_ci() -> None:
    repo = load_config(ROOT).repo("bodegus/openclaw2-deploy")
    command = next(command for command in repo.gate if "pytest" in command)
    assert command.startswith('TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)" ')
    args = shlex.split(command)
    targets = {arg for arg in args if arg.startswith("tests/")}
    assert targets
    assert all(path.startswith("tests/unit/") and path.endswith(".py") for path in targets)
    pytest_args = args[args.index("python") + 3 :]
    assert not {"-k", "-m", "--ignore", "--deselect"} & set(pytest_args)
    assert any(check.workflow == "CI" and check.job == "unit" for check in repo.required_checks)
