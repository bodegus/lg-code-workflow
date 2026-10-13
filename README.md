# lg-code-workflow

A LangGraph workflow that takes a GitHub issue to a **merge-ready pull request**, with plain code for
every step and the OpenAI Codex agent only for building, reviewing and verifying findings. It never
merges. The pull request is the run's record: decisions are PR comments with hidden markers,
findings are review threads, and you steer a run by replying `/lgcw answer …`, `/lgcw retry` or
`/lgcw abort` on the PR.

**Status:** Phase 1 (local, on the owner's Mac), under construction. T0 toolchain, T1 models,
T2 configuration, T3 ledger logic and T4 GitHub port/renderers/fake are implemented. Live adapters,
graph nodes and the functional CLI are still to come. T6 CI qualification, bounded retry policy
and log trimming pass the local gate. T7 review sizing and finding admission also pass locally.
T5's GitHub adapter passes local checks; its live contract is pending a usable issue-enabled
sandbox (the existing OpenClaw fixture disables Issues). See decisions D-021/D-022.
No complete live execution has been qualified yet. See the checked tasks in the plan.

| Read | For |
|---|---|
| [AGENTS.md](AGENTS.md) | rules for anyone (human or agent) working here |
| [docs/design.md](docs/design.md) | how it works |
| [docs/plan.md](docs/plan.md) | what to build next, task by task |
| [docs/decisions.md](docs/decisions.md) | decisions with evidence |
| [docs/research/README.md](docs/research/README.md) | the research behind it (sources in `docs/research/notes/`) |

## Prerequisites (Phase 1)

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- `gh` logged in as the owner (`gh auth status`)
- A **separate** Codex login for the workflow:
  `mkdir -p ~/.lgcw/codex && CODEX_HOME=~/.lgcw/codex codex login`
  (never copy `~/.codex/auth.json`)

## Quickstart (available after plan task T17)

```bash
make setup
uv run lgcw doctor --repo bodegus/family-calendar
uv run lgcw run bodegus/family-calendar#12
uv run lgcw report bodegus/family-calendar#12
```
