"""Real local repositories and synthetic identities for the workspace contract."""

from __future__ import annotations

from pathlib import Path

from lgcw.git.run import git
from lgcw.models.base import Strict
from lgcw.models.config import RepoConfig
from tests.unit.ci.cases import repo

IDENTITY = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.test",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.test",
}


class LocalOrigin(Strict):
    """A local bare origin and its seed checkout."""

    bare: Path
    seed: Path
    base: str


async def checked(cwd: Path, *args: str) -> str:
    """Run real git with an isolated public fixture identity."""
    result = await git(*args, cwd=cwd, env=IDENTITY)
    assert result.code == 0, result.err
    return result.out.strip()


async def origin(root: Path) -> LocalOrigin:
    """Seed a bare main branch with code and trusted agent instructions."""
    bare, seed = root / "origin.git", root / "seed"
    bare.mkdir()
    seed.mkdir()
    await checked(bare, "init", "--bare", "--initial-branch=main")
    await checked(seed, "init", "--initial-branch=main")
    (seed / "AGENTS.md").write_text("Trusted base instructions.\n")
    (seed / "app.py").write_text("VERSION = '0.1.0'\n")
    (seed / ".agents").mkdir()
    (seed / ".agents" / "guide.md").write_text("Trusted skill.\n")
    await checked(seed, "add", "-A")
    await checked(seed, "commit", "-m", "fixture baseline")
    await checked(seed, "remote", "add", "origin", str(bare))
    await checked(seed, "push", "origin", "main")
    return LocalOrigin(bare=bare, seed=seed, base=await checked(seed, "rev-parse", "HEAD"))


def policy() -> RepoConfig:
    """Return a local-only target's trusted default branch."""
    return repo().model_copy(update={"full_name": "fixture/sandbox"})
