# lg-code-workflow

A local LangGraph workflow from a GitHub issue to a **merge-ready pull request**. Plain code owns
routing, git, GitHub writes, CI and limits. Codex builds and reviews. It never merges.
The PR is the durable run record; rerunning the same issue reconstructs progress from its markers.

**Phase 1 prototype:** the CLI and none/light review path are implemented and merged. R1 completed
a real dependency bump through green CI, review and merge-ready, including a ci_wait kill/resume.
One verified operator retry was needed before that interruption; see the [R1 evidence](docs/runs/r1-proxy-addr-26.md).
Configured standard/deep reviews execute as one light review under D-037. R2/R3 and hardening remain planned.

| Read | For |
|---|---|
| [AGENTS.md](AGENTS.md) | working rules and role boundaries |
| [docs/design.md](docs/design.md) | architecture and current prototype override |
| [docs/plan.md](docs/plan.md) | task and live-run qualification state |
| [docs/decisions.md](docs/decisions.md) | decisions and evidence |
| [docs/research/README.md](docs/research/README.md) | research |

## Prerequisites

Use Python 3.13 and uv, git, and gh logged in as the configured owner. For family-calendar, put
stable Node >=26.8.0,<26.9.0 and npm >=12.0.2,<13 on PATH for the owner-requested R2 policy.
`doctor` checks these configured bounds. R1 used the earlier Node24/26 matrix policy.
The workflow uses its own Codex login at `~/.lgcw/codex`; never copy the desktop auth file and
never run another Codex process on that home while the workflow is active.

```bash
make setup
LGCW_CODEX_BIN="$(uv run python -c 'from codex_cli_bin import bundled_codex_path; print(bundled_codex_path())')"
CODEX_HOME="$HOME/.lgcw/codex" "$LGCW_CODEX_BIN" login
```

Alex's Mac has a prepared Node26.8.2/npm12.0.2 toolchain under `~/.lgcw/toolchains/`.
Select it for a shell with:

```bash
export PATH="$HOME/.lgcw/toolchains/node-26.8.2-darwin-arm64/bin:$PATH"
```

## Run, inspect and resume

Run from this checkout, or pass `--root /path/to/lg-code-workflow` before the command. Replace N
with an owner-supplied or explicitly delegated issue number. Alex delegated R1 issue creation
and execution; it is [family-calendar#26](https://github.com/bodegus/family-calendar/issues/26).
The next delegated exercise is [family-calendar#28](https://github.com/bodegus/family-calendar/issues/28),
including a weekly GitHub Actions dependency refresh; it requires the R2 Quality/container policy.

```bash
uv run lgcw doctor --repo bodegus/family-calendar
uv run lgcw run bodegus/family-calendar#N
uv run lgcw report bodegus/family-calendar#N
```

Exit codes: 0 merge-ready/success; 2 waiting (including an already-active local run); 3 blocked or
closed; 1 error. A waiting run has a question on its PR or issue. The allowed owner can answer
`/lgcw answer ...`, `/lgcw retry` or `/lgcw abort`; then rerun the same `run` command.
Report regenerates local report.md from evidence and starts no agents or GitHub clients. `LGCW_HOME` selects a different
state directory and dedicated Codex home. Local state is never committed.

## Qualification

`make check` runs the isolated unit lane. `make live` opts into real services; the R1 smoke also
requires explicit issue selection and can spend Codex tokens:

```bash
LGCW_LIVE=1 LGCW_SMOKE_ISSUE=bodegus/family-calendar#N \
  uv run pytest -m live tests/live/test_smoke_e2e.py -s
```

The smoke launches the actual CLI, records its PR facts, kills its verified owned process tree
in ci_wait, and resumes to merge-ready with green required CI. It retains an interruption receipt
and refuses to repeat an uncertain kill. Receipts, usage and the report remain under
`~/.lgcw/runs/bodegus__family-calendar__N/`. A missing issue selection is reported as not run.

For R1, the local gate runs `npm run check`; production audit is qualified by the existing CI
jobs running `npm audit --omit=dev --audit-level=high`, not by that local gate.
