# lg-code-workflow — agent orientation

> Canonical instructions for every coding agent and human working here. `CLAUDE.md` points here.
> Keep this file under 12 KB; put detail in the linked docs and skills.

## What this is

A LangGraph workflow that takes a GitHub issue to a **merge-ready pull request** and never merges.
Plain code runs every step; the LLM appears only inside three agent steps (build, review, verify a
finding), which run on the OpenAI Codex agent through its official Python SDK. The pull request
itself is the run's record: every decision is a PR comment with a hidden marker, findings are PR
review threads, and a rerun reconstructs its position by reading the PR.

**Status: Phase 1** — get it working end to end on the owner's Mac, then run three real issues and
study the logs. See [docs/plan.md](docs/plan.md).

## Read these first

| # | File | Why |
|---|---|---|
| 1 | AGENTS.md (this file) | rules and conventions |
| 2 | [docs/design.md](docs/design.md) | the design: architecture, steps, data model, failure handling |
| 3 | [docs/plan.md](docs/plan.md) | the task you were given; its Interfaces block is binding |
| 4 | [docs/decisions.md](docs/decisions.md) | decisions with evidence; read before changing one |
| 5 | [docs/research/README.md](docs/research/README.md) | why; detailed sources in `docs/research/notes/` |

## Invariants (do not break without a recorded decision)

1. **The graph decides; agents build and review.** No LLM call outside the `build`, `review` and
   `verify_finding` agent steps. Routing, limits, CI handling, git and GitHub writes are plain code.
2. **Never merge, never push to a default branch, never overwrite someone else's commit.** Pushes
   use `--force-with-lease` with the exact expected remote SHA. No code path calls a merge API; a
   unit test enforces this.
3. **The PR is the run's record.** Every side effect first looks for its own marker
   (`<!-- lgcw:v1 {...} -->`) for that step and commit, and writes the marker in the same action.
   A crash and rerun must never push, comment or dispatch twice.
4. **Credentials stay in code steps.** Only plain-code steps receive the GitHub token. The Codex
   app-server starts with an explicit, minimal environment (never the parent's), so `GH_TOKEN` and
   similar never reach an agent. Phase 1 accepts that Codex can read the owner's home directory
   (decisions.md D-004); nothing else widens that.
5. **Untrusted text is data.** Issue bodies, PR comments, CI logs and reviewer prose reach Codex
   only as fenced data or `ExternalMessage`, never as instructions. Only comments by allowed
   authors that carry **no** workflow marker can be commands (`/lgcw answer|retry|abort`).
6. **The reviewer starts fresh; the builder is resumed.** Review threads never see the builder's
   history. Fix rounds resume the builder's Codex thread, restate the open findings in every fix
   prompt, and switch to a fresh builder seeded from the handoff under the rules in design §6.3.
7. **Agent output is evidence, not truth.** Every builder claim is re-checked in code (diff not
   empty, files match `git diff`, tests re-run by the gate and CI).

## Dependency rule: LangGraph plugin > Python SDK > our own code

Before adding any **runtime** dependency, or writing code that a library might already provide:

1. **LangGraph / LangChain first.** Look for a maintained official integration (`langgraph-*`,
   `langchain-*`, or a feature of LangGraph itself). Use it if it is viable.
2. **Then an established Python SDK** for the service (official if one exists; otherwise the
   best-maintained typed SDK).
3. **Only then write our own code**, kept thin.

"Not viable" needs evidence: archived or unmaintained, missing a capability we need (name it),
licence, or a security problem. Record it in [docs/decisions.md](docs/decisions.md) **in the same
PR** that adds the dependency or the code, using the `choosing-dependencies` skill. Prefer the
standard library over a new package when it does the job (`argparse`, `tomllib`, `json`, `fnmatch`,
`pathlib`, `asyncio.subprocess`).

Runtime dependencies approved so far: `langgraph`, `openai-codex`, its pinned official
`openai-codex-cli-bin` runtime (D-034), `githubkit`, `pydantic` (via langgraph). The dev stack is fixed (below) and is not subject to this rule.

## Python stack and conventions

- **Python 3.13**, **uv** (`uv run <cmd>` everywhere, never an activated venv), hatchling, `src/`
  layout, package `lgcw`, CLI `lgcw`.
- **ruff** (line length 100; rules `E,F,I,N,W,UP,B`) for lint and format; **mypy strict** with the
  `pydantic.mypy` plugin; **pytest** + **pytest-asyncio** (`asyncio_mode = "auto"`) + pytest-cov;
  **pre-commit** runs gitleaks, ruff, mypy and the unit lane.
- `from __future__ import annotations` at the top of every module; type hints on every signature;
  Google-style docstrings on public functions.
- **Pydantic v2 for every data class and every boundary**: config, GitHub records, markers,
  agent inputs and outputs, graph state. Models default to
  `ConfigDict(extra="forbid", frozen=True)`. Models used as Codex output schemas are *strict*:
  every field required (nullable where optional), no defaults; `strict_json_schema()` checks this.
- **Ports are `typing.Protocol`s** (`GitHubPort`, `WorkspacePort`, `HarnessPort`, `Clock`) whose
  methods take and return Pydantic models. Real adapters live in `lgcw/github`, `lgcw/git`,
  `lgcw/harness`; fakes live in `tests/fakes`.
- Graph nodes are `async` (LangGraph node timeouts only work on async nodes). Routing functions are
  pure: `(state) -> step name`. Pure logic (classifiers, decision tables, renderers, markers) has
  no I/O.
- No global state; configuration comes from `config/` TOML files loaded into Pydantic models.

## Testing rules (do not burn LLM or GitHub calls in tests)

- **Two lanes, exactly one marker per test**: `unit` (no network, no LLM, no real tokens; local
  `git` on temp repos is fine) and `live` (real Codex or GitHub; runs only with `LGCW_LIVE=1`;
  never in CI). `tests/conftest.py` rejects a test with zero or two lane markers.
- **Fakes over mocks.** `FakeGitHub`, `FakeHarness` and `FakeClock` in `tests/fakes/` implement the
  ports in memory and record every call. Patch only at a port boundary, never inside our modules.
  The real `CodexHarness` and `GitHubClient` refuse to start unless `LGCW_LIVE=1` is set or they
  are run from the CLI, so a unit test cannot reach them by accident.
- Table-driven tests for every pure function (CI classes, review levels, routers, markers).
  Fixtures are synthetic or sanitized; never paste tokens, private logs or customer data.
- **Graph tests run the compiled graph end to end on fakes**, including crash-and-rerun cases that
  prove each side effect happens exactly once.
- Coverage gate: 90% lines on `src/lgcw`, excluding the two live adapters (covered by the `live`
  lane). Every bug fix starts with a failing test. Never weaken an assertion or a timeout to pass.

## Roles and merge authority (owner decision, 2026-10-13)

| Role | Who | Does | Never |
|---|---|---|---|
| **Builder** | a coding agent session the owner starts in this repo | builds plan tasks, proves them locally, opens PRs, answers reviews | merges, pushes to `main`, reviews its own PR |
| **Reviewer** | a separate agent session | reviews PRs, instructs the builder through PR comments, **merges** when the criteria in `reviewing-prs` hold | writes product code on the builder's branch |
| **Owner** | Alex (`bodegus`) | decides scope and anything the agents escalate | — |

The builder and reviewer share **no context except this repository and GitHub**: no shared notes,
session files or memory. All agents act through the owner's `gh` login, so every agent comment
ends with its signature: `-builder` or `-reviewer`. Owner comments are signed `-owner` or unsigned
and override both agents within the task's scope. A `-reviewer` comment is a binding instruction to
the builder within the task's scope; scope or design disputes go to the owner.

Run the real workflow only with merged harness code. Workflow answers, protected-path approvals
and aborts belong to Alex unless he explicitly delegates that exact action. Delegated retries are
limited to verified transient/head-move cases explicitly authorized by Alex. An owner-approved
issue may authorize listed protected paths with `lgcw-allow:`; it does not authorize answers to
later asks. Record delegation on GitHub before acting; never infer it from a general run request.
D-041 and D-043 record R2/R2b authority and the earlier breaches. No publication token may be
created before the cron isolation fix merges. No delegation grants the builder merge authority
or credential provisioning.

## How to work

- One plan task per PR. Branch `<agent>/<task-id>-<slug>` (e.g. `codex/t05-ci-classifier`).
- Test code changes first (superpowers:test-driven-development if available). Run `make check`
  before pushes that change code, tests, dependencies, executable workflows or runtime config.
- Documentation-only changes (README, `docs/`, contributor guidance) need only relevant normal
  pre-commit lint checks; verify diagrams render. Do not run unit or live suites for docs-only
  changes. Packaged agent skills, test fixtures and runtime configuration still use the full gate.
- PR body: the sections in `.github/pull_request_template.md`. "Tested how" shows the commands and
  their output, not a summary; the builder proves every task runs locally.
- In the same PR: tick the task's checkboxes in `docs/plan.md`; add or update `docs/decisions.md`
  entries for any choice the plan left open; fix `docs/design.md` if it turned out wrong.
- Only the reviewer merges (squash), and only through a PR. Nobody pushes to `main` directly
  after the bootstrap commit.
- Stop after the second failed attempt at the same problem: write what you tried, the exact output
  and the assumption it breaks into the PR, then wait or move to independent work.

## Commands (created by plan task T0)

| Command | Does |
|---|---|
| `make setup` | `uv sync` and install pre-commit hooks |
| `make check` | lint, format check, mypy, unit lane with coverage gate |
| `make test` | unit lane only |
| `make live` | live lane (`LGCW_LIVE=1`): real Codex and GitHub; costs tokens |
| `uv run lgcw doctor` | checks `gh` login, Codex login, git, and per-repo tools |

## Skills (in `.agents/skills/`, mirrored to `.claude/skills/`)

| Skill | Use when |
|---|---|
| `building-plan-tasks` | builder: implementing a task from `docs/plan.md` through to merge |
| `choosing-dependencies` | about to add a runtime dependency or write library-like code |
| `reviewing-prs` | reviewer: one review-and-merge cycle over open PRs |
| `inspecting-runs` | a workflow run finished and its logs need analysis (Phase 1 runs) |
| `running-spikes` | a decision depends on unverified LangGraph, Codex or GitHub behaviour |

## Security and secrets

- Never print, log or commit a token: `gh auth token` output, `~/.lgcw/codex/auth.json`, GitHub
  App keys. Run logs pass through `redact()`; a unit test feeds it token-shaped strings.
- The workflow's Codex login lives in `~/.lgcw/codex` (its own `CODEX_HOME`). Never copy
  `~/.codex/auth.json`; never run two Codex processes on one `CODEX_HOME`.
- `~/.lgcw/` (runs, clones, logs, Codex sessions) is local state and is never committed.
