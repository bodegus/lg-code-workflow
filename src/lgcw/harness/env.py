"""Build the complete allowlisted environment for the owned Codex runtime."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from lgcw.models.config import WorkflowConfig


def build_codex_env(config: WorkflowConfig, base: Mapping[str, str]) -> dict[str, str]:
    """Return exactly four non-credential keys, replacing inherited CODEX_HOME."""
    return {
        "PATH": base.get("PATH") or os.defpath,
        "HOME": base.get("HOME") or str(Path.home()),
        "LANG": base.get("LANG") or "C.UTF-8",
        "CODEX_HOME": str(config.codex_home),
    }
