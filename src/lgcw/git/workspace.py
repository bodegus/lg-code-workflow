"""Local per-issue clones with owned leases and independent reviewer workspaces."""

from __future__ import annotations

import re
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import SecretStr

from lgcw.git.port import CommandResult, PushAuth, PushRejectedError, WorkspaceInfo, WorkspacePort
from lgcw.git.run import git, run_process
from lgcw.github.port import TokenProvider
from lgcw.ledger.markers import fingerprint
from lgcw.live import require_live
from lgcw.models.config import RepoConfig
from lgcw.models.issue import IssueRef
from lgcw.runlog import redact


def _sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise ValueError("expected a full commit object ID")
    return value


def _instruction(path: str) -> bool:
    parts = tuple(part.casefold() for part in PurePosixPath(path).parts)
    return any(part in {".agents", ".claude", ".codex"} for part in parts) or (
        parts[-1] in {"agents.md", "agents.override.md", "claude.md"}
    )


class GitWorkspace(WorkspacePort):
    """A single issue's mutable clone; all durable progress remains in GitHub."""

    def __init__(
        self,
        home: Path,
        *,
        origin: Path | None = None,
        token_provider: TokenProvider | None = None,
        allow_live: bool = False,
    ) -> None:
        self._home = home.absolute()
        self._origin = origin.absolute() if origin is not None else None
        self._tokens = token_provider
        self._allow_live = allow_live
        self._info: WorkspaceInfo | None = None
        self._repo: RepoConfig | None = None
        self._issue: IssueRef | None = None
        self._configs: dict[Path, str] = {}

    def _prepared(self) -> WorkspaceInfo:
        if self._info is None:
            raise RuntimeError("workspace has not been prepared")
        return self._info

    def _auth(self) -> dict[str, str]:
        if self._origin is not None:
            return {}
        require_live("GitWorkspace remote", self._allow_live)
        if self._tokens is None:
            raise RuntimeError("GitWorkspace remote needs a token provider")
        return PushAuth(token=SecretStr(self._tokens.token())).env()

    async def _checked(self, cwd: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
        result = await git(*args, cwd=cwd, env=env)
        if result.code:
            raise RuntimeError(f"git {args[0]} failed ({result.code}): {result.err}")
        return result.out.rstrip("\n")

    async def _paths(self, cwd: Path, *args: str) -> tuple[str, ...]:
        return tuple(path for path in (await self._checked(cwd, *args)).split("\0") if path)

    async def _safe_links(self, cwd: Path) -> None:
        paths = await self._paths(
            cwd, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
        )
        for path in paths:
            candidate = cwd / path
            try:
                resolved = candidate.resolve()
            except (OSError, RuntimeError):
                raise ValueError("invalid workspace symlink") from None
            if not resolved.is_relative_to(cwd):
                raise ValueError(f"workspace symlink escapes checkout: {path}")

    async def _trusted_config(
        self, cwd: Path, url: str, repo: RepoConfig, branch: str, *, mirror: bool = False
    ) -> None:
        """Reject config execution/transport knobs and any drift after preparation."""
        directory = cwd if mirror else cwd / ".git"
        if directory.is_symlink() or (directory / "config").is_symlink():
            raise ValueError("unsafe local git config symlink")
        raw = await self._checked(cwd, "config", "--local", "--no-includes", "--null", "--list")
        allowed = {
            "core.repositoryformatversion": {"0"},
            "core.filemode": {"true", "false"},
            "core.bare": {"true" if mirror else "false"},
            "core.logallrefupdates": {"true"},
            "core.ignorecase": {"true", "false"},
            "core.precomposeunicode": {"true", "false"},
            "remote.origin.url": {url},
            "remote.origin.tagopt": {"--no-tags"},
            "remote.origin.fetch": {
                "+refs/*:refs/*" if mirror else "+refs/heads/*:refs/remotes/origin/*"
            },
            "remote.origin.mirror": {"true"} if mirror else set(),
            f"branch.{branch}.remote": {"origin"},
            f"branch.{branch}.merge": {f"refs/heads/{branch}", f"refs/heads/{repo.default_branch}"},
            f"branch.{repo.default_branch}.remote": {"origin"},
            f"branch.{repo.default_branch}.merge": {f"refs/heads/{repo.default_branch}"},
        }
        seen: set[str] = set()
        for row in raw.split("\0"):
            if not row:
                continue
            key, _, value = row.partition("\n")
            if key in seen or value not in allowed.get(key, set()):
                raise ValueError("local git origin/config contains an untrusted key or value")
            seen.add(key)
        snapshot = "\0".join(sorted(raw.split("\0")))
        if cwd in self._configs and self._configs[cwd] != snapshot:
            raise ValueError("local git config changed after preparation")
        self._configs[cwd] = snapshot

    async def _default(self, cwd: Path, url: str, env: Mapping[str, str]) -> str:
        output = await self._checked(cwd, "ls-remote", "--symref", url, "HEAD", env=env)
        return next(
            (
                line.split("\t", 1)[0].removeprefix("ref: refs/heads/")
                for line in output.splitlines()
                if line.startswith("ref: refs/heads/")
            ),
            "",
        )

    async def prepare(self, repo: RepoConfig, issue: IssueRef, branch: str) -> WorkspaceInfo:
        """Resume dirty local state or clone the current default/existing owned remote branch."""
        if (
            issue.repo != repo.full_name
            or branch != f"lgcw/issue-{issue.number}"
            or branch == repo.default_branch
        ):
            raise ValueError("workspace target or owned branch mismatch")
        if self._issue is not None and self._issue != issue:
            raise ValueError("workspace is already bound to another issue")
        auth = self._auth()
        self._home.mkdir(parents=True, exist_ok=True)
        url = (
            str(self._origin)
            if self._origin is not None
            else f"https://github.com/{repo.full_name}.git"
        )
        if await self._default(self._home, url, auth) != repo.default_branch:
            raise ValueError("configured default branch differs from advertised remote HEAD")
        key = repo.full_name.replace("/", "__")
        mirror = self._home / "mirrors" / f"{key}.git"
        run_dir = self._home / "runs" / f"{key}__{issue.number}"
        checkout = run_dir / "repo"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        if mirror.exists():
            if await self._checked(mirror, "remote", "get-url", "origin") != url:
                raise ValueError("mirror origin mismatch")
            await self._trusted_config(mirror, url, repo, branch, mirror=True)
            await self._checked(mirror, "fetch", "--prune", url, "+refs/*:refs/*", env=auth)
        else:
            await self._checked(self._home, "clone", "--mirror", "--", url, str(mirror), env=auth)
        await self._trusted_config(mirror, url, repo, branch, mirror=True)
        base = await self._checked(
            mirror, "rev-parse", "--verify", f"refs/heads/{repo.default_branch}^{{commit}}"
        )
        existing = checkout.exists()
        if existing:
            if await self._checked(checkout, "remote", "get-url", "origin") != url:
                raise ValueError("clone origin mismatch")
            if await self._checked(checkout, "branch", "--show-current") != branch:
                raise ValueError("clone branch mismatch")
            await self._trusted_config(checkout, url, repo, branch)
            await self._checked(
                checkout, "fetch", "--prune", url, "+refs/heads/*:refs/remotes/origin/*", env=auth
            )
            remote = await git(
                "show-ref", "--verify", f"refs/remotes/origin/{branch}", cwd=checkout
            )
            resumed = remote.code == 0
        else:
            await self._checked(
                run_dir, "clone", "--local", "--no-checkout", "--", str(mirror), str(checkout)
            )
            remote = await git(
                "show-ref", "--verify", f"refs/remotes/origin/{branch}", cwd=checkout
            )
            resumed = remote.code == 0
            start = f"refs/remotes/origin/{branch if resumed else repo.default_branch}"
            await self._checked(checkout, "checkout", "-b", branch, start)
            await self._checked(checkout, "remote", "set-url", "origin", url)
        await self._trusted_config(checkout, url, repo, branch)
        base = await self._checked(checkout, "merge-base", _sha(base), "HEAD")
        await self._safe_links(checkout)
        self._repo, self._issue = repo, issue
        self._info = WorkspaceInfo(repo_dir=checkout, branch=branch, base_sha=base, resumed=resumed)
        return self._info

    async def run_commands(
        self, cwd: Path, commands: Sequence[str], timeout_s: float, log_path: Path
    ) -> CommandResult:
        """Run trusted commands sequentially, stopping at the first bounded failure."""
        info = self._prepared()
        if cwd != info.repo_dir:
            raise ValueError("host commands must run in the owned checkout")
        await self._safe_links(cwd)
        started = time.monotonic()
        code, command = 0, ""
        logs: list[str] = []
        for command in commands:
            result = await run_process(("bash", "-lc", command), cwd=cwd, timeout_s=timeout_s)
            logs.append(f"$ {redact(command)}\n{result.out}{result.err}\nexit {result.code}\n")
            code = result.code
            if code:
                break
        content = redact("\n".join(logs))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(content)
        tail = "\n".join(content.splitlines()[-200:]).encode()[-8192:].decode(errors="ignore")
        return CommandResult(
            ok=code == 0,
            command=redact(command),
            code=code,
            tail=tail,
            fingerprint=fingerprint(command, tail) if code else None,
            duration_s=time.monotonic() - started,
            log_path=log_path,
        )

    async def head_sha(self) -> str:
        """Return the clone's committed head, including a commit made before a crash."""
        return await self._checked(self._prepared().repo_dir, "rev-parse", "HEAD")

    async def commit_message(self, sha: str) -> str:
        """Read a committed message without hooks or external programs."""
        return await self._checked(
            self._prepared().repo_dir, "show", "-s", "--format=%B", _sha(sha)
        )

    async def numstat(self, base_sha: str) -> str:
        """Return committed/index/worktree changes plus untracked file counts without staging."""
        cwd = self._prepared().repo_dir
        await self._safe_links(cwd)
        output = await self._checked(cwd, "diff", "--numstat", "-z", _sha(base_sha), "--")
        for path in await self._paths(cwd, "ls-files", "--others", "--exclude-standard", "-z"):
            file = cwd / path
            data = str(file.readlink()).encode() if file.is_symlink() else file.read_bytes()
            count = "-\t-" if b"\0" in data else f"{len(data.splitlines())}\t0"
            output += f"{count}\t{path}\0"
        return output

    async def changed_paths(self, base_sha: str) -> tuple[str, ...]:
        """List all changed paths, including both sides of renames as delete/add paths."""
        cwd = self._prepared().repo_dir
        await self._safe_links(cwd)
        changed = await self._paths(
            cwd, "diff", "--name-only", "--no-renames", "-z", _sha(base_sha), "--"
        )
        untracked = await self._paths(cwd, "ls-files", "--others", "--exclude-standard", "-z")
        return tuple(dict.fromkeys((*changed, *untracked)))

    async def _commit(self, message: str, *, empty: bool = False) -> str:
        cwd = self._prepared().repo_dir
        args = ("--allow-empty",) if empty else ()
        await self._checked(
            cwd,
            "-c",
            "user.name=lgcw",
            "-c",
            "user.email=lgcw@users.noreply.github.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            *args,
            "-m",
            message,
        )
        return await self._checked(cwd, "rev-parse", "HEAD")

    async def commit_all(self, message: str, trailers: Mapping[str, str]) -> str | None:
        """Stage and commit changed files after symlink checks; preserve a clean clone."""
        cwd = self._prepared().repo_dir
        await self._safe_links(cwd)
        if not await self._checked(cwd, "status", "--porcelain", "--untracked-files=all"):
            return None
        if any(
            not re.fullmatch(r"[A-Za-z0-9-]+", key) or "\n" in value or "\r" in value
            for key, value in trailers.items()
        ):
            raise ValueError("invalid commit trailer")
        if trailers:
            message += "\n\n" + "\n".join(f"{key}: {value}" for key, value in trailers.items())
        await self._checked(cwd, "add", "-A", "--")
        return await self._commit(message)

    async def commit_empty(self, message: str) -> str:
        """Create an empty checkpoint, refusing to capture pre-existing staged changes."""
        cwd = self._prepared().repo_dir
        if await self._checked(cwd, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("empty checkpoint requires clean workspace")
        return await self._commit(message, empty=True)

    async def push(self, branch: str, expected_remote_sha: str | None, auth: PushAuth) -> str:
        """Publish only the owned branch with the exact full-ref lease and no lost ancestry."""
        info = self._prepared()
        cwd = info.repo_dir
        if branch != info.branch or self._repo is None or branch == self._repo.default_branch:
            raise PushRejectedError("only the owned non-default branch may be pushed")
        if await self._checked(cwd, "branch", "--show-current") != branch:
            raise PushRejectedError("local branch moved")
        if await self._checked(cwd, "status", "--porcelain", "--untracked-files=all"):
            raise PushRejectedError("dirty workspace cannot be published")
        env = auth.env()
        url = await self._checked(cwd, "remote", "get-url", "origin")
        expected_url = (
            str(self._origin)
            if self._origin is not None
            else f"https://github.com/{self._repo.full_name}.git"
        )
        try:
            await self._trusted_config(cwd, expected_url, self._repo, branch)
        except ValueError as error:
            raise PushRejectedError(f"remote identity/config unsafe: {error}") from error
        if (
            url != expected_url
            or await self._default(cwd, expected_url, env) != self._repo.default_branch
        ):
            raise PushRejectedError("remote identity or default branch changed")
        ref = f"refs/heads/{branch}"
        observed = await self._checked(cwd, "ls-remote", expected_url, ref, env=env)
        remote_sha = observed.split()[0] if observed else None
        if remote_sha != expected_remote_sha:
            raise PushRejectedError("remote head differs from exact expected lease")
        head = await self._checked(cwd, "rev-parse", "HEAD")
        if expected_remote_sha is not None:
            ancestor = await git(
                "merge-base", "--is-ancestor", _sha(expected_remote_sha), head, cwd=cwd
            )
            if ancestor.code:
                raise PushRejectedError("push would discard expected remote history")
        if head != remote_sha:
            result = await git(
                "push",
                f"--force-with-lease={ref}:{expected_remote_sha or ''}",
                expected_url,
                f"HEAD:{ref}",
                cwd=cwd,
                env=env,
            )
            if result.code:
                raise PushRejectedError(result.err)
        return head

    async def diff_text(self, from_sha: str, to_sha: str, max_bytes: int) -> str:
        """Read a redacted committed diff, without external diff drivers, bounded in bytes."""
        output = await self._checked(
            self._prepared().repo_dir,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            _sha(from_sha),
            _sha(to_sha),
            "--",
        )
        return output.encode()[: max(0, max_bytes)].decode(errors="ignore")

    async def adopt_remote_head(self, branch: str) -> str:
        """Adopt a remotely changed owned branch only when the local clone is clean."""
        info = self._prepared()
        if branch != info.branch:
            raise ValueError("cannot adopt an unowned branch")
        if await self._checked(info.repo_dir, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("cannot adopt remote head with dirty local state")
        if self._repo is None:
            raise RuntimeError("workspace target is missing")
        url = (
            str(self._origin) if self._origin else f"https://github.com/{self._repo.full_name}.git"
        )
        await self._trusted_config(info.repo_dir, url, self._repo, branch)
        await self._checked(info.repo_dir, "fetch", url, f"refs/heads/{branch}", env=self._auth())
        head = await self._checked(info.repo_dir, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
        await self._checked(info.repo_dir, "reset", "--hard", head)
        return head

    async def reviewer_checkout(self, head_sha: str, base_sha: str) -> Path:
        """Detach a fresh review clone and replace its instruction surface from trusted base."""
        info = self._prepared()
        checkout = info.repo_dir.parent / f"review-{_sha(head_sha)}-{uuid4().hex[:8]}"
        await self._checked(
            info.repo_dir.parent,
            "clone",
            "--local",
            "--no-checkout",
            "--",
            str(info.repo_dir),
            str(checkout),
        )
        await self._checked(checkout, "checkout", "--detach", head_sha)
        await self._safe_links(checkout)
        head_paths = await self._paths(checkout, "ls-tree", "-r", "--name-only", "-z", head_sha)
        base_paths = await self._paths(
            checkout, "ls-tree", "-r", "--name-only", "-z", _sha(base_sha)
        )
        # Delete instruction roots shallowest first; unlink symlinks instead of following them.
        roots: set[Path] = set()
        for path in head_paths:
            if _instruction(path):
                parts = PurePosixPath(path).parts
                end = next(
                    (
                        i + 1
                        for i, part in enumerate(parts)
                        if part.casefold() in {".agents", ".claude", ".codex"}
                    ),
                    len(parts),
                )
                roots.add(checkout.joinpath(*parts[:end]))
        for root in sorted(roots, key=lambda root: len(root.parts)):
            if root.is_symlink() or root.is_file():
                root.unlink()
            elif root.is_dir():
                shutil.rmtree(root)
        instructions = [path for path in base_paths if _instruction(path)]
        for instruction in instructions:
            for parent in (checkout / instruction).parents:
                if parent == checkout:
                    break
                if parent.is_symlink():
                    raise ValueError("base instruction parent symlink must not be followed")
        if instructions:
            await self._checked(
                checkout, "restore", f"--source={base_sha}", "--worktree", "--", *instructions
            )
        await self._safe_links(checkout)
        return checkout
