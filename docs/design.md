# lg-code-workflow — design

Status: **agreed direction, 2026-10-13** (approach A, PR as the run's record, Phase 1 on the Mac).
Owner: Alex (`bodegus`). Research: [research/README.md](research/README.md). Plan: [plan.md](plan.md).
Decisions with evidence: [decisions.md](decisions.md).

## 1. Goal and scope

Take a GitHub issue to a **merge-ready pull request** with a declarative LangGraph workflow:
plain code for every step, an LLM only inside the agent steps, and hard limits on every loop. It
replaces the "LLM conductor following prose rules" pattern that kept failing on protocol details.

- **In scope:** issue intake, workspace, build, local checks, publish, CI wait and "fix or move
  on", review sized to the change, review-fix loop, mark ready, questions to the owner.
- **Never:** merge, push to a default branch, approve its own PRs, run on issues from other people.
- **Not a framework:** one workflow for coding issues, configured per target repository.

Phases (owner, 2026-10-13):

| Phase | Goal | Exit |
|---|---|---|
| 1a | works end to end on the owner's Mac | live smoke issue on the sandbox repo reaches merge-ready, with a run report |
| 1b | three real runs, logs inspected | simple (version bump), medium (family-calendar feature), complex (memgo-app feature) runs, each with findings; a ranked Phase 2 list |
| 2+ | iterate until the local workflow is durable | §15 exit criteria |
| 3+ | move from the Mac to OpenClaw hosting | §15 |

## 2. Architecture

```text
lgcw CLI ──► graph (LangGraph StateGraph, pure routing, limits)
               │
               ├── ports (Protocols, Pydantic in/out)
               │     GitHubPort ── githubkit (REST + GraphQL), token from `gh auth token`
               │     WorkspacePort ─ plain `git` + the repo's setup/gate commands
               │     HarnessPort ── Codex Python SDK (`openai-codex`), own CODEX_HOME
               │     Clock
               └── policy and content (data, not code)
                     config/workflow.toml, config/repos/<owner>__<repo>.toml
                     step skills (src/lgcw/skills/*/SKILL.md), prompt and comment templates
```

- **Process model (Phase 1).** `lgcw run <owner/repo>#<n>` runs one issue in the foreground until
  it is merge-ready, blocked, or waiting for the owner. Every invocation starts at `reconcile`,
  which reads the issue and PR and decides where to continue. There is no local state that matters:
  losing `~/.lgcw` loses logs, not progress (§3.5).
- **Three layers.** The graph owns order, limits and routing and never calls an LLM. Adapters do
  I/O behind ports. Policy and content (per-repo config, skills, templates) is data.
- **No LangGraph checkpointer in Phase 1** (D-010). The PR is the durable record; LangGraph is used
  for structure, per-node retry/timeout/error handlers and event streaming.
- **Concurrency.** One run per process in Phase 1. Inside a run, reviewer lenses run in parallel
  as separate Codex threads on the same app-server.

Local folders (`LGCW_HOME`, default `~/.lgcw`):

```text
~/.lgcw/codex/                       CODEX_HOME of the workflow's own Codex login (sessions/ live here)
~/.lgcw/mirrors/<owner>__<repo>.git  bare mirror per target repo
~/.lgcw/runs/<owner>__<repo>__<n>/   one folder per issue: repo/ clone, review-<sha>/ checkouts, logs
```

## 3. The PR is the run's record

### 3.1 Markers

Every comment the workflow writes ends with one hidden marker:

```text
<!-- lgcw:v1 {"kind":"push","head_sha":"9f2c…","source":"ci_fix","round":1} -->
```

JSON, compact, one per comment, validated into a Pydantic discriminated union on `kind`. Only
comments authored by the workflow's GitHub login **and** carrying a marker enter the ledger. In
Phase 1 the workflow posts as the owner (D-004), so the marker, not the author, tells workflow
comments from human ones.

| `kind` | Written by | Where | Fields | Meaning |
|---|---|---|---|---|
| `run` | intake, open_pr | issue, then PR | `issue`, `branch`, `base_sha`, `flow_version` | picked up / PR opened |
| `session` | build | PR | `role`, `session_id`, `reason` (`initial`, `fresh_restart`) | builder Codex thread in use |
| `push` | publish, open_pr | PR | `head_sha`, `source` (`initial`, `build`, `gate_fix`, `ci_fix`, `review_fix`, `human`), `round` | workflow-owned head |
| `ci` | ci_wait | PR | `head_sha`, `status`, `klass`, `action`, `fingerprint` | CI verdict and the action taken |
| `review` | review | PR | `head_sha`, `level`, `round`, `lenses`, `blocking`, `nonblocking`, `review_id` | a review round |
| `finding` | review | review thread | `id`, `priority`, `lens`, `head_sha` | one blocking finding |
| `ask` | ask | issue or PR | `seq`, `step`, `code` | a question to the owner |
| `ack` | reconcile | issue or PR | `seq`, `command_id`, `verb` | an owner command was applied |
| `ready` | merge_ready | PR | `head_sha` | merge-ready |
| `blocked` | blocked | PR or issue | `reason` | terminal stop |

Commits also carry trailers (`Lgcw-Issue: owner/repo#n`, `Lgcw-Round: ci_fix-1`) for humans and
`git log`; the ledger does not depend on them.

### 3.2 Where things live

- **Issue:** the `run` pickup comment, and questions while no PR exists (incomplete issue).
- **Draft PR:** opened right after intake, from branch `lgcw/issue-<n>` with an empty commit whose
  message contains `[skip ci]`, so no CI runs on it. GitHub skips `push` and `pull_request`
  workflows when the head commit message contains it (verified,
  [docs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)).
- **PR body:** a view rendered by code from the latest handoff and the ledger: summary, `Fixes #n`,
  decisions, not done and assumptions, tested how, review summary, and a status checklist. Model text
  sits between `<!-- lgcw:handoff:begin -->` and `<!-- lgcw:handoff:end -->`. Capped at 60,000
  characters (GitHub's limit is 65,536).
- **Event comments:** one short comment per decision (§3.1), append-only.
- **Findings:** blocking findings are inline review threads; non-blocking ones are listed once in
  the review body. Dispositions are thread replies plus `resolveReviewThread` with reason
  `ADDRESSED`, `WONT_FIX` or `INVALID`.
- **Labels:** `lgcw:active`, `lgcw:waiting`, `lgcw:merge-ready`, `lgcw:blocked`; review-level
  overrides `lgcw:review-none|light|standard|deep`. The workflow never applies a review-level label
  itself, so any such label is the owner's (in Phase 1 both act as `bodegus`).

### 3.3 Owner commands

A comment whose first line starts with `/lgcw` and that carries no marker, written by a login in the
repo config's `allowed_authors`, after the open question's comment id:

| Command | Effect |
|---|---|
| `/lgcw answer <text>` | continue at the question's step; `<text>` becomes a trusted owner instruction for the next agent turn |
| `/lgcw retry` | continue at the question's step with that step's counter reduced by one |
| `/lgcw abort` | stop: `blocked` marker, `lgcw:blocked` label, draft PR kept |

Each applied command gets an `ack` marker, so it is applied once.

### 3.4 Reconcile

`reconcile` builds a `PrLedger` from issue and PR comments and review threads, then
`next_step(ledger, issue, pr, threads) -> Step` (pure) picks where to continue:

1. PR merged or closed by a human → end (`closed`).
2. `blocked` marker → end. A pending `ask` with no later command → end (`waiting`); with a command →
   apply it (write `ack`) and continue at its step, or `blocked` on abort.
3. `ready` for the current head → end (`merge_ready`).
4. PR head ≠ the last `push` head → `ask` ("head moved"); `/lgcw retry` adopts the new head with a
   `push` marker of source `human`.
5. Otherwise continue from the last completed fact for the current head: no PR → `intake`; only the
   initial push → `build`; a push with no `ci` marker → `ci_wait`; `ci` action `fix` → `build`;
   `ci` success or `proceed_note` with no `review` → `review`; a `review` with open blocking
   threads → `build`; a `review` with none → `merge_ready`.

Counters (fix rounds, reruns, review rounds) are recomputed from the ledger, never stored locally.

### 3.5 Why this is enough to survive crashes

Each node checks for its own marker before acting and writes the marker as part of the same step,
so rerunning `lgcw run` after a crash or kill continues where GitHub says the run is. The
push-then-marker window is closed by checking the remote branch head. A submitted review whose
response was lost is recovered through `list_pr_reviews`, including reviews with no inline
findings; its body carries the round marker in the original submission (D-020). That marker can
have a null review ID until GitHub assigns it; the enclosing review receipt provides the actual
ID without a second event. The builder's Codex thread id is in the `session` marker, so a rerun
resumes the same thread. These are integration requirements, not qualification of the currently
implemented pure ledger; D-019 records the remaining pre-publication persistence gaps.

## 4. Steps

Node names are stable (renaming one is a breaking change). All nodes are `async`.

| Node | LLM | Does | Next |
|---|---|---|---|
| `reconcile` | no | §3.4 | any node, or end |
| `intake` | no | fetch issue; check author, open, acceptance criteria | `open_pr`, `ask` |
| `open_pr` | no | clone, branch, setup commands, empty `[skip ci]` commit, push, draft PR, labels, `run` marker | `build`, `ask` |
| `build` | **yes** | start or resume builder thread; one build or fix turn; check claims in code | `gate`, `ask` |
| `gate` | no | protected-path policy; repo gate commands | `publish`, `build`, `ask` |
| `publish` | no | commit, push with lease, PR body, `push` marker, thread replies and resolutions | `ci_wait` |
| `ci_wait` | no | poll by head SHA, classify, decision table, reruns, trimmed logs | `review`, `build`, `ask` |
| `review` | **yes** | pick level; fresh reviewer per lens; gate findings; verify blocking ones; post review | `merge_ready`, `build`, `ask` |
| `merge_ready` | no | re-check head, conflicts, required checks; mark ready; summary; labels | end |
| `ask` | no | post question (`ask` marker), `lgcw:waiting` | end (`waiting`) |
| `blocked` | no | `blocked` marker, `lgcw:blocked` | end |

Step details:

- **intake.** Reject a closed issue, a pull request, or an issue whose author is not in
  `allowed_authors`. Acceptance criteria: the non-empty section under a heading matching
  `acceptance criteria|done when|definition of done|expected` (case-insensitive), else every
  `- [ ]` checklist item, else incomplete → `ask` on the issue. The issue is snapshotted (title,
  body, `updated_at`); `merge_ready` notes it if the issue changed later.
- **open_pr.** Bare mirror fetch, `git clone --local` per issue, branch `lgcw/issue-<n>` from the
  default branch (or the existing remote branch on rerun). Runs the repo's `setup` commands
  (network on). Pushes the empty commit with lease "branch must not exist", opens the draft PR
  (title = issue title, body starts `Fixes #<n>`), labels `lgcw:active`, writes `run` and `push`
  (source `initial`) markers.
- **build.** See §5. A `blocked` or `partial` handoff with open questions → `ask`. An empty diff
  on `done` counts as a gate failure ("no changes").
- **gate.** Protected paths (config `protected_globs`, default `.github/workflows/**`) changed
  without the issue mentioning them → `ask`. Gate commands run on the host in the clone with a
  timeout; failure → feedback to `build` with the trimmed output (max `gate_fix_rounds`, default
  2). The same failure fingerprint twice → fresh builder once (§6), then `ask`.
- **publish.** `git add -A`, commit (message `lgcw: <first summary line> (#<n>)` plus trailers),
  push with `--force-with-lease=<branch>:<last pushed sha>`, render the PR body, write the `push`
  marker. After a review fix: reply to each finding thread with the builder's disposition and fix
  SHA, then resolve it with the matching reason.
- **ci_wait.** §8. Never waits on a SHA the workflow did not push.
- **review.** §7. Runs only after CI is green or "moved on", so no review is spent on code a CI fix
  is about to change.
- **merge_ready.** GraphQL re-read: head equals the last push, not conflicting, required checks
  green on that head (classifier again). Then `markPullRequestReadyForReview` if still a draft, final
  PR body, a summary comment with the `ready` marker, labels `lgcw:merge-ready` (drop `active`).
  Leaving draft does not start CI on the target repos (their `pull_request` triggers use the
  default activity types).

## 5. Agent steps (Codex harness)

- **One Codex app-server per process** (`openai-codex` `AsyncCodex`), `CODEX_HOME=~/.lgcw/codex`,
  started with an explicit environment: `PATH`, `HOME`, `LANG`, `CODEX_HOME`, nothing else. The
  workflow's login is created once with `CODEX_HOME=~/.lgcw/codex codex login` (D-002).
  `config.toml` there sets `analytics.enabled = false` and `otel.metrics_exporter = "none"`.
- **Sessions:**

| Role | Sandbox | Network | Approval | Effort | Thread |
|---|---|---|---|---|---|
| builder | `workspace_write` (`.git` stays read-only) | **on** in Phase 1 (D-012) | `deny_all` | high | one per issue, resumed (§6) |
| reviewer | `read_only` on a separate checkout | off | `deny_all` | per level (§7) | fresh per lens per round |
| verifier | `read_only` | off | `deny_all` | low | fresh per finding |

  `approval_mode` and `sandbox` are set explicitly on every turn: they are sticky across turns and
  the SDK's default `auto_review` would let another agent approve escalations.
- **Step skills** ship inside the package (`src/lgcw/skills/{build,fix,review,review-security,
  review-tests,verify-finding}/SKILL.md`) and are invoked by exact path, so a same-named skill in
  the target repo cannot shadow them. They describe how to do one step well; they never sequence
  steps or decide limits.
- **Turn input** is one user message rendered from a template: the skill reference, trusted
  instructions, then untrusted text (issue body, CI log, reviewer prose, owner-unrelated comments)
  inside a fence labelled as data. `ExternalMessage` is a Phase 2 option.
- **Outputs** are strict JSON schemas from Pydantic models: `BuildHandoff` (builder),
  `ReviewVerdict` (reviewer, mirroring Codex's review rubric), `FindingCheck` (verifier). An output
  that fails validation gets one retry turn ("your answer did not match the schema"), then `ask`.
- **Limits:** Codex has no turn cap, so each agent node has a LangGraph `TimeoutPolicy`
  (`run_timeout`, `idle_timeout` refreshed by a heartbeat on every Codex event) and the harness
  interrupts the turn on cancel. Defaults: build 3,600 s run / 600 s idle; review 1,200 s / 300 s;
  verify 300 s / 120 s.
- **Errors:** login problems → `ask` ("re-login"); quota or rate limit → `ask` with the reset time;
  timeout → `ask`. Usage per turn (input, cached input, output, reasoning tokens, context window)
  goes to the run log.

## 6. Context plan

- **Reviewer:** always a fresh thread on a checkout of the PR head whose `.agents/`, `.claude/`,
  `AGENTS.md` and `CLAUDE.md` come from the base commit. It never sees the builder's thread.
- **Builder:** one thread per issue (id in the `session` marker), resumed for gate, CI and review
  fixes, with these guardrails:
  1. Every fix prompt restates the acceptance criteria, the open blocking findings (id, priority,
     file:lines, title, required disposition) and the latest failure. Compaction on a ChatGPT login
     keeps only user messages, so nothing may depend on the thread remembering.
  2. **Fresh builder rule** (code): start a new builder thread seeded with a consolidated prompt
     (issue, criteria, latest handoff, open findings, latest failure) when (a) the thread's input
     tokens exceed `context_restart_ratio` (default 0.6) of its context window before a fix round,
     or (b) the same failure fingerprint repeats after a fix, or (c) the thread cannot be resumed.
     Only once per cause; the next repeat goes to `ask`.
- **Handoff:** the builder returns `BuildHandoff` every turn; code renders it into the PR body and
  the reviewer packet. The reviewer gets approach, decisions, assumptions, risks, not-done, file
  reading order and acceptance evidence pointers, but not the builder's summary prose, self-grades
  or test claims (it gets the gate and CI results instead).

## 7. Review levels and finding rules

`pick_level` (pure) uses `git diff --numstat` over base..head (excluding `excluded_globs`: lockfiles,
generated, vendored), the repo's risk-class globs, owner labels and the handoff's `risks`. A human
label wins; nothing an agent writes can lower a level. Thresholds are config (re-fit after about 30
runs).

| Level | When (first match) | Reviewers | Effort | Blocks on | Fix rounds |
|---|---|---|---|---|---|
| deep | any risk class (`ci_supply_chain`, `secrets_auth`, `agent_instructions`, `schema_data`), a new dependency, or ≥ 500 changed lines | 3: `general` (correctness, acceptance), `security`, `tests` | high | P0/P1, plus P2 with category `security` | 2 |
| standard | 100–499 lines, ≥ 8 files, `deploy_ops` paths, or source changed without tests | `general` + `tests` if source changed without tests, `ops` if ops paths | high | P0/P1 | 2 |
| light | any other code change | `general` | medium | P0/P1 with confidence ≥ 0.7 | 1 |
| none | only docs/tests/generated files, CI green, no agent instructions | 0 | — | — | — |

Rules (code): a finding blocks only if it is P0/P1 (P2 security at deep), inside the reviewed lines
and above the level's confidence bar. At standard and deep, each blocking finding first gets a
verifier turn (`FindingCheck`: valid, introduced by the change); only confirmed ones reach the
builder. Everything else is listed once in the review body and never raised again (dedupe by
`finding_id = sha256(path, normalized title, category)[:16]` against existing threads). Re-reviews
cover `last_reviewed_sha..head` plus open threads; a new P0/P1 outside that range is reported to the
owner in the summary, not looped on. The builder answers each blocking finding with `fixed`,
`wont_fix` or `invalid`; the same finding raised again after `wont_fix`/`invalid`, or the round cap,
→ `ask`. A fix delta that touches a new risk class re-runs `pick_level` (it can only rise).

## 8. CI handling

`classify(required, runs, jobs, pr, pushed_sha, pushed_at, now) -> (CiStatus, failing_jobs)` (pure).
Required checks are `(workflow name, job name)` pairs from repo config, unioned with any the
repository's rulesets report. States: `pending` (no checks yet, or required not reported, or running),
`success`, `failure`, `blocked` (cancelled or stale without a timeout annotation), `missing` (nothing
after `ci_start_grace_s`, default 600), `conflict`, `head_moved`, `timeout` (past `ci_deadline_s`,
default 5,400). Poll interval starts at 15 s and doubles to 120 s; a heartbeat each round.

`decide(...) -> CiDecision` (pure), first matching row per failing required job:

| Class | Signal | Action |
|---|---|---|
| superseded | cancelled by a newer run, or run head ≠ PR head | keep waiting |
| awaiting_approval | run `action_required`, no jobs | ask |
| startup_failure | run `startup_failure`, no jobs | builder if the diff touched workflows, else ask |
| infra | runner lost/not acquired, action or image download failure, rate limit, network error in a setup step | rerun once per class per head; again → ask |
| timeout | job `cancelled` with "exceeded the maximum execution time", or a step "has timed out" | rerun if the base job also times out, else builder |
| resources | `ENOSPC`, out of memory, exit 137 in a failed job | rerun once, then builder |
| flaky | failed then passed on the same head, or a known-flaky test id from config | rerun once; pass → proceed and note |
| pre_existing | same workflow, job and failing step fail on the base branch's latest completed push run | proceed and note (ask if the check is required and `pre_existing_policy = "ask"`) |
| mass_failure | ≥ 5 failing jobs | infra rules, else builder |
| change | build, lint or test step fails and the base is green | builder with the trimmed log |
| unclassified | none of the above | builder, flagged |

Caps: reruns ≤ 2 per head and ≤ 5 per PR; CI fix rounds ≤ 3 per PR; the same failure fingerprint
after a fix → fresh builder once, then ask. Trimmed log for the builder: job and step names, exit
code, failure annotations, about 60 lines from the first error match, the last 200 lines of the
failing step, ANSI codes and timestamps stripped, capped at 8 KB per job and 16 KB in total; the full
log is saved to the run folder.

## 9. Data model (Pydantic v2)

All models `extra="forbid"`, frozen unless noted. Output-schema models are strict (all fields
required, nullable where optional). Field lists are in the plan's Interfaces blocks; the main ones:

| Model | Module | Purpose |
|---|---|---|
| `WorkflowConfig`, `RepoConfig`, `Limits`, `RequiredCheck`, `RiskClass`, `ReviewThresholds` | `models/config.py` | configuration |
| `IssueSnapshot`, `IntakeResult` | `models/issue.py` | intake |
| `PrSnapshot`, `PrReview`, `IssueComment`, `ReviewThread`, `ThreadComment`, `ReviewCommentDraft`, `RunView`, `JobView` | `models/github.py` | GitHub records |
| marker union (`RunMarker` … `BlockedMarker`), `LedgerEntry`, `PrLedger`, `Command` | `models/ledger.py` | the PR record |
| `BuildHandoff`, `Decision`, `AcceptanceItem`, `FileNote`, `TestRun`, `Risk`, `Disposition` | `models/handoff.py` | builder output (strict) |
| `ReviewVerdict`, `ReviewFinding`, `CodeLocation`, `LineRange`, `FindingCheck` | `models/review.py` | reviewer and verifier output (strict) |
| `LevelDecision`, `GatedFinding`, `DiffStat`, `FileChange` | `models/review.py` | review policy |
| `CiStatus`, `CiClass`, `CiAction`, `CiDecision`, `CiHistory` | `models/ci.py` | CI policy |
| `SessionSpec`, `SessionRef`, `TurnInput`, `Usage`, `TurnOutcome` | `models/harness.py` | harness port |
| `Feedback`, `RunState` (mutable) | `models/state.py` | graph state |

## 10. Failure handling

| Failure | Handling |
|---|---|
| transient HTTP (5xx, 429, network) | node `RetryPolicy` (max 4, backoff from 2 s) with an explicit `retry_on`; never 4xx or `CalledProcessError` |
| any other exception after retries | default `error_handler` → `ask` with the node name and error class (no traceback in the comment; full traceback in the run log) |
| Codex login, quota, timeout, invalid output | §5 |
| crash or kill mid-run | rerun `lgcw run`; reconcile continues (§3.5) |
| owner pushed to the branch | `ask` ("head moved"); `/lgcw retry` adopts it |
| PR closed or merged by a human | end quietly |
| limits reached | `ask`, with the counter and the latest evidence; `/lgcw retry` grants one more round |
| setup or gate tool missing | `ask` naming the command; `lgcw doctor` checks tools up front |

## 11. Logging and the run report

Inspecting runs is the main output of Phase 1, so every run writes, under
`~/.lgcw/runs/<owner>__<repo>__<n>/`:

- `events.jsonl`: one line per node start/end (duration, attempt), routing decision, side effect
  (comment id, review id, pushed SHA), counter change and error;
- `turns/<seq>-<role>.json`: the rendered prompt, the validated output, usage (input, cached input,
  output, reasoning tokens, context window), duration, Codex session id and rollout file path (the
  full transcript stays in `~/.lgcw/codex/sessions/`);
- `ci/<sha>/`: poll log, full and trimmed job logs; `gate/<round>.log`;
- `github/<seq>-<kind>.md`: every body posted, with ids and URLs;
- `report.md` from `lgcw report <owner/repo>#<n>`: outcome, timeline and time per step, every agent
  turn with tokens (cached separately), rounds per loop, CI actions, findings and dispositions, and
  links to the raw files.

All writes go through `redact()`, which removes token-shaped strings. Nothing is sent to a tracing
service (`LANGSMITH_TRACING=false`).

## 12. Configuration

`config/workflow.toml` (defaults, limits, model and effort) and one file per target repository:

```toml
# config/repos/bodegus__family-calendar.toml
full_name = "bodegus/family-calendar"
default_branch = "main"
allowed_authors = ["bodegus"]
setup = ["npm ci"]
gate = ["npm run check"]
required_checks = [{ workflow = "CI", job = "Node 24.20.0" }, { workflow = "CI", job = "Node 26.8.1" }]
protected_globs = [".github/workflows/**"]
excluded_globs = ["package-lock.json"]
source_globs = ["src/**"]
tests_globs = ["test/**"]
docs_globs = ["**/*.md"]
pre_existing_policy = "note"

[[risk_classes]]
name = "ci_supply_chain"
globs = [".github/**", "Dockerfile", "compose*.yaml", "package.json", ".npmrc"]
```

Job names must be checked against real runs when the file is written (plan task T15).

## 13. Testing strategy

- **Lanes:** `unit` and `live`, exactly one per test (conftest enforces). Unit: no network, no LLM,
  no real tokens; local `git` on temporary repositories is allowed. Live: `LGCW_LIVE=1` only, never
  in CI.
- **Fakes:** `FakeGitHub` (issues, comments, PRs, threads, labels, runs and jobs scripted over
  time, call log, failure injection after the Nth call), `FakeHarness` (scripted outputs per role
  and round, records every prompt, can raise each harness error), `FakeClock`.
- **Pure functions** (markers, ledger, `next_step`, classifier, decision table, log trimming, level
  picker, finding gate, renderers, routers): table-driven tests.
- **Graph tests** run the compiled graph on fakes: happy path; incomplete issue; gate failure then
  fix; CI change failure then fix; pre-existing failure moved on; infra rerun; review with blocking
  finding then fix and resolve; caps reached → ask → `/lgcw retry`; abort; head moved; and a
  **crash test** that injects a failure after every side effect, reruns, and asserts exactly one
  push per round, one PR, one marker per decision.
- **Contract tests** run the same scenarios against `FakeGitHub` (unit) and the sandbox repository
  (live), so the fake cannot drift silently.
- **Coverage** ≥ 90% lines, excluding `harness/codex.py` and `github/client.py` (live lane).
- **CI** (GitHub Actions, ubuntu): `uv sync --locked`, ruff, mypy, unit lane with coverage.

## 14. Security model

Phase 1 runs on the owner's Mac with accepted exposures (D-004, D-012): Codex can read the home
directory (including the `gh` login), and the builder has network access. Still enforced: no token
in the Codex environment, in argv, in `.git/config` or in logs; `.git` read-only for the builder;
reviewers read-only; owner-only commands; untrusted text fenced; hooks disabled for host git
(`-c core.hooksPath=/dev/null`). Phase 2 targets: GitHub App identity, egress allowlist,
Docker sandbox or Codex `exec-server` split, deny-read on `CODEX_HOME`.

## 15. Phase exit criteria

- **1a:** all unit and graph tests green, coverage met; `lgcw doctor` passes; a live smoke issue on
  the sandbox repo reaches merge-ready; its report shows every turn's usage; a kill during the live
  run followed by a rerun does not duplicate any push or comment.
- **1b:** R1 simple (family-calendar `proxy-addr` advisory), R2 medium (family-calendar feature),
  R3 complex (memgo-app feature) each end merge-ready or asking with a clear reason; one findings
  file per run in `docs/runs/`; a ranked Phase 2 list.
- **2 (durable local workflow):** unattended background service resuming active PRs (`lgcw tick`);
  a kill at any step never duplicates a side effect; five consecutive issues without manual repair;
  cost per issue measured; GitHub App identity.
- **3:** packaged image on horse under an OpenClaw cron job, own Codex login and GitHub App on the
  host via home-infra, notifications through OpenClaw.

## 16. Open questions

1. Does the Codex SDK accept a skill reference plus text in one turn input, and an `output_schema`
   on resumed threads? (spike in T7)
2. Cache lifetime and quota accounting of cached tokens on the Pro plan (measure in R1–R3).
3. Live smoke repository: reuse `bodegus/oc2-publish-sandbox` or create a dedicated one (D-014).
4. Should the workflow honour each target repository's own PR template? (Phase 2)
5. Re-fit review thresholds after about 30 runs.
