"""Exercise collection and environment isolation through real pytest invocations."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

CONFTEST = Path(__file__).parents[1] / "conftest.py"


@pytest.mark.unit
def test_lane_marker_required(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile("def test_no_lane(): pass")
    result = pytester.runpytest()
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*exactly one explicit execution lane*"])


@pytest.mark.unit
def test_two_lane_markers_rejected(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile(
        "import pytest\n@pytest.mark.unit\n@pytest.mark.live\ndef test_both(): pass"
    )
    result = pytester.runpytest()
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*exactly one explicit execution lane*"])


@pytest.mark.unit
def test_live_skipped_without_opt_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LGCW_LIVE", raising=False)
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile(
        "import pytest\n@pytest.mark.live\ndef test_live(): raise AssertionError('ran live')"
    )
    pytester.runpytest().assert_outcomes(skipped=1)


@pytest.mark.unit
def test_live_runs_with_opt_in(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LGCW_LIVE", "1")
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile("import pytest\n@pytest.mark.live\ndef test_live(): pass")
    pytester.runpytest().assert_outcomes(passed=1)


@pytest.mark.unit
def test_isolated_env_removes_tokens() -> None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME"):
        assert key not in os.environ
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert Path(os.environ["LGCW_HOME"]).name == "lgcw"


@pytest.mark.unit
def test_isolation_overrides_parent_env(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME"):
        monkeypatch.setenv(key, "synthetic-parent-value")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LGCW_HOME", "/synthetic-parent-home")
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile("""
        import os
        from pathlib import Path
        import pytest

        @pytest.mark.unit
        def test_clean_env(tmp_path):
            for key in (
                "GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_HOME"
            ):
                assert key not in os.environ
            assert os.environ["LANGSMITH_TRACING"] == "false"
            assert Path(os.environ["LGCW_HOME"]) == tmp_path / "lgcw"
    """)
    pytester.runpytest().assert_outcomes(passed=1)
