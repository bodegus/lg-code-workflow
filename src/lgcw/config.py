"""Read trusted TOML configuration into validated workflow boundaries."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lgcw.models.config import RepoConfig, WorkflowConfig
from lgcw.models.config import UnknownRepoError as UnknownRepoError


class ConfigError(ValueError):
    """A configuration file is missing, malformed or inconsistent."""


def load_config(root: Path, *, home: Path | None = None) -> WorkflowConfig:
    """Load workflow policy and each explicitly configured target repository.

    Args:
        root: Project directory containing config/workflow.toml and config/repos/.
        home: Optional runtime directory, overriding LGCW_HOME and the user default.

    Raises:
        ConfigError: Invalid TOML, unknown options, invalid values or a repository filename
            that disagrees with its full_name.
    """
    workflow_path = root / "config" / "workflow.toml"
    options = _read_toml(workflow_path)
    managed_keys = {"home", "codex_home", "repos"} & options.keys()
    if managed_keys:
        raise ConfigError(
            f"{workflow_path}: runtime-managed keys: {', '.join(sorted(managed_keys))}"
        )

    repos: dict[str, RepoConfig] = {}
    for path in sorted((root / "config" / "repos").glob("*.toml")):
        try:
            repo = RepoConfig.model_validate(_read_toml(path))
        except ValidationError as error:
            raise ConfigError(f"{path}: {error}") from error
        expected_name = repo.full_name.replace("/", "__") + ".toml"
        if path.name != expected_name:
            raise ConfigError(f"{path}: full_name requires filename {expected_name}")
        repos[repo.full_name] = repo

    runtime_home = (
        home if home is not None else Path(os.environ.get("LGCW_HOME") or "~/.lgcw")
    ).expanduser()
    defaults: dict[str, Any] = {
        "model": None,
        "builder_effort": "high",
        "reviewer_effort": {"none": "low", "light": "medium", "standard": "high", "deep": "high"},
        "verifier_effort": "low",
        "limits": {},
        "thresholds": {},
    }
    resolved = (
        defaults
        | options
        | {"home": runtime_home, "codex_home": runtime_home / "codex", "repos": repos}
    )
    try:
        return WorkflowConfig.model_validate(resolved)
    except ValidationError as error:
        raise ConfigError(f"{workflow_path}: {error}") from error


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error
