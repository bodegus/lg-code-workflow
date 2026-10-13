"""Configuration files, defaults and repository identity boundaries."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lgcw.config import ConfigError, UnknownRepoError, load_config
from lgcw.models.config import Limits

FIXTURES = Path(__file__).parents[1] / "fixtures" / "config"
ROOT = Path(__file__).parents[2]


@pytest.fixture
def config_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    repos = root / "config" / "repos"
    repos.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "workflow-minimal.toml", root / "config" / "workflow.toml")
    shutil.copyfile(FIXTURES / "repo-minimal.toml", repos / "example__sandbox.toml")
    return root


@pytest.mark.unit
def test_load_defaults(config_project: Path, tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    config = load_config(config_project, home=home)
    assert config.home == home
    assert config.codex_home == home / "codex"
    assert config.limits == Limits()
    assert config.model is None
    assert config.builder_effort == "high"
    assert config.verifier_effort == "low"
    assert config.reviewer_effort["light"] == "medium"
    assert config.reviewer_effort["deep"] == "high"


@pytest.mark.unit
def test_home_from_env(
    config_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "from-env"
    monkeypatch.setenv("LGCW_HOME", str(home))
    assert load_config(config_project).codex_home == home / "codex"


@pytest.mark.unit
def test_explicit_home_wins(config_project: Path, tmp_path: Path) -> None:
    home = tmp_path / "explicit"
    assert load_config(config_project, home=home).home == home


@pytest.mark.unit
def test_home_default(config_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LGCW_HOME", raising=False)
    assert load_config(config_project).home == Path.home() / ".lgcw"


@pytest.mark.unit
def test_repo_filename_must_match(config_project: Path) -> None:
    path = config_project / "config" / "repos" / "example__sandbox.toml"
    path.rename(path.with_name("wrong__name.toml"))
    with pytest.raises(ConfigError, match="example__sandbox.toml"):
        load_config(config_project)


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["workflow.toml", "repos/example__sandbox.toml"])
def test_unknown_key_rejected(config_project: Path, filename: str) -> None:
    path = config_project / "config" / filename
    path.write_text(path.read_text() + "unknown_key = true\n")
    with pytest.raises(ConfigError):
        load_config(config_project)


@pytest.mark.unit
def test_unknown_repo_raises(config_project: Path) -> None:
    config = load_config(config_project)
    with pytest.raises(UnknownRepoError, match="example/absent"):
        config.repo("example/absent")
    assert config.repo("example/sandbox").full_name == "example/sandbox"


@pytest.mark.unit
def test_sandbox_repo_config_valid() -> None:
    repo = load_config(ROOT).repo("bodegus/oc2-publish-sandbox")
    assert repo.setup == repo.gate == ()
    assert [(check.workflow, check.job) for check in repo.required_checks] == [("CI", "test")]
    assert repo.allowed_authors == ("bodegus",)


@pytest.mark.unit
def test_missing_workflow_file_is_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="workflow.toml"):
        load_config(tmp_path)


@pytest.mark.unit
def test_invalid_toml_is_config_error(config_project: Path) -> None:
    (config_project / "config" / "workflow.toml").write_text("[broken")
    with pytest.raises(ConfigError, match="workflow.toml"):
        load_config(config_project)


@pytest.mark.unit
@pytest.mark.parametrize("key", ["home", "codex_home", "repos"])
def test_runtime_paths_and_repo_map_cannot_be_overridden(config_project: Path, key: str) -> None:
    (config_project / "config" / "workflow.toml").write_text(f'{key} = "unexpected"\n')
    with pytest.raises(ConfigError, match=key):
        load_config(config_project)


@pytest.mark.unit
def test_partial_limits_use_model_defaults(config_project: Path) -> None:
    (config_project / "config" / "workflow.toml").write_text("[limits]\nci_fix_rounds = 1\n")
    limits = load_config(config_project).limits
    assert limits.ci_fix_rounds == 1
    assert limits.gate_fix_rounds == 2


@pytest.mark.unit
def test_invalid_limit_rejected(config_project: Path) -> None:
    (config_project / "config" / "workflow.toml").write_text("[limits]\nci_fix_rounds = -1\n")
    with pytest.raises(ConfigError):
        load_config(config_project)


@pytest.mark.unit
@pytest.mark.parametrize("mapping", ["reviewer_effort", "limits.review_fix_rounds"])
def test_partial_level_maps_fill_defaults(config_project: Path, mapping: str) -> None:
    value = '"medium"' if mapping == "reviewer_effort" else "3"
    (config_project / "config" / "workflow.toml").write_text(f"[{mapping}]\ndeep = {value}\n")
    config = load_config(config_project)
    if mapping == "reviewer_effort":
        assert config.reviewer_effort == {
            "none": "low",
            "light": "medium",
            "standard": "high",
            "deep": "medium",
        }
    else:
        assert config.limits.review_fix_rounds == {"none": 0, "light": 1, "standard": 2, "deep": 3}
