# lg-code-workflow — design

> Phase1 prototype override (D-037; owner decision6159291007): T16 executes none/light reviews,
> maps standard/deep to light with a log, blocks only P0/P1 and marks ready once. Advanced review
> features below are deferred. T17 is run/report/doctor plus family-calendar R1 and kill/resume;
> hardening is prioritized from real logs. Authority, credentials, content and no-merge invariants
> remain unchanged.


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
| `/lgcw retry` | continue at the question's step with one additional round granted for its step/code |
| `/lgcw abort` | stop: `blocked` marker, `lgcw:blocked` label, draft PR kept |

Each applied command gets an `ack` marker, so it is applied once. `LedgerCounts.retry_grants`
joins retry acknowledgements to prior `ask(seq)` facts by step/code; duplicate command IDs do
not grant twice. Activity counts retain the actual number of attempts; consuming nodes compare
those counts with the configured limit plus the corresponding grants.

### 3.4 Reconcile

`reconcile` builds a `PrLedger` from issue/PR comments, review threads and submitted review
bodies. Submitted review facts use their own namespace and require matching author/head/ID
(D-029); a null marker ID is filled from the enclosing receipt. Then
`next_step(ledger, issue, pr, threads) -> Step` (pure) picks where to continue:

1. PR merged or closed by a human → end (`closed`).
2. `blocked` marker → end. A pending `ask` with no later command → end (`waiting`); with a command →
   apply it (write `ack` with frozen command, return step and any exact-head adoption) and continue
   at its step, or `blocked` on abort. An unfinished acknowledgement resumes after a crash;
   `command_done` prevents replay. A newer pending question takes precedence. A continuation
   targeting reconcile completes its command before selecting the next step from fresh facts;
   it never returns directly to the same unfinished acknowledgement.
3. `ready` for the current head → end (`merge_ready`).
4. PR head ≠ the last `push` head → `ask` ("head moved"); `/lgcw retry` adopts the new head with a
   `push` marker of source `human`.
5. An open PR without a push receipt → idempotent `open_pr` recovery, which verifies its initial
   checkpoint before writing missing receipts. Otherwise continue from the last completed fact for the current head: no PR → `intake`; only the
   initial push → `build`; a push with no `ci` marker → `ci_wait`; `ci` action `fix` → `build`;
   `ci` success or `proceed_note` with no `review` → `review`; a `review` with open blocking
   threads → `build`; a `review` with none → `merge_ready`.

Counters (fix rounds, reruns, review rounds) are recomputed from the ledger, never stored locally.

### T13 bootstrap journal refinements

Before a PR exists, authenticated issue comments retain the original intake snapshot/criteria,
bootstrap operation/base and setup intent/result. The initial commit contains its operation ID
and `[skip ci]`; re-entry verifies its message and empty diff before reuse. A run intent containing
its exact initial SHA precedes push. Remote head equality recovers a lost push response; draft
creation includes its run marker atomically. Its issue completion fact links the PR number so a
closed PR remains discoverable. Any-state head-branch lookup also finds a closed/merged PR
before that completion receipt exists, so crash/closure never creates another PR. Identical run
body/comment copies count as one fact.

A setup intent without a measured result asks instead of re-executing. Owner continuation uses a
new setup operation ID. Dirty setup output is preserved and asks. Owner retry adopts only the
head frozen in its acknowledgement: fetch/adopt the clean clone, write a human push marker, then
complete the command before observing CI. Labels repair from observed state after lost responses.
New/superseding questions do not replay older acknowledged continuations. Non-abort PR commands
restore active labels before continuing. A newly generated, lost unpublished checkout gets a new
bootstrap/setup operation and initial commit only while the remote remains absent; changes to an
existing checkout still ask. Setup tails stay local; receipt markers carry only code/fingerprint.
See D-031 and D-033.

### 3.5 Why this is enough to survive crashes

Each node checks for its own marker before acting and writes the marker as part of the same step,
so rerunning `lgcw run` after a crash or kill continues where GitHub says the run is. The
push-then-marker window is closed by checking the remote branch head. A submitted review whose
response was lost is recovered through `list_pr_reviews`, including reviews with no inline
findings; its body carries the round marker in the original submission (D-020). That marker can
have a null review ID until GitHub assigns it; the enclosing review receipt provides the actual
ID without a second event. The builder's Codex thread id is in the `session` marker, so a rerun
resumes the same thread. T14 closes the pre-publication gaps with build/gate/publish intent and completion journals
(D-035). Unknown paid or host-command results ask for an explicit new owner operation rather
than replaying. Builder handoffs and gate receipts bind actual content; publication independently
audits immutable committed bytes before pushing. The PR body carries an atomic operation receipt.
Review/CI integration and real end-to-end qualification remain subsequent tasks.

## 4. Steps

Node names are stable (renaming one is a breaking change). All nodes are `async`. Runtime context
is a frozen Pydantic boundary over runtime-checkable capability Protocols. Plain-code nodes retry
only whitelisted transient errors (four attempts, initial 2 s); build/review have one attempt so a
lost paid-turn response is reconciled before another dispatch. Configured agent run/idle bounds
use explicit heartbeats. A failed ask/blocked writer ends with error instead of recursively asking
(D-028). The caller owns adapter shutdown; run_issue records updates/outcome and writes the report.

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
- **open_pr.** Code-only token provider supplies ephemeral GIT_CONFIG environment authentication
  to private fetches (D-025), never a URL or persisted config. Bare mirror fetch, `git clone --local` per issue, branch `lgcw/issue-<n>` from the
  default branch (or the existing remote branch on rerun). Runs the repo's `setup` commands
  (network on). Pushes the empty commit with lease "branch must not exist", opens the draft PR
  (title = issue title, body starts `Fixes #<n>`), labels `lgcw:active`, writes `run` and `push`
  (source `initial`) markers.
- **build.** See §5. A `blocked` or `partial` handoff with open questions → `ask`. An empty diff
  on `done` counts as a gate failure ("no changes").
- **gate.** Protected paths (config `protected_globs`, default `.github/workflows/**`) changed
  without explicit `lgcw-allow: <path>` lines in the frozen issue → `ask`. Each line names one
  exact relative path in a standalone paragraph outside HTML comments, script/pre blocks and
  Markdown code fences. Line breaks are LF/CR/CRLF only; other Unicode separators are prose. Ordinary mentions,
  denial sentences and hidden text never pre-authorize paths. The question carries exact paths
  and a content fingerprint; only its authenticated `answer approve` acknowledges that proposal.
  Only the latest answered protected-path question counts; a later denial revokes an earlier
  approval even if old bytes return. A later allowed-author command also revokes an already
  acknowledged approval; check after a long gate and immediately before push. Abort is terminal.
  The acknowledgement route must match the question. An approved proposal matching its receipt
  proceeds directly to gate without another paid turn only before any gate result exists. Content changes re-ask (D-035 R2).
  Gate commands run on the host in the clone with a
  timeout; failure → feedback to `build` with the trimmed output (max `gate_fix_rounds`, default
  2). The same failure fingerprint twice → fresh builder once (§6), then `ask`. Before every
  command, including a retry after an unknown result, content must match the builder receipt. Commands must leave identical content;
  zero exit with altered content records blocking feedback. An unknown command result asks.
  Existing gate results consume restored owner commands before routing; repeated graph states or
  GraphRecursionError produce a recoverable node_error ask. Explicit owner retry authorizes a
  new command operation (D-035 R3).
- **publish.** `git add -A`, commit (message `lgcw: <first summary line> (#<n>)` plus trailers),
  push with `--force-with-lease=<branch>:<last pushed sha>`, render the PR body, write the `push`
  marker. Before push, an independent checkout of the immutable candidate must match the gate's
  byte/mode/path fingerprint; changed work or foreign heads ask. Commit trailers and exact remote
  SHA recover lost commit/push responses, and the body has an atomic operation receipt (D-035).
  After a review fix: reply to each finding thread with the builder's disposition and fix
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

  `approval_mode=deny_all` is explicit on every start/resume/turn. The complete role sandbox and
  network policy is set at thread_start for a fresh first turn and thread_resume immediately
  before each later turn. Cached threads retain their immutable role policy; the first resume
  in a new server applies it. SDK 0.162.1's turn-level workspace_write preset resets network=false;
  omit that preset after explicitly configuring the thread (D-034). Never inherit old settings
  across a server restart or use the SDK's default auto_review.
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
  interrupts the turn on cancel and closes its verified owned process tree, because SDK
  interrupt alone can leave a shell running (D-034 R1). Reparented children and rapid fork
  chains can escape the bounded ancestry inventory; workspace quiescence is not guaranteed.
  T14 must re-verify actual content after cancellation before gate/commit and bind the committed
  candidate to its measured gate before push (D-034 R2). Defaults: build 3,600 s run / 600 s idle; review 1,200 s / 300 s;
  verify 300 s / 120 s.
- **Errors:** login problems → `ask` ("re-login"); quota or rate limit → `ask` with the reset time
  when available, otherwise explicitly report reset time unavailable (D-034 R1 deferral);
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
     (issue, criteria, latest handoff, open findings, latest failure) when (a) the latest context input tokens (`Usage.context_input_tokens`, not summed billing)
     exceed `context_restart_ratio` (default 0.6) of its context window before a fix round,
     or (b) the same failure fingerprint repeats after a fix, or (c) the thread cannot be resumed.
     Only once per cause; the next repeat goes to `ask`.
- **Handoff:** the builder returns `BuildHandoff` every turn; code renders it into the PR body and
  the reviewer packet. The reviewer gets approach, decisions, assumptions, risks, not-done, file
  reading order and acceptance evidence pointers, but not the builder's summary prose, self-grades
  or test claims (it gets the gate and CI results instead).

### 6.1 Owner retry grants

The PR question and acknowledged command bind each continuation; retry does not waive all limits.
The exhaustive code table is `graph/retry.py`:

| Ask code | Continuation |
|---|---|
| build_unknown, harness_auth, harness_quota, harness_error, node_error | Resume one explicitly authorized turn; preserve pending failure evidence. |
| handoff_incomplete | Resume with current clarification; owner feedback is not persisted as pending failure evidence. |
| protected_path | Exact bound approval of unchanged builder bytes goes directly to gate; denial or changed bytes cannot use an older approval. |
| gate_fix_limit, no_changes | One additional resumed fix; do not force a competing fresh-restart question. |
| builder_restart_limit | One fresh builder for the acknowledged continuation; not a reusable global waiver. |
| harness_session_lost | One fresh session seeded with the handoff and latest owner answer. |
| workspace_changed | New build on preserved work; after commit, retry instead uses the journaled restoration below. |
| build_evidence_missing | New build with verified input and new receipt. |
| local_head_changed | Owner must inspect/preserve/restore the foreign local commit; never overwrite it automatically. |
| handoff_too_large | Inspect retained local output, narrow or abort; never repeat a paid turn for that known result. |

After a post-commit content question, retry freezes the observed content and restoration target
in the PR. Candidate and dirty tracked work are preserved under local recovery refs. Restore a
candidate matching the gate, or restore its published parent and rebuild a rejected candidate.
Untracked files and foreign commits are refused. Unknown reset responses recover the exact clean
target without resetting again. See D-035 R1.

The selected session's successful handoff history determines prompt kind. Until a session has
completed a validated handoff, retries reuse its original build/restart prompt with the full
issue (and handoff for a restart). A fresh session marker without a dispatch is reused and does
not consume a session-loss grant. Initial-build retries and owner/rebuild continuations remain
source=build; known auth/quota/session-loss errors do not consume gate-fix allowance. Genuine
gate/no-change intents and unknown results remain bounded. Owner answers are reconstructed from
the current authenticated command, never persisted as pending feedback; all prompt kinds apply
the same trusted owner-instruction suffix while keeping any evidence copy fenced.

## 7. Review levels and finding rules

`pick_level` (pure) uses `git diff --numstat` over base..head (excluding `excluded_globs` from line counts, while retaining
excluded paths as risk evidence), the repo's risk-class globs, owner labels and the handoff's `risks`. A human
label chooses the initial level; a previous decision remains a floor on fix deltas. Conflicting
owner labels choose the strongest level. Nothing an agent writes can lower a level. Manifest and lockfile
changes conservatively select deep because numstat cannot prove no dependency was added (D-024; R2-C6). A fully excluded diff never selects `none`. Thresholds are config (re-fit after about 30
runs).

| Level | When (first match) | Reviewers | Effort | Blocks on | Fix rounds |
|---|---|---|---|---|---|
| deep | any risk class (`ci_supply_chain`, `secrets_auth`, `agent_instructions`, `schema_data`), a new dependency, or ≥ 500 changed lines | 3: `general` (correctness, acceptance), `security`, `tests` | high | P0/P1, plus P2 with category `security` | 2 |
| standard | 100–499 lines, ≥ 8 files, `deploy_ops` paths, or source changed without tests | `general` + `tests` if source changed without tests, `ops` if ops paths | high | P0/P1 | 2 |
| light | any other code change | `general` | medium | P0/P1 with confidence ≥ 0.7 | 1 |
| none | only docs/tests/generated files, CI green, no agent instructions | 0 | — | — | — |

Rules (code): a finding blocks only if it is P0/P1 (P2 security at deep), inside the reviewed lines
and above the level's confidence bar (light >= 0.7; standard/deep defer confidence to the
independent verifier). The complete finding range must lie inside one reviewed range; reject
absolute locations outside the checkout and all parent traversal. This gate is lexical and
performs no filesystem reads. At standard and deep, each blocking finding first gets a
verifier turn (`FindingCheck`: valid, introduced by the change); only confirmed ones reach the
builder. Everything else is listed once in the review body and never raised again (dedupe by
`finding_id = sha256(path, normalized title, category)[:16]` against existing threads). Re-reviews
cover `last_reviewed_sha..head` plus open threads; a new P0/P1 outside that range is reported to the
owner in the summary, not looped on. The builder answers each blocking finding with `fixed`,
`wont_fix` or `invalid`; the same finding raised again after `wont_fix`/`invalid`, or the round cap,
→ `ask`. A fix delta that touches a new risk class re-runs `pick_level` (it can only rise).

## 8. CI handling

`classify(required, runs, jobs, pr, pushed_sha, pushed_at, now, limits) -> (CiStatus, failing_jobs)` (pure).
Required checks are `(workflow name, job name)` pairs from repo config, unioned with any the
repository's rulesets and classic branch protection report. The same effective union reaches
both classify and decide. Unknown contexts remain required; an unsupported pinned external
check app asks rather than accepting a same-named Actions job (D-036). States: `pending` (no checks yet, or required not reported, or running),
`success`, `failure`, `blocked` (cancelled or stale without a timeout annotation), `missing` (nothing
after `ci_start_grace_s`, default 600), `conflict`, `head_moved`, `timeout` (past `ci_deadline_s`,
default 5,400). Poll interval starts at 15 s and doubles to 120 s; a heartbeat each round.

`decide(..., *, pushed_sha) -> CiDecision` (pure), first matching row per failing required job.
The exact owned head is required even when no run exists; per-class rerun counts come from the
ledger. Choose the latest run/attempt per workflow and evaluate every required job instance.
Required skipped/neutral checks block; active required workflows remain pending. The deadline
bounds waiting, while completed current-head results remain authoritative after it. Aggregate
job actions by ask > fix > rerun > wait > proceed-note, so one pre-existing failure cannot conceal
an introduced failure (D-023).


| Class | Signal | Action |
|---|---|---|
| superseded | cancelled by a newer run, or run head ≠ PR head | keep waiting |
| awaiting_approval | run `action_required`, no jobs | ask |
| startup_failure | run `startup_failure`, no jobs | builder if the diff touched workflows, else ask |
| infra | GitHub step number 1 named Set up job fails; runner lost or cancellation before any user step starts; job startup conclusion | at most one combined infra/resources/flaky rerun per head; another failure → builder |
| timeout | job `cancelled` with "exceeded the maximum execution time", or a step "has timed out" | rerun if the base job also times out, else builder |
| resources | resource signal during the GitHub setup phase or before user steps start | shares the one transient rerun; another failure → builder |
| flaky | exact known-flaky pytest FAILED identifiers, matching summary failed count and no error lines | shares the one transient rerun; pass → proceed and note; another failure → builder |
| pre_existing | same workflow, job and failing step fail on the base branch's latest completed push run | proceed and note (ask if the check is required and `pre_existing_policy = "ask"`) |
| mass_failure | ≥ 5 failing jobs | infra rules, else builder |
| change | build, lint or test step fails and the base is green | builder with the trimmed log |
| unclassified | none of the above | builder, flagged |

Caps: infra/resources/flaky share at most one rerun per head, with another failure routed to
the builder even if its class changes. Absolute rerun limits remain ≤ 2 per head and ≤ 5 per PR; CI fix rounds ≤ 3 per PR; the same failure fingerprint
after a fix → fresh builder once, then ask. Trimmed log for the builder: job and step names, exit
code, failure annotations, about 60 lines from the first error match, the last 200 lines of the
failing step, ANSI codes and timestamps stripped, capped at 8 KB per job and 16 KB in total; the full
log is saved to the run folder.

Rerun requests have an exact head/run/from-attempt intent and acceptance receipt. A missing
receipt is recovered only by a newer observed attempt; otherwise the durable grace/deadline
ends in an owner question, never another automatic dispatch. CI markers include attempt identity.
Failure feedback is retained before the fix decision, selected failing job first, within the
8 KB/job and 16 KB aggregate bounds; omitted failures retain a bounded identity summary.
Every failing log is attempted, with metadata fallback for 404/409/410. Annotation paths and
check-run output never establish service provenance. GitHub's exact numbered setup step and
complete step metadata distinguish service-phase failures from arbitrary user-named steps.
Network prose in a user step does not grant a rerun; the builder receives it as failure evidence.
Same-named jobs cannot hide a blocked workflow; until policy names identify their workflow,
unresolved/blocked workflows remain conservatively required, including an optional startup
failure (D-036 R2). Runs must belong to this repository, PR branch and push/pull_request event;
a PR event must have exactly this PR and matching base.ref. Multiple associated PRs or another
open PR sharing the branch ask ci_ownership_ambiguous. Re-read identity/attempt/conclusion,
PR/remote head and unique ownership before intent and again before dispatch. A recorded
rerun decision without intent resumes only its exact observed attempt. Evidence removes terminal
controls with line- and length-bounded sequences, limits annotations to 2 KiB/job and measures
escaped markers. Downloads above 8 MiB, more than 100 owned runs after filtering or 200 jobs
ask rather than evaluating partial evidence. Base comparison queries that workflow path's latest
completed push run directly; an absent base run is empty baseline. Classic protection 404 requires
an explicit disabled classic-protection state or enforcement off with empty checks/contexts,
after a complete ruleset read; protected alone is ambiguous because rulesets also set it.
Missing/enforced classic policy and unsupported workflows, required_deployments, code_scanning
or merge_queue rules ask. See D-036 R1 and superseding R2 corrections.

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

The log trimmer strips an initial UTF-8 BOM and treats a step section as everything from
`##[group]` to the next `##[group]`. `##[endgroup]` ends the command-echo wrapper, not the
step output. If the named section has no error, retain the first section containing an error.
CI decisions use required workflows only, ignore cancelled/skipped/neutral consequences within
a genuinely failed run, and compare against the latest completed base run/attempt per workflow.
Blocked CI never dispatches a builder fix.

## 10. Failure handling

| Failure | Handling |
|---|---|
| transient HTTP (5xx, network) | node `RetryPolicy` (max 4, backoff from 2 s) with an explicit `retry_on`; never 4xx (including 429) or `CalledProcessError`; paid agent dispatch is single-attempt |
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

All writes redact credential-shaped strings. Structured JSON redacts each value before
serialization, so header redaction cannot consume neighboring fields. RunLog.write_report saves
the semantically redacted derived view atomically without a second regex pass. Raw artifacts/turns
cannot overwrite different evidence; report.md can be regenerated. Report reads stay inside the
run folder, unknown usage remains unknown, and a later invocation without run_end is incomplete
rather than inheriting an earlier completed outcome (D-027). Nothing is sent to a tracing
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
reviewers read-only on independent detached clones with base instruction overlays; checkout
symlink escapes and instruction-parent aliases are rejected; owner-only commands; untrusted text fenced; hooks disabled for host git
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
