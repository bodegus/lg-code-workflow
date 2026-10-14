"""Doctor checks credential denial inside the pinned builder sandbox."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from lgcw.doctor import HostProbe, ProbeResult, doctor
from tests.unit.graph.cases import context
from tests.unit.test_doctor import FakeDoctor


@pytest.mark.unit
@pytest.mark.parametrize("code,ok", [(0, False), (1, True), (-1, False)])
def test_doctor_requires_builder_sandbox_github_denial(tmp_path: Path, code: int, ok: bool) -> None:
    class SandboxDoctor(FakeDoctor):
        def run(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> ProbeResult:
            result = super().run(argv, env)
            return ProbeResult(code=code) if "sandbox" in argv else result

    ctx = context(tmp_path)
    probe = SandboxDoctor()
    checks = doctor(ctx.config, ctx.repo, probe=probe)
    check = next(item for item in checks if item.name == "github_sandbox_isolation")
    assert check.ok == ok
    login = next((argv, env) for argv, env in probe.calls if argv[-2:] == ("login", "status"))
    sandbox = next((argv, env) for argv, env in probe.calls if "sandbox" in argv)
    assert sandbox[0] == (login[0][0], "sandbox", "-P", ":workspace", "--", "gh", "auth", "status")
    assert sandbox[1] == login[1]
    assert set(sandbox[1] or {}) == {"PATH", "HOME", "LANG", "CODEX_HOME"}
    assert any(item.name == "github_login" and item.ok for item in checks)
    assert "app-server" not in sandbox[0]


@pytest.mark.unit
def test_unavailable_probe_is_not_credential_denial(tmp_path: Path) -> None:
    result = HostProbe().run((str(tmp_path / "missing-executable"),))
    assert result.code == -1
