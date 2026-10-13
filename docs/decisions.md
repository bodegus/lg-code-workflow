# Decisions

One entry per decision: what was chosen, the alternatives, the evidence, and what would make us
revisit it. Append new entries; never rewrite an old one (add "Superseded by D-nnn" instead).
Dependency decisions follow the rule in [AGENTS.md](../AGENTS.md): LangGraph plugin > Python SDK >
our own code. Research references point into [research/](research/).

## D-001 LangGraph runs the flow; Codex does the build and review work (approach A)

- **Decided:** Alex, 2026-10-13. A LangGraph `StateGraph` with plain-code steps and pure routing;
  the LLM only inside the build, review and verify-finding agent steps.
- **Alternatives:** (B) everything inside LangGraph with Deep Agents sub-graphs; (C) a thin wrapper
  around `codex exec`.
- **Evidence:** research §3, §5, §9: no mature open-source LangGraph issue-to-PR pipeline exists;
  production designs keep the process deterministic (GitLab Duo flows, Codex two-job autofix,
  gh-aw safe outputs); B's ChatGPT-login path is unofficial; C cannot combine `resume` with
  `--output-schema` (openai/codex#14343).
- **Revisit when:** Phase 1 logs show Codex's own loop is the weak point (then trial B behind the
  same `HarnessPort`).

## D-002 Harness: the official Codex Python SDK on a dedicated login

- **Decided:** 2026-10-13. `openai-codex` (pinned; it pins the CLI binary), one app-server per
  process, `CODEX_HOME=~/.lgcw/codex` created by its own `codex login`.
- **Plugin check (step 1):** LangChain/Deep Agents with LangChain's private `_ChatOpenAICodex`
  ChatGPT-login model — not viable: underscore-private, labelled experimental and unofficial,
  calls an undocumented endpoint (research notes 02 §1.8). `codex mcp-server` + LangChain MCP
  adapters — removed (openai/codex#42993, 2026-09-05) and archived.
- **SDK (step 2):** `openai-codex` 0.162.1, Production/Stable on PyPI, typed threads, `output_schema`,
  `thread_resume`, `thread_fork`, read-only sandbox, `deny_all` approvals (research §5).
- **Evidence on auth policy:** ChatGPT-managed Codex auth is documented for trusted private
  automation; one `auth.json` per process chain (research §6).
- **Revisit when:** the SDK breaks on an upgrade, or OpenAI changes plan-usage terms; fallback is
  the same harness on an API key (configuration only).

## D-003 The PR is the run's record

- **Decided:** Alex, 2026-10-13 ("use GitHub PR comments as a way to track state — comment id,
  commit hash — to lean out the workflow").
- **What:** markers in workflow comments, findings as review threads, owner commands as PR
  comments, reconcile-from-PR on every run (design §3).
- **Alternatives:** a local SQLite checkpointer and ledger with LangGraph `interrupt()` for
  questions; a separate answer-polling service.
- **Evidence:** Copilot's coding agent opens a draft PR on an empty commit and keeps progress in the
  PR; Claude Code Action keeps one tracking comment; Open SWE and CodeRabbit use hidden markers,
  `last_reviewed_sha` and thread resolution (research notes 07 §B.4). LangGraph's own crash-resume is
  not exactly-once (langchain-ai/langgraph#8039), so check-before-act was needed anyway.
- **Revisit when:** API rate limits or comment noise become a problem in Phase 1 runs.

## D-004 Phase 1 identity: the owner's `gh` login

- **Decided:** Alex, 2026-10-13 ("a for now, I want to move quickly").
- **Consequences:** PRs and comments appear as `bodegus`; markers, not authorship, identify
  workflow comments; commands are accepted only from comments without a marker. Reviews are posted
  as `COMMENT` (GitHub does not let authors approve or request changes on their own PRs). Codex can
  read the home directory, including the `gh` login (accepted for the local test).
- **Revisit when:** Phase 2 (GitHub App `lg-code-workflow[bot]`, repo-scoped tokens, `checks:read`).

## D-005 Reviewer fresh, builder resumed, with guardrails

- **Decided:** Alex, 2026-10-13 (reviewer never starts from the builder's context; CI and review
  fixes keep the builder's context). Guardrails added from research: restate open findings in every
  fix prompt; fresh builder from the handoff on 60% context, a repeated failure, or a lost thread.
- **Evidence:** Codex's own `/review` runs with empty history; ChatGPT-login compaction keeps only
  user messages; cache lifetime is about 30 minutes; debugging effectiveness drops after two or
  three attempts (research §8.2).

## D-006 Review levels and finding rules

- **Decided:** 2026-10-13, as proposed in research §8.1 / design §7 (none, light, standard, deep;
  block only P0/P1 inside the change; verify blocking findings; interdiff re-review; caps).
- **Revisit when:** after about 30 runs, re-fit thresholds on findings per level and escaped
  defects.

## D-007 CI "fix or move on" table

- **Decided:** 2026-10-13, design §8 (11 classes, rerun caps 2 per head / 5 per PR, 3 CI fix
  rounds).
- **Evidence:** CI platforms classify failures deterministically (Chromium "fails without patch",
  GitLab `retry:when`, OpenShift retester caps); a job timeout ends `cancelled` with an annotation
  (research §8.4).

## D-008 GitHub access: githubkit

- **Plugin check (step 1):** LangChain's GitHub toolkit (`GitHubAPIWrapper` in
  `langchain-community`) — not viable: `langchain-ai/langchain-community` is archived (2026-06-19);
  it requires GitHub App credentials (`GITHUB_APP_ID`); its methods are string-in/string-out agent
  tools; it has no check runs, job logs, review threads, thread resolution or GraphQL
  ready-for-review (checked 2026-10-13, `libs/community/langchain_community/utilities/github.py`).
- **SDK (step 2):** GitHub has no official Python SDK. `githubkit` 0.16.1 (MIT): async, typed,
  REST and GraphQL in one client, repo-scoped App tokens; Open SWE pins it. PyGithub: sync only,
  LGPL, cannot scope App tokens to a repository (research notes 03 §2.1).
- **Decided:** githubkit. Token from `gh auth token` in Phase 1.

## D-009 git: a thin wrapper over the `git` command line

- **Plugin check:** no LangGraph or LangChain git integration exists.
- **SDK check:** GitPython is in maintenance mode and itself shells out to `git`; pygit2 (libgit2)
  lags git features and adds GPL-with-exception licensing (research notes 03 §3.1).
- **Decided:** our own thin async wrapper over `git` (`asyncio.create_subprocess_exec`, explicit
  argv, hooks disabled, per-call timeout).

## D-010 No LangGraph checkpointer in Phase 1

- **Decided:** 2026-10-13, consequence of D-003: GitHub holds progress; local state is logs only.
- **If needed later:** `langgraph-checkpoint-sqlite` (a LangGraph plugin, step 1 of the rule) with
  `durability="sync"`.

## D-011 Standard library for CLI, config, globbing and logs

- **Decided:** `argparse` (CLI), `tomllib` + Pydantic (config), `pathlib.PurePath.full_match`
  (risk globs, Python 3.13), `json` (event log). No click/typer, no pydantic-settings, no
  structlog. Revisit only with a concrete capability gap.

## D-012 Builder network on in Phase 1

- **Decided:** 2026-10-13 (proposed; not objected to). Needed for dependency changes such as the
  R1 version bump. Phase 2 narrows egress to package registries.

## D-013 Python stack

- **Decided:** Alex's standard stack, as in `bodegus/memgo-app`: Python 3.13, uv + hatchling, ruff
  (100), mypy strict with the pydantic plugin, pytest + pytest-asyncio + pytest-cov, pre-commit with
  gitleaks; one lane marker per test.

## D-014 Live smoke repository (proposal, owner to confirm)

- **Proposed:** `bodegus/oc2-publish-sandbox` (small Python + npm project with CI), using branches
  `lgcw/issue-*` that do not collide with openclaw2-deploy's `openclaw/*` test branches.
- **Alternative:** a dedicated `bodegus/lgcw-sandbox`, created by the owner.

## D-015 Separate builder and reviewer agents; the reviewer merges

- **Decided:** Alex, 2026-10-13 ("I am concerned about context leakage — I want you to be the
  reviewer but another agent to be the builder; they follow your instructions via PR comments; you
  review/merge; the other agent builds and proves it runs locally").
- **What:** roles, signatures (`-builder`, `-reviewer`, `-owner`) and merge criteria in AGENTS.md
  and the `building-plan-tasks` / `reviewing-prs` skills. The two agents share only the repository
  and GitHub. The reviewer merges with `--squash` after its criteria hold; nobody pushes to `main`.
- **Pattern source:** the openclaw2-deploy `backlog-builder` / `backlog-monitor` protocol (one
  review comment per head SHA with a findings ledger; one ledger reply per review).
- **Revisit when:** a GitHub App gives the agents distinct identities (Phase 2), so signatures are
  no longer the only way to tell them apart.

## D-016 T0 toolchain: locked environments and pinned CI actions

- **Decided:** 2026-10-13, T0 builder. Use only the runtime dependencies already approved in
  D-002, D-008 and D-013 at the plan's constraints, resolved in `uv.lock`; no additional runtime
  dependency. Local hooks use the same uv environment for mypy and the unit lane.
- **CI:** `actions/checkout` v7.0.1 and `astral-sh/setup-uv` v10.3.0 are pinned to their commit
  SHAs, verified through GitHub's commits API. Permissions are `contents: read`, checkout does
  not persist credentials, and CI uses `uv sync --locked` then `make check` on Python 3.13.
- **Evidence:** T0's PR records the failing-first run, dependency sync, local checks and hooks.
  Lane collection tests use pytest's bundled `pytester` plugin, not mocks or new dependencies;
  the opt-in test runs only a synthetic live-marked function and contacts no real service.
- **Not implemented yet:** the `lgcw` entry point is declared as specified in the plan; its CLI
  module and functional commands belong to T17, so T0 does not claim `lgcw doctor` works.
- **Revisit when:** a dependency or action upgrade requires a different Python/runtime version,
  or the actual T17 CLI needs a different entry point.

## D-017 T1 model boundaries and output-schema validation

- **Decided:** 2026-10-13, T1 builder. All boundary models inherit Pydantic `Strict` with
  `extra="forbid", frozen=True`; only graph state permits reassignment, with assignment validation.
  Agent outputs require every field, including nullable ones, and have no defaults.
- **Schema checker:** validate Pydantic's generated schema recursively through definitions,
  properties, compositions, arrays and conditional schema nodes. Required nullable fields are
  valid; defaults and objects that permit extra properties are rejected. A field named `default`
  is valid when it does not supply a schema default.
- **Shared names:** `Step` is defined alongside `Strict` in `models/base.py` and re-exported from
  its binding module `models/state.py`, so ledger question markers and state use the same type
  without a state/ledger import cycle. No public binding name in the plan changes.
- **Review with no lenses:** `ReviewMarker.review_id` is required but nullable, so the `none`
  review level can record a round without inventing a GitHub review ID.
- **Limits:** explicit run/idle timeout fields per role use the design's exact defaults;
  round caps and counts cannot be negative, and context-restart ratio must be in (0, 1].
  One-based ordered line ranges and bounded priorities/confidences reject malformed findings.
- **Dependency check:** no added packages; only already-approved Pydantic and standard-library
  typing, datetime, pathlib and asyncio. Ledger methods and counters remain T3; configuration
  loading and repository lookup remain T2. Live adapters and workflow execution remain unbuilt.
- **Evidence:** T1's initial imports fail as expected; its model tests exercise strict schemas,
  validation, marker discrimination, round trips, mutable state, diff accounting and both clocks.
  Final full-gate proof will be recorded in this PR before T1 is marked complete.
- **Revisit when:** a pinned SDK rejects these schemas or later task integration demonstrates
  a missing boundary field; record any interface change before dependent tasks consume it.

## D-018 T2 trusted TOML loading and sandbox CI identity

- **Decided:** 2026-10-13, T2 builder. Use `tomllib` and Pydantic validation as approved in D-011;
  no added package. Unknown options, malformed files and filename/full_name mismatches fail as
  `ConfigError`. Unconfigured target lookup raises `UnknownRepoError` (defined with the models
  and re-exported from `lgcw.config`).
- **Runtime paths:** explicit `home` wins over `LGCW_HOME`, then `~/.lgcw`; derive `codex_home`
  as `home/codex`. TOML cannot override these managed paths or the discovered repository map.
  Per-field limits retain the T1 defaults when omitted. No directory, clone or login is created
  by loading configuration.
- **Sandbox required check:** `CI / test`, read from `.github/workflows/ci.yml` at
  `bodegus/oc2-publish-sandbox` main `01162f9cc2d7de1f09cdadb750c22b618b7e0f99`.
  That workflow currently runs PR jobs only on `openclaw/*`, or on manual dispatch; therefore
  `lgcw/issue-*` PRs are skipped. This configuration records the real name without qualifying
  live acceptance. Sandbox preparation or a different approved fixture remains required.
- **Evidence:** T2's PR records the missing-module failure, 16 configuration tests, and the
  full `make check` result (73 tests, 100% current-package line coverage). The sandbox config
  intentionally has empty setup/gate commands as the task specifies; CI is still mandatory.
- **Revisit when:** a target's workflow or job names change, or sandbox preparation removes its
  branch guard. Re-read actual target CI before a live run; do not classify skipped checks green.

## D-019 T3 durable-record parsing and counter semantics

- **Decided:** 2026-10-13, T3 builder. Use the plan's compact JSON wire format and escape every
  `--` in JSON data as a hyphen plus `\u002d`, preventing data from closing its HTML comment.
  Parse v1 blocks with the prescribed regex and Pydantic discriminated union; malformed and
  unknown records are ignored. No dependency beyond approved Pydantic and standard-library
  json, re and hashlib.
- **Identity and commands:** only exact workflow-login authorship admits ledger facts; only
  configured author logins admit commands after the question ID. Any workflow-marker prefix,
  including malformed/unknown markers, excludes a comment from owner commands. Parse commands
  only on the first nonempty line; preserve multiline answer content.
- **Ordering:** issue/PR facts retain service timestamps. The binding `ThreadComment` has no
  timestamp, so finding-thread facts use UTC minimum as an explicit unknown-time sentinel,
  ordered by comment ID. That sentinel is not evidence of when a finding occurred.
- **Counts:** fix counts reflect published `push` source markers, reruns reflect `ci` actions,
  review rounds reflect review markers, and fresh restarts reflect session markers. No local
  counter is persisted. Questions are pending only without a later matching acknowledgement.
- **Integration limit to resolve before T12/T14:** these current markers do not record
  pre-publication gate-fix attempts or a complete recoverable handoff. Their persistence and
  crash behavior need explicit integration facts/tests before claiming restart qualification.
  T3 proves pure reconstruction from supplied records, not the unbuilt graph's crash recovery.
- **Evidence:** initial three missing-module errors; full gate passes with 103 unit tests and
  100% current-package line coverage. PR proof includes the actual commands and output.
- **Revisit when:** integration needs additional durable facts, or review-thread timestamp data
  is added to the binding GitHub record model.

## D-020 T4 review receipts must be readable independently of inline threads

- **Evidence:** design §3.5 closes a review-post crash window by reading the review whose body
  carries the marker. The original T4 port could create a review and list inline threads, but
  could not list submitted review bodies. A COMMENT review with zero inline findings creates
  no thread that could carry the review-round fact. The failing T4 regression demonstrates the
  missing `list_pr_reviews` capability. GitHub exposes reviews separately from issue comments:
  [review listing](https://docs.github.com/en/rest/pulls/reviews#list-reviews-for-a-pull-request),
  [issue comment listing](https://docs.github.com/en/rest/issues/comments#list-issue-comments).
- **Decided:** 2026-10-13, T4 builder. Add `PrReview(id, author, body, head_sha, submitted_at)`
  and `GitHubPort.list_pr_reviews(repo, number) -> list[PrReview]`, with matching fake and real
  adapters. Keep native review records separate from conversation comments; reconciliation will
  ingest their markers using their authoritative submission timestamps. T5's shared contract
  checks review-body readback as well as inline threads.
- **Atomic marker identity:** a marker placed inside a review body can use a null `review_id`
  at submission, because GitHub assigns the ID afterward. Recovery uses the enclosing
  `PrReview.id`; it must not post a second event merely to recover that identity. T16/T12 will
  prove the post-before-return crash case. All existing binding fields remain supported.
- **Rendering:** package template strings are immutable constants loaded once at import;
  render functions perform no I/O. Untrusted text cannot introduce HTML comments, including a
  forged workflow marker or handoff delimiter. Truncation preserves handoff boundaries and
  code-produced status, with the whole PR body capped at 60,000 characters.
- **Fake:** each port call is recorded; failure injection occurs after a successful operation's
  effect and fires once. Run/job snapshots are scheduled by fake-clock offsets. The three
  shared contract scenarios are unit-tested here and must run live in T5 before adapter claims.
- **Dependency check:** the read operation belongs on the already-approved githubkit adapter;
  rendering uses standard-library string.Template/importlib.resources. No added dependency.
- **Revisit when:** GitHub changes review listing or the graph requires another durable fact;
  do not claim crash qualification from this fake-only readiness work.

## D-021 T5 live boundaries, SDK retry ownership and forward redaction dependency

- **Decided:** 2026-10-13, T5 builder. Keep all service calls on the already-approved githubkit
  0.16.1 SDK. Its installed constructor defaults `auto_retry=True`; explicitly disable that
  and HTTP caching so nodes own recovery and reads re-observe GitHub. Use the SDK's current
  REST Link-header paginator and GraphQL cursor paginator, rather than writing a paginator.
- **Credentials:** the live guard runs before credential access. `GhCliTokenProvider` captures
  `gh auth token` only inside code, caches it for 50 minutes, and emits a safe login instruction
  on failure without including captured output. The SDK receives the token in memory, never in
  argv or a log. The adapter refreshes its SDK auth from the provider at operation boundaries.
- **Write pacing:** serialize mutations and wait one second after the previous mutation finishes,
  including failures. Disable SDK retries for mutations as well as reads; do not blindly repeat
  a failed POST inside the adapter.
- **Forward dependency:** T5's required token test consumes `redact`, originally scheduled in
  T11. Implement only the pure `lgcw.runlog.redact` helper and its pattern tests now; leave the
  run log/report in T11. Standard-library regex is sufficient (D-011); no added package.
- **Intake boundary:** add `IssueSnapshot.is_pull_request: bool = False` and map the REST
  `pull_request` field. The planned intake rejection otherwise had no typed evidence with which
  to distinguish a PR returned by the issue endpoint. Existing snapshot fields remain supported.
- **GraphQL verification:** live schema introspection on 2026-10-13 confirms
  `ResolveReviewThreadInput.resolutionReason` accepts ADDRESSED, WONT_FIX and INVALID, and review
  comments expose `fullDatabaseId` (the old `databaseId` field is absent). Use full IDs without
  32-bit truncation. This was a read-only schema check, not a submitted review qualification.
- **Revisit when:** the pinned SDK or GitHub schema changes; re-run the live contract and actual
  graph acceptance before claiming equivalent behavior.

## D-022 Live fixture choice pending: existing sandbox cannot host issue intake

- **Observed:** T5's first live attempt failed with HTTP 410 at issue creation. A subsequent
  read confirmed `bodegus/oc2-publish-sandbox.has_issues = false`. No issue or PR was created;
  the unique temporary branch was deleted and a separate GET confirmed HTTP 404. Main remained
  at `01162f9cc2d7de1f09cdadb750c22b618b7e0f99`. The non-secret receipt and failure transcript
  are retained locally and summarized on the PR; the failed attempt is not live qualification.
- **Existing CI:** its current workflow additionally skips `lgcw/*` branches and documents an
  intentionally failing baseline for OpenClaw tasks (D-018). Preserve that fixture's purpose;
  do not turn skipped checks into success or change its settings without the owner's choice.
- **Proposal awaiting owner:** create private `bodegus/lgcw-sandbox` from the reviewable files in
  `tests/fixtures/live_sandbox/` (strip `.txt` from each filename when seeding). It has Issues,
  `CI / test` on every PR, a small addition CLI and canonical `VERSION` release metadata.
  A patch bump changes only VERSION; existing tests still verify arithmetic and the CLI's
  reported release without weakening assertions. No repository has been created or modified
  by this proposal. Owner may instead enable Issues on the existing sandbox, with separate CI
  preparation still required before a complete workflow run.
- **Local fixture proof:** copied the exact proposed files into a fresh temporary directory:
  `uv run --python 3.13 --with pytest==9.1.1 python -m pytest -q tests` → `5 passed in 0.05s`.
  This proves the local fixture baseline only, not GitHub CI or the lgcw workflow.
- **Scope:** T5's local gate passes (146 unit tests, 99.73% current-package coverage); its live
  qualification remains pending. Continue independent work while the fixture and dedicated
  Codex login prerequisites await the owner. Update this decision with the actual choice and
  live receipts before marking the live task complete.

## D-023 T6 CI decisions require exact-head and rerun-class evidence

- **Decided:** 2026-10-13, T6 builder. Add required keyword `pushed_sha` to `decide`: a missing
  run cannot supply the SHA for its own decision, and guessing an empty or foreign SHA would
  corrupt the durable record. Add optional `CiHistory.reruns_by_class_head`, reconstructed from
  CI markers, to enforce the table's per-class caps. Unknown prior class consumption cannot
  authorize another automatic rerun. Existing history fields remain supported.
- **Run ordering:** add optional `RunView.created_at`, mapped from the service. Choose the latest
  run per workflow and its latest attempt; legacy/synthetic records without a timestamp use
  run ID and attempt order. Never reuse an old successful attempt while a newer one is queued.
  Evaluate every same-named job instance in the selected attempt, not just one matrix result.
- **Qualification:** required skipped/neutral jobs block. An active required workflow is still
  pending even if its currently observed jobs pass. A waiting deadline cannot invalidate a
  completed current-head result: it bounds waiting, while re-entry can observe terminal truth.
  No configured checks does not make an empty run set green.
- **Decision aggregation:** evaluate every failing required job and choose the most blocking
  action (ask, fix, rerun, wait, proceed-note). A pre-existing failure cannot hide another
  introduced failure. Preserve workflow/job identity in fingerprints; normalize paths/digits
  only in the error text so matrix job names remain distinct.
- **Logs:** select the named failing group or the first error's group, retain first-error context
  and failing-step tail, strip ANSI/timestamps, redact credentials, then enforce the UTF-8 byte
  cap. Full logs and the combined 16 KiB cap remain the CI-wait node's responsibility.
- **Dependency check:** these are domain policy tables using existing models/redaction and
  standard-library re/path/hash helpers; no package added and no service/LLM calls.
- **Revisit when:** live runs reveal a missing CI signal or changed payload semantics; keep
  exact-head evidence and hard caps while adjusting the table with recorded examples.

## D-024 T7 conservative review selection and deterministic finding admission

- **Decided:** 2026-10-13, T7 builder. Diff stats cannot tell whether a manifest edit adds a
  dependency, so changes to dependency manifests conservatively select deep review. Lockfiles
  remain governed by configured exclusions. Built-in CI/instruction paths always select deep;
  repo risk classes can add paths. `deploy_ops` selects standard with an ops lens; other named
  risk classes select deep. Builder risks raise none/light to standard, never lower a level.
- **Labels and re-entry:** owner overrides choose the initial level, but a previous decision's
  floor still applies on fix deltas. Conflicting owner labels choose the strongest level.
  Preserve previous reasons and standard-tier lenses; deep uses exactly general/security/tests,
  including when operations paths also change. A regression caught and removed an accidental
  fourth ops reviewer on escalation. The caller must
  supply only authenticated owner labels, not agent-created label claims.
- **Admission:** light requires confidence >= 0.7 for blocking priority findings; standard/deep
  use the independent verifier as the confidence check (no additional numeric floor specified
  by the design). None blocks nothing. P2 security blocks only at deep. A location must be an
  absolute lexical path inside the checkout, with no parent traversal, and its entire inclusive
  range must lie in one reviewed range. This pure function does not inspect the filesystem;
  checkout safety and symlink handling remain workspace responsibilities.
- **Deduplication:** normalize title whitespace/case and its leading priority tag, plus category
  case. Keep path case. Process strongest priority/confidence first, then stable lens/path/title
  ordering; a duplicate is dropped even across lenses. Return rejection reasons for malformed
  paths, outside-range locations, unrequested lenses and known IDs rather than silently losing
  evidence. No dependency or I/O added: stdlib PurePosixPath.full_match, parsing and existing hash.
- **Revisit when:** a measured review miss or noisy manifest-only review warrants a richer typed
  input. Never infer a dependency's absence from line counts or allow fix deltas to lower review.

## D-025 T8 workspace ownership, credential lifetime and reviewer instruction overlay

- **Decided:** 2026-10-13. Keep D-009's thin async git CLI adapter; no dependency added. The
  wrapper has an explicit minimal process environment, disables system/global git configuration,
  hooks and fsmonitor, refuses prompts, and kills the process group on timeout/cancellation.
  Trusted setup/gate commands use bash -lc with no inherited credential variables. Outputs and
  log files are redacted before returning/writing; known push credentials and their base64 form
  are additionally removed even if they do not match a token-shaped regex.
  Reject known credentials and token-shaped arguments before process creation; a failing
  regression proved output redaction alone did not prevent a literal token from entering argv.
- **Interface additions:** GitWorkspace accepts optional `origin: Path` for local bare-repo unit
  contracts, `token_provider: TokenProvider` for private fetches and `allow_live` for CLI authority.
  Non-local operations require the live guard and provider; fetch auth, like push auth, is passed
  via GIT_CONFIG environment, never a URL or persisted config. Tests never contact GitHub.
  Add `WorkspacePort.head_sha() -> str`: after a crash following commit but preceding push,
  commit_all returns None on the clean clone; recovery needs to read that existing commit rather
  than guessing from the PR's older SHA or creating another commit. The regression failed first.
- **Ownership:** one instance binds one issue; its only writable remote branch is
  lgcw/issue-<number>. Verify configured and advertised remote default branches, origin identity,
  local branch and clean state before publishing. Leases name the full ref and exact expected
  SHA, including the empty expected SHA for create-only. Existing expected heads must be
  ancestors of the proposed head. Prepare preserves an existing dirty clone; explicit adoption
  refuses dirty state instead of deleting it. No implicit reset to an owner-pushed head.
- **Diff evidence:** NUL-delimited numstat/path queries preserve unusual names. Include untracked
  files without staging them so pre-publication inspection has no index side effect. Count binary
  untracked changes as one line, matching T7. SHA arguments must be full object IDs.
- **Reviewer:** each call creates a separate detached clone at the reviewed SHA. Replace all
  head instruction paths with base versions (AGENTS.md, AGENTS.override.md, CLAUDE.md, .agents,
  .claude and .codex, including nested paths), removing instructions newly introduced by head.
  Before host commands or agent use, reject symlinks that resolve outside the checkout. Overlay
  uses git's tracked base files/modes and never follows a head instruction symlink to write data.
  A failing regression additionally exposed a head-created internal alias at a base instruction's
  parent. Reject that layout before restore instead of relying on git's directory replacement.
  The diff still uses committed base/head, so reviewers can inspect the instruction change.
- **Revisit when:** parallel runs need cross-process mirror locking, or another git host is added.
  Phase 1 runs one workflow process at a time; mirror/clone state is a cache, never progress state.

## D-026 T9 self-contained fenced prompts and exact packaged skills

- **Decided:** 2026-10-13. Renderers return a self-contained TurnInput.text: fixed trusted template,
  a JSON data block fenced with more backticks than any run in the data, and an optional separately
  labelled authenticated owner instruction. Set data/data_label to None to prevent duplicate
  transmission. The harness may still accept raw data from other callers and must fence it once.
  Fence labels are validated constants, never an avenue for introducing another instruction.
- **Review boundary:** ReviewPacket rejects extra fields and has no builder summary, acceptance
  self-grades or test claims. It contains approach/decisions/risks and evidence pointers, while
  gate and CI summaries are code-produced. Packet construction in T16 must preserve this boundary.
  All packet content remains data; only the fixed review template/skill defines the task.
  Before implementation, corrected the new review test's oracle to inspect excluded JSON fields:
  banning the literal word tests would contradict the required tests lens. The structural
  assertion rejects summary/status/tests/acceptance keys while preserving the exact lens value.
- **Skills:** resolve only the six allowed names to absolute paths under the installed package;
  never use a target repo's same-named skill. Keep each skill below 5,000 bytes with YAML name and
  description. Apply skill-creator's guidance to keep roles focused on their own output, not
  sequencing/reruns or remote writes. Validate frontmatter and wheel contents locally; actual
  skill-reference SDK behavior remains T10's live spike, not proven by resource tests.
  Actual wheel inspection first found only five skills: the unanchored build/ ignore also
  excluded skills/build/SKILL.md. A git check-ignore regression failed before anchoring /build/
  to the repository root. Preserve the build-artifact exclusion while shipping the required skill.
- **Fake:** script typed results or exceptions by role, retain separate sessions/turns, validate
  against the requested output model and expose measured usage as a configurable fixture. Unknown
  sessions, wrong schemas and exhausted scripts fail explicitly instead of synthesizing success.
  No token, network, agent process or LLM is used by these contracts.
- **Dependencies:** reuse Pydantic and stdlib json/re/importlib resources/collections; no library
  or SDK implementation added. T10 supplies the real adapter after its required live spike.

## D-027 T11 structured redaction, immutable artifacts and honest usage reports

- **Decided:** 2026-10-13. Implement T11 independently while T10's mandatory owner-login/live
  spike prerequisite remains missing; do not tick T10 or substitute fake SDK qualification.
  Reuse D-011's stdlib JSON/path/log approach and T5's redact; no dependency added.
- **Structured writes:** redact each JSON string before serialization, including nested output
  and explicit credential-header keys. Applying the Authorization regex to an already-encoded
  JSON line can consume its closing quote/braces; the regression must retain parseable JSON and
  neighboring fields. Timestamp/kind/node/fields form typed event records; turns have typed
  prompt/outcome/usage records. Optional injected Clock supports deterministic graph evidence.
  A new failing report regression also caught header-regex removal of neighboring display
  fields; render structured cells by redacting values first, serializing, then Markdown escaping.
- **Files:** events append; individual turns and artifacts write atomically with private file
  permissions and cannot overwrite different existing evidence. Paths stay inside the run root,
  cannot traverse symlinks outside it, and cannot target repo/review checkout directories. Posted
  bodies have IDs in a JSON metadata fence and their exact redacted Markdown below it.
  The derived report.md view may be regenerated atomically; raw evidence remains immutable.
  Add write_report() for CLI/integration: render and atomically save the already semantically
  redacted view. Another failing regression caught the plain-text artifact writer reapplying the
  header regex to rendered JSON cells. For report.md, artifact accepts only the generated view
  and saves it without a second regex pass; arbitrary text at that reserved path is rejected.
- **Report:** render available local evidence without routing from it. Include outcome, node
  timeline, every agent turn, input/cached/output/reasoning usage, known-usage totals, loop rounds,
  CI decisions, findings and dispositions. Input includes cached tokens; reasoning is reported
  separately without adding it to output again. An errored turn without usage is unknown, not
  zero; malformed/truncated local records produce an explicit report warning. Monetary pricing
  is outside this interface. Controller events supply durable-ledger counts in later integration.
  Two additional failing regressions exposed an outside-folder turn symlink and a stale completed
  outcome after a later invocation began. Bound report reads to the run directory and mark the
  latest invocation incomplete if it has no run_end; a log alone never proves a live process.
- **Revisit when:** Phase 1 run inspection needs another report view or multi-process writes.
  Local files are evidence/cache only; GitHub remains the workflow's canonical progress record.

## D-028 T12 runtime contracts and conservative node failure policies

- **Evidence:** docs/spikes/2026-10-13-runtime-contracts.md, pinned local probes. LangGraph injects
  NodeError/context into default handlers and routes their Command to ask; heartbeat-only idle
  expiry reaches the same handler. Pydantic arbitrary_types_allowed requires runtime-checkable
  Protocols. Decorate all four ports; this checks structural capabilities, not method signatures.
- **SDK finding:** 0.162.1 CodexClient.start copies os.environ then updates it with config.env.
  Four supplied keys do not isolate credentials. An env-clearing launcher removed a synthetic
  inherited marker, but Python added macOS metadata; actual-Codex follow-up failed setup twice
  and remains inconclusive. T10 must qualify the actual process, not assume SDK env replacement.
  No dependency added; the official SDK's bundled runtime helper is already its dependency.
- **Graph:** immutable registered node mappings, no LangGraph checkpointer. Until all real nodes
  are implemented, default compilation fails explicitly rather than filling successful stubs.
  Tests inject a complete node mapping. Optional limits on build_graph and optional nodes on
  run_issue make configured policies and compiled runtime behavior testable without patching.
- **Retries:** plain-code nodes use four transient-only attempts, initial 2 s. Whitelist transport
  timeout/connection failures and SDK HTTP 5xx; never retry auth, quota, 4xx, schema errors or agent
  dispatch automatically. Agent nodes get one attempt: a lost response must be reconciled before
  another paid turn. Ask/blocked failures terminate with error instead of recursively asking.
- **Limits/lifecycle:** compile agent timeouts from configured Limits with explicit heartbeats.
  Derive a generous finite recursion guard from loop caps; it does not grant any node another
  fix/rerun. run_issue logs each update and terminal outcome, preserves cancellation as an
  incomplete invocation, and saves the report. The caller that constructs adapters owns close.
  Registration uses a keyword-aware callable Protocol and a fail-closed optional NodeError
  sentinel, proven in a strict-type/runtime probe; no casts/ignores/private LangGraph imports.
  The first router test used get_args on a PEP 695 alias and parametrized zero cases. Enumerate
  the Pydantic Step schema instead, and assert the graph covers that independent declared enum.
- **Routing:** ready must agree with the current PR and latest owned push. Unowned/moved heads
  ask; unresolved findings are trusted only through authenticated ledger entries. Missing review
  thread evidence asks. Durable issue/handoff/pre-publication attempt gaps (D-019) are still node
  integration work, not qualified by this graph skeleton.

## D-029 T12 submitted-review receipts become authoritative ledger facts

- **Decided:** 2026-10-13. Complete D-020's read-side recovery with optional keyword
  build_ledger(..., reviews=()). Submitted review bodies are a separate namespace:
  LedgerEntry.where adds review; conversation and inline comment contracts stay distinct.
- **Admission:** exact workflow author, ReviewMarker only, matching submitted head, and a null
  marker review_id or the actual enclosing receipt ID. Fill the null ID from that receipt without
  posting a second marker. The no-inline regression failed first with unexpected keyword reviews.
  Foreign authors and mismatched heads/IDs are rejected in table-driven tests.
- **Limits:** this proves pure ingestion of already-read records, not a live GitHub submission
  or end-to-end lost-response recovery. T16 must read these receipts before posting another review
  and prove the crash case on the compiled graph. No dependency added.


## D-030 Round-2 review corrections and durable recovery inputs

- **Decided:** 2026-10-13, PR #1 review 6150249995, pinned head 1af4ad6. The reproduced P1/P2
  findings correct implementation defects; no new runtime dependency is added.
- **Service boundaries:** githubkit UNSET defaults must be excluded before mapping. Pending or
  unsubmitted reviews are absent receipts; a submitted review can have no commit ID and cannot
  authenticate a head marker until an exact head is present. Fakes accept review replies only
  on the root comment, matching GitHub's restriction.
- **Ledger:** only one complete trailing marker is a fact. An earlier complete marker makes the
  comment ambiguous; an incomplete prefix is data and cannot swallow a valid trailing marker.
  Retry grants are counted from acknowledgements joined to earlier questions, keyed by step/code
  and deduplicated by command ID. T14–T16 consume those grants without erasing historical activity.
- **Git:** authenticate against the explicitly configured URL. Before authenticated operations,
  validate local mirror/clone config against an exact key/value allowlist and a prepare-time
  snapshot. Reject transport programs, push URLs, includes, URL rewrites and config drift.
  Git's generated `remote.origin.tagOpt=--no-tags` is permitted. Instruction matching is case
  insensitive, and resume base is merge-base(default, HEAD); resumed means the remote issue
  branch exists. This does not widen D-004's credential boundary.
- **CI and review:** failed-run cancelled/skipped/neutral siblings are consequences, not separate
  owner blockers. Blocked CI cannot dispatch a fix; mass failure counts genuine failures only.
  Optional workflows cannot override required failures. Base jobs are selected by newest
  completed workflow run/attempt (GitHub run IDs increase at creation). Excluded paths remain
  risk evidence while excluded lines stay out of size counts; lockfiles select deep.
- **Graph:** missing initial push receipts route to idempotent open_pr recovery. Head-moved retry
  returns an explicit source=human PushMarker adoption request; T13 must persist it before CI.
  A current review reporting blockers requires current-head finding evidence. Every node must
  return next_step explicitly. Node and run failures retain redacted tracebacks locally while
  questions expose only node/class. HTTP 429 is not automatically retried, consistent with D-028.
- **Qualification:** compiled foundation tests prove routing/adoption inputs, not a complete live
  crash recovery or paid-agent workflow. T13 and T17 retain those acceptance obligations.


## D-031 T13 bootstrap and command journals close pre-PR crash windows

- **Decided:** 2026-10-13. Add typed intake (original snapshot/criteria), bootstrap intent/complete,
  setup intent/result and command_done markers. Extend RunMarker with optional snapshot, criteria,
  initial SHA, operation ID and authenticated owner answer. Extend AckMarker with optional command
  snapshot and return step. Legacy fields remain accepted; unknown legacy state asks rather than
  guessing. Acknowledgements are written once before continuation; the newest unfinished command
  can resume, and command_done prevents replay. Retry allowances remain derived from acknowledgements, deduplicated by question sequence
  as well as command ID (review carry-forward 6150762838).
- **Initial commit/push:** persist bootstrap operation/base before making the empty [skip ci]
  commit. Read its message/empty diff on re-entry to reuse it after a lost local response. Persist
  the enriched run intent before push; exact remote SHA recovers push-before-receipt without a
  second push. Add WorkspacePort.commit_message and GitHubPort.branch_head/get_pr_document.
  The draft creation body carries the run marker in that same write; a recovered PR then receives
  its append-only run/push/completion receipts once. Run body/comment copies dedupe as one fact.
- **Setup:** journal before executing trusted commands and after the result. An interrupted intent
  without a result asks; it never runs commands again automatically. An owner continuation gets
  a new operation ID. Dirty setup output is preserved and asks instead of being silently committed.
  Local bare-repo contracts use a recording port adapter and BaseException crash injection to
  bypass normal node error recovery. fail_after's first subsequent call is 1, correcting T13's 0.
- **Canonical input:** freeze the first valid issue snapshot before asking or preparing a clone.
  Owner answers can supply missing criteria and remain separate authenticated instructions. The
  enriched run fact retains this context on the PR. Oversized records ask for bounded scope;
  never truncate canonical data. Structured marker values redact before serialization.
- **Capabilities:** RunContext gains an excluded, non-repr optional TokenProvider; only code-side
  push_auth reads it. No agent prompt receives the context/provider. Label repair checks observed
  state, including a question/blocked marker written before a crash interrupted labels. Posted
  local receipts dedupe by their actual GitHub IDs/body so recovery does not duplicate evidence.
  The completion fact on the issue retains the PR number so closed PRs remain discoverable.
- **Dependencies:** approved SDKs/stdlib only. Real adapters use official githubkit read endpoints;
  live qualification is now unblocked by the owner (D-032) and remains pending execution. No merge/default-branch write added.


- **Test correction evidence:** a new node-log assertion expected `end` to emit node_start, but
  T12 registers its fixed terminator outside `_logged` in build_graph.py. The assertion now
  requires exactly reconcile while waiting, excluding every writer/paid continuation. The
  initial failing assertion was retained in the PR's Tested how evidence; no gate was relaxed.

## D-032 Owner-authorized live target supersedes the original sandbox proposal

- **Decided:** Alex, 2026-10-13, relayed by the reviewer in PR #1 comment 6150166861. Use
  `bodegus/family-calendar` for the T5 adapter contract and T17 smoke. This supersedes D-014's
  `oc2-publish-sandbox` proposal and D-022's alternate clean sandbox proposal.
- **Authority and scope:** the owner accepts live-run risk on this repository. Use recognizable
  issue/branch/draft-PR fixtures, close test artifacts and delete their branches; never merge or
  push to main. The target's existing npm-audit failure is baseline evidence, not a green result.
- **Login:** the reviewer reports the dedicated workflow Codex login is ready. Never read or
  print its authentication file, or reuse the desktop login. T5/T10/T17 live results require actual
  receipts before any box is ticked; this decision alone does not qualify them.

## D-033 T13 review: bounded continuations, closed runs and lost unpublished clones

- **Decided:** 2026-10-13, PR #2 review 6151329960. A command returning to reconcile completes
  its acknowledgement before routing from a refreshed ledger. It never routes directly back to
  reconcile from the same unfinished acknowledgement. Non-abort PR commands repair active/waiting
  labels. No-PR head changes return to open_pr for a bounded recheck after owner correction;
  abort remains available on the resulting question.
- **Closed identity:** add GitHubPort.find_pr, an any-state head-branch lookup via githubkit's
  existing typed paginator. Reconcile and open_pr inspect closed/merged PRs even before the linked
  completion receipt exists. No new library; the existing SDK remains viable (D-008).
- **Lost unpublished clone:** WorkspaceInfo.created distinguishes a code-generated new clone from
  an existing checkout. With a recorded checkpoint and an absent remote, a newly generated clone
  gets a new bootstrap operation/base and setup journal before re-checkpointing. The original
  issue snapshot remains frozen; an unpublished replacement may start at current default. A
  changed existing local head still asks. A second remote read plus exact lease guards publication.
  Fresh code-generated clones reset the prior path's config snapshot, then validate the same strict
  allowlist; existing clone config drift remains refused. Published-clone recovery reuses the
  remote commit and never pushes a second checkpoint.
- **Independent guards:** setup cleanliness compares the worktree with HEAD; committed checkpoint
  content is independently checked against the base, expected message and recorded head. Tests
  isolate those conditions rather than passing through a different earlier guard.
- **Input/evidence:** HTML comments (including incomplete placeholders) and indented code do not
  supply acceptance criteria. PR-body run facts and dedupe remain, with admission/exclusion tests.
  Setup output stays in its local measured log; new SetupMarker receipts retain code/fingerprint
  and tail=null (the nullable legacy field remains readable).
- **Proof:** compiled-graph regressions exercise reconcile retry/answer and ack loss, failed adoption
  followed by retry/abort, no-PR head change, close-before-completion, clone loss with setup/main
  advancement, ownership guards and redaction. Fourteen isolated source-removal probes each fail a
  behavioral assertion, proving guard/body/dedupe coverage without changing production source.
- **Live follow-up:** the reviewer explicitly allowed the persistent T5 fixture/plan follow-up in
  this PR. It now uses the owner-approved family-calendar target and recognizable branch prefix;
  its named command also checks branch/body reads and any-state discovery after fixture closure.

## D-034 T10 official SDK runtime isolation, policy and measured usage

- **Plugin check (step 1):** D-002 and research §5 reject the private/experimental LangChain
  ChatGPT-login bridge. LangGraph supplies control, timeouts and heartbeats, not a typed Codex
  app-server session/skill/output-schema implementation. Its graph stays outside paid calls.
- **SDK check (step 2):** official openai-codex 0.162.1 (Apache-2.0) provides AsyncCodex,
  SkillInput, schema-bearing turns, streaming, resume and interrupt. Use its public APIs only.
  Its pinned openai-codex-cli-bin 0.162.1 dependency (same upstream) publicly exports
  bundled_codex_path/bundled_path_dir. Declare that existing transitive package directly because
  the launcher now imports those helpers; no new package version is introduced. A two-function
  checked stub describes the upstream helpers, which lack py.typed; no type-check suppression.
- **Environment:** CodexConfig.env merges inherited keys. Public launch_args_override with
  /usr/bin/env -i replaces the actual Rust process environment with exactly PATH, HOME, LANG,
  CODEX_HOME. Preserve the runtime's public helper PATH directory. Free real-PID inspection
  confirmed the exact four keys with inherited synthetic token variables excluded. Thin stdlib
  fcntl lock prevents two workflow-owned servers on the dedicated home; SDK close releases it.
- **Policy:** deny_all is sent on every start/resume/turn. The high-level turn workspace_write
  preset creates a new policy with network=false, losing D-012's builder networking. Therefore
  start the fresh first turn with an explicitly configured thread, or explicitly thread_resume
  immediately before every subsequent turn with its role sandbox/network, then omit the resetting
  turn preset. Returned resumed effective policy was workspaceWrite/network=true/approval=never.
  Reviewer/verifier always use read_only/network=false. Reject role/spec mismatches.
  This refines design §5's “set on every turn”: complete thread policy immediately before the
  turn, rather than the SDK preset that changes its meaning. No full-access or auto_review path.
- **Recovery:** cache the fresh thread handle only until first dispatch; thread_start alone has
  no resumable rollout. Cross-process resume after a completed turn works; an unmaterialized
  session maps to HarnessSessionLostError. Refuse to dispatch into an observed in-progress turn.
  T14 must reconcile an interrupted/unknown paid dispatch before selecting a fresh builder.
- **Cancellation:** shield the turn/start reply so a cancellation between dispatch and handle
  receipt can still interrupt that exact handle. If the reply/interrupt fails, close the owned
  server without redispatching. A delayed-reply fake-SDK regression failed before this fix.
- **Output/accounting:** one schema-correction turn at most, no auth/quota/transport retry. Public
  typed notifications supply heartbeat, completion, final answer and measured cumulative counters.
  Own-session rollout supplies the pre-turn cumulative baseline, including across server restart.
  Usage input/cached/output/reasoning are deltas; new nullable context_input_tokens is the latest
  model-request input for the T14 context threshold, distinct from summed billing. Never estimate
  a missing usage value. A resumed thread without its own accounting baseline never dispatches.
  RunLog.next_turn_seq derives the next evidence filename from all retained
  role artifacts across restarts (R2-X3 carry-forward), and turn() still refuses overwrites.
- **Evidence:** docs/spikes/2026-10-13-codex-{environment,policy,paid}.md; four tiny spike turns,
  named live-smoke runs (four turns each, including the final dispatch-cancellation hardening).
  Real agent tools denied .git/config and read-only workspace writes;
  an active shell command was interrupted on cancellation. The bare command/exec RPC's weaker
  .git behavior is irrelevant to this adapter because it never uses that RPC.
- **Limits:** cancellation/invalid-output failures still carry unknown usage at the existing
  error boundary; raw own-session rollouts retain evidence. Quota/auth are covered through the
  public SDK fake rather than spending/revoking a login. This decision does not qualify T14–T17.
- **Revisit when:** SDK gains an explicit network-bearing turn sandbox, an environment-replacement
  option or typed runtime helpers; or Phase 1 evidence contradicts the measured policy/accounting.

- **T14 integration correction:** an observed in-progress resumed turn raises HarnessError,
  not HarnessSessionLostError. “Lost” permits the bounded fresh-builder rule; an active turn
  instead requires reconciliation, so another builder cannot race its workspace. A fake-SDK
  regression failed before this classification fix and proves zero additional dispatches.

### D-034 R1 qualification refinements (PR #3 review 6154582337)

- **Launcher/roles:** capture the actual CodexConfig in unit tests, execute both its minimal
  prefix and complete trusted launcher with env replacing the binary, and inspect the real
  Rust PID's environment in a free probe. All show exactly PATH/HOME/LANG/CODEX_HOME. Dropping
  -i, reverting to SDK env-merging, or dropping analytics each fails an assertion. Read-only
  reviewer/verifier and workspace-write builder policy are table tested on start and resume;
  mutations making all roles writable or networked each fail. Mismatched specs fail before start.
- **Repository instructions:** remove project_doc_max_bytes=0 from startup and thread config.
  The builder reads its target AGENTS.md and reviewer/verifier read the trusted base overlay
  prepared under D-025. The revised live first turn answers a value present only in AGENTS.md,
  with tools forbidden in that prompt; this proves loading rather than a prompt echo. Earlier
  max-bytes-zero spike transcripts remain historical, superseded by this correction.
- **Lifecycle:** keep a fresh handle until turn/start returns, classify missing accounting as
  HarnessSessionLostError, clear prior attempt handles before a retry resume, and classify an
  in-progress turn as HarnessError (not lost). Interrupt RPCs are bounded at one second; SDK
  shutdown and the home-lock release run even after an interrupt or initialization/close error.
- **Physical cancellation:** the stronger live test refuted SDK interrupt as shell cleanup:
  terminal status was interrupted but `sleep 2; printf ... > delayed.txt` still completed. The
  public SDK has no runtime process-tree shutdown hook; LangGraph cancellation alone cannot
  implement it. A thin stdlib/POSIX boundary now uses a unique, code-owned PID receipt from the
  trusted launcher, verifies its direct-parent ancestry, freezes its descendant tree and kills
  those processes (including children with separate process groups) before SDK close. No private
  SDK process attributes or new dependency. Cancellation closes that owned runtime; the next
  invocation creates a new server and resumes durable sessions. PID/parent inspection reads no
  command lines or environments. Tests refuse self/foreign-parent PID receipts. Startup failure
  also cleans up and releases the lock even when SDK close fails.
- **Live proof:** same-call-ID custom-tool receipts from the own-session rollout prove the
  read-only command actually ran and exited 1 with a permission denial. Thread.read omits these
  custom tool items, so its empty item list was an invalid evidence assumption. Cancellation is
  checked after the sleep deadline, with persisted interrupted status read on a new server and
  actual server PID disappearance. The strong delayed-file assertion passes after physical
  cleanup; it was not weakened. Earlier immediate-absence checks did not qualify physical cleanup.
- **Structured errors:** prefer CodexErrorInfoValue over incidental prose before keyword
  fallback. Fake modes cover failed/interrupted turns, missing usage, resume failure, role
  mismatch, active-turn refusal, wedged/failed interrupts and shutdown failures.
- **Quota reset-time deferral (R1-F5, reviewer explicitly permits a recorded deferral):**
  HarnessQuotaError.resets_at remains None. SDK 0.162.1 exposes RateLimitSnapshot and a low-level
  account/rateLimits/read RPC, but AsyncCodex has no public rate-limit read/subscription and its
  routed turn stream does not expose the global account stream. We preserve the public facade
  and single owned server rather than using private client attributes or a concurrent server.
  T14 must ask with an explicit “reset time unavailable; check the dedicated login's usage” when
  None, rather than promise a reset time. No live quota exhaustion or reset-time qualification
  is claimed. Wire the public rate-limit boundary in a follow-up, or when the facade exposes it.
- **Cached policy limit (R1-F10):** a free probe changing network false→true on the same cached
  thread returned false both times, refuting in-process reconfiguration. Separate new servers
  resumed that materialized probe thread with false and then true, each applying the requested
  value. Roles are immutable within a harness; start/first cross-process resume selects their
  policy, subsequent resumes send the same policy, and each turn sends deny_all. No claim that
  a cached thread can change roles or networking. The turn preset remains omitted to preserve
  the selected builder network policy.
