"""Doctor host probes are injected at their explicit port boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from lgcw.doctor import ProbeResult, doctor
from tests.unit.graph.cases import context


class FakeDoctor:
    """No command execution, auth reads or network access."""

    def __init__(self, missing: str | None = None) -> None:
        self.missing = missing
        self.calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def which(self, name: str) -> Path | None:
        return None if name == self.missing else Path("/fixture/bin") / Path(name).name

    def run(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> ProbeResult:
        self.calls.append((tuple(argv), dict(env) if env is not None else None))
        return ProbeResult(code=0)


@pytest.mark.unit
def test_doctor_missing_npm(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    repo = ctx.repo.model_copy(update={"setup": ("npm ci",), "gate": ("npm run check",)})
    checks = doctor(ctx.config, repo, probe=FakeDoctor(missing="npm"))
    assert any(check.name == "tool:npm" and not check.ok for check in checks)


@pytest.mark.unit
def test_doctor_codex_login_has_only_minimal_environment(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    probe = FakeDoctor()
    checks = doctor(ctx.config, ctx.repo, probe=probe)
    assert all(check.ok for check in checks)
    login = next((argv, env) for argv, env in probe.calls if argv[-2:] == ("login", "status"))
    assert set(login[1] or {}) == {"PATH", "HOME", "LANG", "CODEX_HOME"}
    assert (login[1] or {})["CODEX_HOME"] == str(ctx.config.codex_home)
    assert all("app-server" not in argv for argv, _ in probe.calls)


@pytest.mark.unit
@pytest.mark.parametrize(
    "node,npm,ok",
    [
        ((24, 3, 0), (11, 4, 2), False),
        ((24, 20, 0), (12, 0, 2), True),
        ((26, 8, 1), (13, 0, 0), False),
    ],
)
def test_doctor_checks_configured_tool_versions(
    tmp_path: Path, node: tuple[int, int, int], npm: tuple[int, int, int], ok: bool
) -> None:
    from lgcw.models.config import RepoConfig

    ctx = context(tmp_path)
    policy = RepoConfig.model_validate(
        ctx.repo.model_dump()
        | {
            "tool_minimums": {"node": (24, 20, 0), "npm": (12, 0, 2)},
            "tool_maximums": {"npm": (13, 0, 0)},
        }
    )

    class Versions(FakeDoctor):
        def run(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> ProbeResult:
            result = super().run(argv, env)
            if argv[-1] == "--version" and argv[0] in {"node", "npm"}:
                return ProbeResult(code=0, version=node if argv[0] == "node" else npm)
            return result

    checks = doctor(ctx.config, policy, probe=Versions())
    version_checks = [check for check in checks if check.name.startswith("version:")]
    assert len(version_checks) == 2 and all(check.ok for check in version_checks) == ok
