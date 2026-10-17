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
- **X-9 observation (PR6/6161401783):** reviewer probes with pinned Codex0.162.1 workspace/
  read-only sandbox presets and the minimal environment could not use the current gh keychain
  login (invalid default token); no GH_TOKEN is inherited. This is a current-host observation,
  not a general home-directory isolation guarantee; T17 doctor requalification follows on PR7.
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
- **Counts (extended by D-035):** unpublished gate-fix intents now also count; other fix counts
  reflect published `push` source markers, reruns reflect `ci` actions,
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

### D-034 R2 error boundaries and cleanup scope (review 6155287748)

- **Control flow:** redacted cleanup diagnostics use an instance logger. Process/SDK shutdown
  errors are collected into HarnessError for close(), while cancellation preserves its original
  CancelledError and startup preserves its original authentication/startup exception. SDK close
  and the home-lock release still run. Fake cleanup-port failures and SDK-close failures prove
  the original exception type, task.cancelled(), token-safe logs and replacement-lock admission.
- **HTTP classification:** specific unauthorized/usage-limit/rate-limit codes keep precedence;
  typed nested httpStatusCode 401/429 maps to Auth/Quota, then generic codes fall back to the
  keyword mapper. The optional R1 generic-code fixture had incorrectly required plain
  HarnessError despite authentication prose; R2 explicitly requires fallback. Its expected
  class is now the more specific HarnessAuthError. No assertion, skip or deadline was loosened.
- **Termination proof:** local real-process tests poll os.kill(child_pid, 0) until
  ProcessLookupError, under a fixed three-second bound, in addition to checking delayed writes.
  Removing descendant SIGKILL now fails both the normal-inventory and inventory-failure cases;
  SIGSTOP alone no longer passes. Fixture teardown still cleans up the deliberately stranded child.
- **Scope/obligation (R2-F4):** ownership covers the direct child runtime and descendants still
  reachable in the kernel pid/ppid inventory. An already reparented child (nohup/double fork or
  a parent that exited) and a fork chain faster than the three passes can escape. Cleanup does
  not guarantee workspace quiescence. T14 must re-verify actual diff/content after a cancelled
  builder before gate or commit; a cancelled/unknown dispatch must not reuse a stale handoff.
  It must also bind the committed candidate to measured gate content before pushing. These are
  required integration obligations, not a stronger isolation claim for T10.
- **Optional PID hardening (R2-F5):** a previously stopped process failing the ownership
  re-check receives SIGCONT rather than staying stopped. A fake-inventory/real-child regression
  proves restoration. Already absent root PIDs are skipped. Start-time identity is deferred:
  current authority remains PID plus direct-parent/descendant ancestry, with the review's
  acknowledged millisecond PID-reuse caveat. No claim of protection against that race or of
  containment for reparented daemons; later container/cgroup isolation remains the stronger path.


## D-035 — T14 execution journals and content-bound publication

- **Status:** implemented in T14; covers D-019's pre-publication gaps. No new dependency.
- **Paid dispatch:** a `build` intent records operation, parent, session, source and owner command
  before a turn. Its completion contains the sanitized canonical handoff, measured usage and
  actual content fingerprint. An intent without completion asks `build_unknown`; only a new
  authenticated owner retry authorizes another paid operation. A session selected but never
  materialized may get one fresh `session_lost` session; a busy turn is not a lost session.
- **Startup failures:** dedicated-login/quota failures during session creation use the same
  repair guidance as turn failures, with no build intent, paid turn or push. Session creation
  errors are logged after the harness redaction boundary; a new graph regression failed first.
- **Limits:** unpublished gate-fix attempts count distinct build intents in the PR ledger;
  publication does not count the same attempt twice. Repeated normalized gate failures and
  measured context occupancy select one fresh session per cause, then ask. Owner retry grants
  are scoped to the pending limit. Local gate fixes retain CI/review publication provenance.
- **Gate:** journal command intent before execution and exit/content/feedback after execution.
  Unknown command completion asks, rather than replaying host commands. An explicit owner retry
  gets a new operation. First gate entry checks bytes against the builder completion; commands
  must leave the same content before/after. Exit zero with changed content is recorded truthfully
  as zero plus blocking feedback, requiring another build and stable gate.
- **Content evidence (D-034 R2-F4):** sorted changed paths include untracked files, deletions,
  executable mode and symlink targets; framed SHA-256 hashes include the published parent.
  Gate and publication compare actual bytes, not line counts. An independent temporary shared
  audit clone checks out the immutable candidate commit and computes the same content hash
  before push. Same-size edits after gate and edits during commit are rejected. A cancelled or
  unknown paid turn has no usable completion; a prior completion cannot authorize altered bytes.
  These checks do not claim global process containment or protection from later external writes.
- **Git dependencies:** D-025 already selected thin git CLI integration. Hashing uses hashlib and
  standard filesystem operations; auditing uses the same git adapter. No Git object decoder or
  additional SDK is needed. Machine path output containing a redaction sentinel fails closed,
  preventing a token-shaped filename from hiding a real symlink during path validation.
- **Publication:** commit intent, exact operation/issue/parent trailers, committed receipt, leased
  push, push receipt, canonical handoff body with atomic body-operation receipt, then completion.
  A lost commit response recovers only matching trailers. A lost push response observes the exact
  remote SHA. Reconciliation prioritizes incomplete owned publication before CI. A lost body
  update response compares the actual body and avoids rewriting it. Foreign heads ask.
- **Host command cleanup (review R2-X2):** stdout/stderr capture uses anonymous temporary files;
  waiting is on the owned process, not pipe EOF. The owned process group is killed after normal
  exit as well as timeout/cancellation, and reaping is bounded. An already escaped process group
  is outside this containment, but cannot indefinitely hold pipe draining open. Real subprocess
  regressions exercise both successful-parent/background-child and escaped-pipe cases.
- **Evidence:** named T14 graph tests plus nine comment boundaries, commit/push/body response
  loss, unknown paid/gate results with explicit retry, session-loss/context/failure caps,
  provenance and same-path byte races. See the PR's actual command output. Unit checkpoints stop
  at `ci_wait`; T15/T16 and a real end-to-end run remain unqualified by T14.


### D-035 R1 protected approval and bounded recovery (review 6156345540)

- **Protected paths (F1):** original issue pre-authorization requires exact relative-path tokens;
  `docs/AGENTS.md.bak` cannot approve `AGENTS.md`. Owner prose is never added to that token set.
  A protected-path question records its sorted exact paths and the current content fingerprint
  (including parent). Only its authenticated `/lgcw answer approve` acknowledgement grants that
  exact proposal. Changed content/path sets re-ask. Denial plus a non-compliant builder reproduced
  an unauthorized push before the fix; now it re-asks without a new push.
- **Gate retries (F2):** every gate entry checks bytes against the builder completion, including
  explicit retry after an unknown command result. A hand edit after a command crash requires a
  new build; the old handoff cannot authorize it.
- **Service bounds (F3):** fit the PR body before publication effects, reserving room for its
  compact receipt. That body RunMarker contains ids/hashes and no issue snapshot/criteria/answer;
  the canonical run remains in authenticated conversation facts. Thin view receipts are not a
  replacement for that canonical run. Oversized explanatory agent prose is visibly clipped while
  retaining every machine identity and list item; full raw output remains in the local turn
  artifact. If identities cannot fit, write a known HandoffTooLarge error receipt and ask for
  inspection/narrowing/abort. Even explicit retry never pays for that known result again. Check
  actual escaped marker size before posting the completion. Tests cover 28 KB issue + 36 KB
  handoff, 59.2 KB handoff and an unfit identity list.
- **Host output (F4):** capture at most 64 KiB per stream in the controller, retaining head/tail
  and a truncation marker. Fixed-length positional reads use the file-size snapshot; no shared
  writer offset is changed. Redact overlapping windows before clipping (overlap includes known
  credential lengths), and also cap redaction expansion. Temporary on-disk output is not capped;
  the command lifetime remains bounded. A 32 MiB stdout + 32 MiB stderr regression fails without
  the cap; credential-at-clip and redaction-expansion regressions pass.
- **Owner context (F5):** restart prompts carry the latest acknowledged owner answer in fenced
  JSON, even when a bootstrap-era answer exists. No restart silently loses later clarification.
- **Pending fixes (F6):** BuildMarker.pending_feedback survives an errored or unknown fix turn;
  retry restates the exact gate failure until a fix completes. It is distinct from newly measured
  claims feedback.
- **Retry grants (F7/F8):** the code table in graph/retry.py and design §6.1 defines every
  build-directed question. A gate/no-change limit retry grants one resumed fix without forcing a
  competing restart question. A restart-limit retry grants one fresh builder for that continuation;
  an unknown result's retry resumes rather than silently spending another fresh-session grant.
  Session-loss retry grants one fresh builder seeded with the handoff; auto-recovery plus explicit
  grants remain PR-derived. Known unusable session-loss attempts do not consume gate-fix rounds
  (F11). Auth/quota session-creation failures use the same repair guidance as turn failures.
- **Post-commit recovery (F9):** an explicit retry freezes the observed content and target in a
  reset_intent receipt. Preserve the exact candidate under refs/lgcw/recovery/<operation> and
  dirty tracked content under the sibling <operation>-work-/<content-hash> namespace. Restore
  a gate-matching candidate, or restore its published parent and abandon the rejected candidate
  for a new build. Refuse foreign local commits and untracked files. Backup refs are append-only;
  repeated observation of an already-restored clean target does not reset again. Tests cover
  lost commit/reset responses, both recovery choices, recoverable dirty bytes and foreign-commit
  refusal. The owner question states the restoration action before retry authorizes it.
- **Push identity/tests (F10/F12):** publication passes its audited immutable SHA into push; the
  git refspec uses that SHA rather than HEAD. External executable-boundary races prove an owner
  update between pre-check and git push is rejected, and a moving local HEAD cannot change the
  published candidate. Replacing the exact lease with --force now fails the race regression.
  The auth test makes edits before failure and asserts re-login guidance; the repeated-gate test
  asserts the precise gate_fix_limit code, not either of two possible limits.
- **Evidence:** actual failure reproductions, focused integration, full make check and killed
  source-copy mutants are recorded in docs/validation/2026-10-13-t14-r1.md and the PR. No new
  dependency or paid/live call is needed for these corrections; standard-library bounded I/O
  and D-025's existing git adapter cover the added operations.


### D-035 R2 approval revocation, original prompt recovery and exact ancestry

- **Review:** PR #4 comment6157601488. Required F1–F6 and optional F7–F12 fixed in this append.
- **Explicit authorization (F1/F2/F5):** only full `lgcw-allow: <path>` lines outside HTML comments
  and Markdown fences pre-authorize exact relative paths in the frozen issue. Ordinary mentions,
  denial prose and hidden text do not. The latest protected-path response invalidates older
  permission unless it is an exact approve for that question's paths/content. A/B/A after a
  denial re-asks without pushing. An unchanged approved builder receipt goes directly to gate,
  with no additional builder turn; changed bytes re-ask. Plan T14 and design §4/§6.1 now match.
  Accepted residual (D-004): gate code or an escaped process using the owner's gh login could
  post an authenticated approve command. This local owner-identity limitation is unchanged.
- **Continuations (F3/F4/F10/F11/F12):** owner feedback is never retained in pending_feedback;
  every continuation uses current owner_answer. Each selected session with no successful
  handoff retains its original initial/restart prompt, full issue and restart handoff. An unused
  fresh marker is reused without spending a loss grant. Initial retries/owner clarifications/
  rebuilds use source=build; known auth/quota/lost-session errors are excluded from gate-fix
  attempts. Unknown paid results and actual gate fixes remain bounded. Restart uses the same
  authenticated owner suffix as build/fix, retaining its fenced evidence copy.
- **Publication/restore (F6/F9):** public thin WorkspacePort.commit_parents uses the existing
  hooks-off git wrapper; both commit-recovery branches and restoration require exactly one
  parent equal to the journaled parent. Copied trailers or a matching tree cannot adopt a merge.
  New port-boundary tests move HEAD before push, introduce untracked work and change tracked
  content before intent or immediately before reset. The unreachable pre-push body-size branch
  is removed; the real render reserve is tested directly against its escaped receipt.
- **Capture (F7):** read bounded windows with two margins, then discard the outer margin in
  redacted coordinates before clipping. Shrinking replacements cannot pull an incomplete
  credential into view. Credential shapes embedded in surrounding text are masked; the existing
  standalone short-key rule remains, and extra embedded-key recognition avoids treating ordinary
  task-* filenames as API keys. Existing visible-mask assertions remain. CapturedStream and
  GitResult explicitly report truncation; git machine reads refuse incomplete path/metadata
  output instead of parsing the omission marker as a filename. Gate logs still use bounded text.
- **Handoff (F8):** fit explanatory prose in escaped JSON coordinates and, inside the clip loop,
  measure the actual BuildMarker receipt. Keep paths/IDs/criteria/list entries intact. The
  12,000-arrow handoff now journals and publishes after one turn instead of HandoffTooLarge.
- **Dependency ladder:** no new package. Standard-library parsing/redaction and the approved git
  CLI boundary implement only these narrow policy checks; no second SDK or model call.
- **Qualification:** reproductions, validation corrections and killed guard mutants are retained
  in docs/validation/2026-10-14-t14-r2.md. No paid/live run is needed for these deterministic
  corrections. No merge, default push, force-push, assertion/timeout/lane weakening or gate waiver.

### D-035 R3 — recovery, revocation and CommonMark scope (review6158686710)

- **Gate crash:** an approve continuation may reuse its builder result only before any gate
  record exists. A complete gate receipt finishes the restored command and clears owner_command
  before routing; a crash after receipt cannot create an approval gate/build cycle. Runner tracks
  bounded hashes of observed node/state pairs; repeated state or GraphRecursionError posts a
  node_error ask through the normal durable question writer. The old command is finished after
  that ask exists, so retry and abort remain usable. No paid dispatch or push on the safety path.
- **Revocation:** select the latest protected-question acknowledgement as a unit, requiring exact
  answer approve, matching question route, paths and content fingerprint. Also read current
  allowed-author unmarked commands after that approval. Any later command revokes it before a
  build/gate continuation, after the long gate and immediately before push. Journal the revoking
  command against its question; denial/retry asks again, abort routes to the terminal blocked node.
  Frozen ack snapshots remain authoritative for already-acked text; edited old comments cannot
  rewrite them. A non-allowed author or workflow-marker-bearing comment cannot revoke or approve.
- **Parser:** use only CRLF/CR/LF line breaks; require a standalone paragraph of full allow lines,
  with actual blank line/body boundaries. Mask HTML comments (including unterminated ones) and
  script/pre blocks while preserving line boundaries. Respect fence character and opening length.
  Soft-wrapped prose, lazy blockquotes and Unicode separators cannot manufacture allow lines.
- **Rebuild:** restored-parent feedback has its own code source rebuild, taking precedence over
  stale persisted feedback. Its prompt states the restoration instruction and clears the old
  handoff's reset-file claims. Stale owner pending feedback remains filtered; current authenticated
  owner instructions still use the trusted suffix. This is a new build, not an accidental gate-fix
  charge just because the restore instruction was code-produced.
- **Accepted command residual (no code):** a command's owner is its GitHub creator, not its last
  editor. Someone with write access could edit the owner's post-ask denial into approve before
  acknowledgement. That is in the same accepted authority class as the shared owner-gh identity;
  no editor-identity guarantee is claimed. Acked text is frozen and later edits do not change it.
- **Optional carry explicitly to T17:** R3-F6 unused granted session-loss accounting can allow one
  extra fresh session after a marker-only crash; R3-F7 approved claim mismatch should route its
  exact path feedback to a charged gate fix; R3-F8 changed builder receipt should ask
  workspace_changed directly; R3-F9 embedded sk-ant/sk-admin keys and long task-* names need the
  specified redaction corrections. These are tracked in the T17 plan before full live execution.
- **Qualification:** docs/validation/2026-10-14-t14-r3.md. All mutation probes use a unique
  --basetemp per mutant; setup/import failures do not count as kills. No new dependencies, model
  turns, GitHub live writes or permission widening.


### D-035 R4 — Fail closed on HTML-block issue bodies

- **Authority:** PR4 review6159722453, R4-F1, the sole security-P2 merge blocker under the
  prototype-first bar. The raw issue body is checked with CRLF/CR/LF boundaries before masking.
  Any line whose first non-space/tab character is < disables all issue-body lgcw-allow
  pre-authorization. This deliberately conservative rule includes HTML-like lines inside code
  examples. Protected changes then use the existing explicit question/content-bound approval.
- **Implementation:** two added lines, no masking extension or new dependency. Existing inline
  comment/script/pre and fence protections remain; tests isolate them with inline openings so
  the whole-body guard cannot hide a missing parser guard.
- **Proof:** style, CDATA, processing instruction, details and hidden-div graph cases ask without
  a protected push; a plain standalone allow paragraph still publishes. Pure cases cover all
  named HTML types with CR/LF/CRLF and the four requested parser-guard isolations. Five guard
  removals are killed in separate basetemp directories. Full transcript:
  docs/validation/2026-10-14-t14-r4.md.
- **Scope:** V-NEW-1..3 and V-P3a..d carry to the T16 PR's hardening backlog as requested. No
  optional T17 patch is included here; df82dc9 remains the parent of this small security fix.


## D-036 — CI observation, required-policy union and rerun intent

- **Decided:** T15, 2026-10-13. The CI node contains no LLM dispatch. Poll exact-head latest
  workflow attempts with 15/30/60/120-second backoff and a heartbeat. Deadlines/grace use the
  durable pushed comment timestamp, so restarting does not reset them. Closed/foreign heads stop.
- **Required policy:** union configured workflow/job pairs with applicable branch-ruleset and
  classic-protection context names. Bind names to observed jobs; before a name appears, include
  every observed workflow conservatively so approval/startup blocks remain visible. An unknown
  required name never becomes green. Pass the identical union to both classify and decide.
  External check apps cannot be proven by Actions jobs; fail closed with owner attention when
  protection pins another app. GET /apps/github-actions returned id 15368 / slug github-actions
  on github.com. This adapter supports github.com, not a claim of GHES app identity.
- **SDK ladder:** D-008's githubkit 0.16.1 already exposes typed async_get_branch_rules (pagination)
  and async_get_status_checks_protection. Their generated v2026_03_10 schemas include context and
  integration/app IDs. Use these public SDK operations, not a new HTTP client or custom API.
  Classic protection 404 is the endpoint's absence response; other failures propagate, never
  become an empty policy. Required-policy mapping is tested with the pinned generated models.
- **Reruns:** record the CI decision then a rerun intent for exact head/run/from-attempt before
  dispatch; record accepted afterward. After process loss, a strictly newer attempt recovers an
  unknown request. Without a newer attempt, wait only the existing grace/deadline, then ask for
  manual Actions inspection/start and explicit workflow retry. Never dispatch the unknown request
  twice. Counts remain PR-derived, per class/head and per PR; CI markers include observed attempt
  identity so distinct allowed reruns cannot collapse into one fact.
- **Evidence:** authoritative runner annotations need no downloadable log (a failed acquisition
  may have none). Other logs are redacted, retained and trimmed. Builder feedback includes the
  selected failure first, at most 8 KB per job and 16 KB total. Retain feedback before the fix
  decision, so a crash cannot resume with only a lossy generic message. Missing/expired GitHub
  logs preserve available job/annotation evidence, not a fabricated test result.
- **Infrastructure carry-forward (PR2 R2-X1):** runner/action/image-download patterns count only
  in service annotations or an actual failed setup step. Application test prose cannot authorize
  an infrastructure rerun. Network errors likewise require failed setup-step evidence.
- **Repeated CI fixes:** the builder compares durable CI feedback fingerprints across published
  heads. The second same failure gets one fresh builder per cause; its recurrence asks. A scoped
  owner retry can grant one more CI fix, but does not waive rerun caps.
- **Qualification:** named CI graph tests, four comment-response crash boundaries, unknown intent
  with manual next-attempt recovery, ruleset-only approval/missing checks, app identity rejection,
  infrastructure-prose regressions; actual output in the PR. Read-only live policy discovery
  returned no required contexts for both authorized repos. T16 review/merge-ready remains an
  explicit unit checkpoint; no complete real workflow is claimed here.


### D-036 immutable CI diff evidence and live Actions read proof

- **Current-head evidence:** CI startup classification must use committed base..pushed-head
  paths, not the owner's dirty or untracked work. A regression adds an unpublished workflow file
  beside an unchanged committed workflow and observes a real-shaped startup_failure: before the
  fix, it dispatched an unnecessary builder turn; now it asks without a new turn or push and
  preserves the unpublished file. WorkspacePort.commit_paths uses the existing D-025 git CLI
  boundary with explicit immutable SHAs and no external diff/textconv. No new dependency.
- **Pinned adapter qualification:** read the D-032 owner-authorized closed T5 fixture PR25.
  githubkit returns all three actual CI jobs, including two annotations on the audit failure,
  and a 39,932-character plain-text log through the redirected download endpoint. Trimming yields
  8,192 bytes. Zero paid turns or GitHub writes. Transcript:
  docs/spikes/2026-10-13-actions-read.md. This confirms the adapter; it does not qualify a full run
  or permit failure/skipped required checks to be treated as green.


### D-036 R1 corrections: execution provenance and complete bounded evidence

- **Review:** PR #5 comment 6157412612. A recorded rerun decision with no matching intent
  resumes that exact head/run/attempt operation; it does not spend the allowance a second time.
  Once an intent exists, unknown dispatch still requires an observed newer attempt or owner
  intervention. The fake exposes later attempts only after a real recorded rerun request.
- **Execution ownership:** RunView retains event, head branch/repository, PR numbers and workflow
  path. Before selecting latest attempts, require this repository, this PR branch and push or
  pull_request; a PR event must name this PR. Re-read run identity/attempt and PR/remote head
  immediately before dispatch. A move during polling or after intent asks without dispatch.
- **Authoritative classification:** preserve annotation paths. Runner evidence is check-run
  output or annotations without a file path or under .github/. Application-file annotations
  cannot authorize infrastructure/resource reruns. Always try the failing job log; 404/409/410
  preserves the available metadata. Resource patterns use those service fields, never application
  log prose. Setup classification uses anchored known setup names, not arbitrary substrings such
  as Test download cache. Flaky matches exact FAILED test identifiers, and every reported failing
  identifier must be configured flaky. Existing positive resource fixtures now carry a service
  annotation as well as the original log; their expected class/action assertions are retained.
- **Required contexts:** a same-named passing job cannot hide an unresolved or approval-blocked
  workflow. The first protected-flag-only 404 cross-check failed on real family-calendar:
  protected=true, but protection.enabled=false and checks/contexts empty with enforcement off;
  applicable rules are deletion/non_fast_forward/pull_request, without status checks.
  Reviewer clarification 6157652390: after the complete ruleset read succeeds, explicit classic
  disabled state (protection.enabled=false), or enforcement=off with empty checks/contexts,
  proves no classic required checks. Missing protection, enforced checks or other enforcement
  values ask. Unsupported workflows rules ask explicitly. All rows have SDK unit tests, including
  the observed family-calendar shape. The repeated live policy read passes both authorized repos;
  no owner remediation or policy write is needed.
- **Evidence:** remove OSC/DCS/ANSI sequences and other controls except newline/tab before saving
  evidence. Cap annotations at 2 KiB per job, each job at 8 KiB and aggregate at 16 KiB, preserving
  log context/tail independently of annotation size. Measure the escaped FeedbackMarker before
  publication. Startup failures retain workflow/path and check-suite output (or an explicit
  unavailable-details statement), with a fingerprint stable across published heads.
- **SDK ladder:** reuse githubkit 0.16.1 public stream=True and aiter_bytes, with its async context
  keeping the transport open; finally closes the response. No new runtime dependency/client.
  Stop complete-log downloads above 8 MiB, SHA/base-run observations above 100 and job observations
  above 200; ask ci_evidence_limit instead of treating truncated observations as complete. The
  HTTP unit tests use only the existing SDK with an in-memory synthetic transport and credentials.
- **Proof:** named graph tests retained; exact dispatch counts replace the earlier <=1 crash
  assertion, with boundary 2 explicitly requiring zero dispatch and ci_rerun_unknown. Added
  provenance, every requested guard, control-byte, two-job annotation and SDK fallback/protection
  tests. Qualification and killed guard mutants: docs/validation/2026-10-13-t15-r1.md.


### D-036 run-association read qualification (no policy change)

Pinned SDK read: own OPEN PR5/run38488590957 reports exact repo/branch/head and association[5];
the D-032 CLOSED T5 fixture PR25 has an empty association list. No universal open-run guarantee
is inferred. The CI node already stops closed PRs before selecting executions; no ownership
policy change follows. Missing open associations continue to fail closed and the actual T17 run
must qualify its own metadata. Zero model turns/GitHub writes; exact transcript in
`docs/spikes/2026-10-14-run-associations.md`.


### D-036 R2 corrections: bounded transient cost and structural provenance

- **Authority:** reviewer PR5 comment6158430183 explicitly revises the CI policy. This section
  supersedes the earlier annotation-path/output authority, user setup-name allowlist and
  per-class rerun-on-recurrence owner asks. Infra/resources/flaky share at most one automatic
  rerun per head; another genuine failure on a rerun head goes to the builder with downloaded
  evidence even if its apparent class changes or becomes pre-existing. Existing blocked,
  approval, policy, deadline and hard limits still ask. Successful flaky reruns retain the note.
- **Evidence:** a path (including `.github`, `.github/x`, None) and check-run output are never
  service provenance. Preserve numbered JobStep metadata plus whether the complete step list was
  observed. Infra may use GitHub's own step number1 named exactly Set up job failing, startup
  job conclusions, or runner-loss/cancellation before any user step starts. Missing step metadata
  cannot prove this phase. Resource patterns likewise need this phase. User setup names and
  network prose grant no rerun, including Install dependencies and a user Set up job at number2;
  those failures go to the builder. This is stricter than scanning only the failing step's network
  section, and prevents scanning another step's network output entirely. service_output remains
  recorded evidence, with its former routing authority removed. Pytest flaky detection requires
  all FAILED identifiers known, one summary whose failed count matches, and no error lines.
- **Terminal evidence:** OSC/DCS/APC/PM/SOS removal consumes at most4096 characters on one line
  and leaves a placeholder. Unterminated strings never consume subsequent failure lines. The
  classifier, resumed builder and saved -full.log are each checked with all five variants.
- **Ownership:** PR association is not a triggering-PR proof. Preserve association base.ref,
  require a unique matching PR/base, and ask on multiple run associations or another open PR
  sharing the branch. Check again before intent and after its write, before dispatch. The fake
  can freeze PR head independently of branch head, proving both halves of the guards.
- **Timeout dispatch:** compare fresh conclusion to the observed conclusion, including cancelled
  timeout runs. Validate before recording intent and repeat after it for races. A changed run
  before intent cannot strand an unknown intent. Crash-and-rerun behavior remains exactly once.
- **SDK ladder:** D-008 remains applicable; githubkit0.16.1 public async_list_workflow_runs accepts
  workflow_id as an int or string path. Query that workflow path directly with branch, event=push,
  status=completed, per_page=1. No run means empty baseline, never a repository-wide 100-run search.
  Filter raw run ownership before the owned-run cap and startup-suite hydration. Thin SDK read
  helpers expose these existing adapter boundaries to synthetic HTTP unit tests; no new client,
  runtime package, credential authority or model call. Existing job/suite/aggregate caps retained.
- **Required-policy conservatism (R2-F8):** retain the current conservative unresolved-context
  union: a same-named job cannot prove which workflow a protection context intends. An unrelated
  startup-failed Nightly can therefore ask, even with a same-named passing job elsewhere. This
  intentional fail-closed behavior is documented rather than narrowed without policy identity.
  Unsupported workflows, required_deployments, code_scanning and merge_queue rules now ask.
- **Feedback:** retain selected failure first, 2 KiB annotations, 8 KiB/job and16 KiB aggregate;
  reserve a bounded also failing (omitted) identity line when evidence cannot fit. A compact third
  job still retains its log if enough space remains; the existing third-tail assertion is kept.
- **Live qualification:** real `.github` user-command annotations and empty check output are
  pinned in tests/fixtures/ci/provenance-observation.json. No real runner-loss/literal printed
  ::error specimen was available. R2-F12 is explicitly inconclusive for those two shapes, carried
  to T17 qualification; path/output are no longer routing authorities. No failure manufactured,
  models dispatched or GitHub writes: docs/spikes/2026-10-14-ci-provenance.md.
- **Proof:** docs/validation/2026-10-14-t15-r2.md records reproductions, guard removals and final
  make check. T16/T17 and the full real version-bump execution remain unqualified here.
- **Live base-query correction:** the public SDK accepts a workflow identifier string, but the
  actual endpoint returned404 for .github/workflows/ci.yml and200 for ci.yml. Normalize the
  filename before the call; the strengthened synthetic route regression failed first. Actual
  repaired latest_base_jobs read returned run38473073579/check/success, zero models/writes.
  Transcript: docs/spikes/2026-10-14-base-workflow.md. A malformed step list missing numbers also
  cannot claim complete observation; its negative regression failed before tightening the flag.


## D-037 — Owner-directed prototype-first Phase 1 scope

- **Authority:** reviewer-relayed owner decision PR4 comment6159291007 (2026-10-14), applied to
  T15 by6159291252; follow-up6159336971 freezes df82dc9 and keeps optional R3-F6..F9 off PR4.
- **Merge bar:** P0/P1 and security-relevant P2s in scope block (credentials, protected paths,
  owner-command authority, wrong bytes, impostor CI). Other P2/P3 items are one-line entries in
  the single T17 Hardening backlog. One verifier per fix round; report fixes exceeding about
  300lines instead of expanding them. No invariant, assertion, timeout or lane is relaxed.
- **T16 replacement:** none/light only, one fresh reviewer and one COMMENT review, P0/P1 blockers
  resume the existing build/gate/publish/CI path, re-review, cap2 then ask (explicit retry +1).
  Configured standard/deep executes light with a logged mapping. Ready mutation/labels/marker
  remain once-only and no merge endpoint exists. Verifier/disputes/thread resolution/interdiff/
  three-lens deep/review-specific human adoption wait for evidence after first runs.
- **T17 replacement:** run/report/doctor, family-calendar only; memgo-app waits for Phase1bR3.
  The live smoke is Phase1bR1 proxy-addr audit repair, once Alex creates the issue. Keep the
  ci_wait kill/rerun proof and actual run report/usage/CI/side-effect receipts. The source/CI
  evidence so far does not prove that real execution.
- **Preserved optional work:** local branch codex/t17-hardening-r3-local holds four reproduced
  optional T14 fixes; no push to df82dc9. It is brought into T17 as directed, rather than
  restarting current verification. The new backlog supersedes earlier promises to finish all
  non-security hardening before the first prototype run.
- **Why:** the owner prioritizes the working issue-to-merge-ready path over successive edge-case
  review rounds. This revises the implementation scope, not the overall requested end state:
  a real CLI execution must still create a qualified merge-ready PR and survive the ci_wait restart.


## D-038 — Minimal prototype review and exact-head readiness

- **Authority:** D-037 and reviewer6160095319 permit T16 from verified main eb2fa779. Execute
  none/light, map standard/deep to light and log configured/executed levels; only admitted P0/P1
  block under the existing light location/confidence gate. No finding-verifier, inline threads,
  disputes, interdiff packets or parallel lenses in this prototype.
- **Durability and bounds:** a reviewer SessionMarker is the write-ahead dispatch fact, bound to
  head and owner command. An unknown result asks rather than repeating a paid turn. A COMMENT
  ReviewMarker carries its GateResult, with coherent blocker counts, in the same submission.
  A lost submission response recovers that receipt, without a second turn or review. Blocking
  evidence becomes the existing FeedbackMarker and resumes the existing builder. Two reviewer
  attempts per run; a question-bound retry grants exactly one further round. Gate/CI/publication
  reuse their existing code and limits. Legacy thread-based review receipts retain their routes.
- **Readiness:** immutable commit and local content must match the successful measured gate;
  current owned runs and the required-policy union are classified again. Head, branch, open state
  and mergeability are read from GitHub. The body has an atomic RunMarker effect receipt;
  draft state and observed labels recover their writes, then one exact-head ReadyMarker completes
  the run. A post-ready-API head check refuses a ready receipt for a changed head. Issue edits are
  reported against the frozen intake. No merge call is available or emitted.
- **Dependency ladder:** D-009/D-025 already selected the thin git CLI adapter. LangGraph provides
  orchestration, not local immutable git statistics or unified-hunk ranges. githubkit's remote
  API models do not supply ranges tied to the local isolated review checkout. Retain the approved
  CLI integration: commit_numstat adds immutable --numstat -z; a small stdlib regex/counter parser
  admits complete ordinary-path hunks. No dependency, lockfile change, new client or tool layer.
  Quoted paths, malformed/truncated hunks and a diff above262144bytes ask rather than guessing.
  Revisit these conservative limits from real run logs, not by silently truncating review evidence.
- **Test lifecycle:** reviewer6160199995 authorizes retaining the missing-registry assertion on an
  explicitly incomplete map and adding complete default compilation; the T15 fixture restores
  its review checkpoint after registry update, preserving all earlier assertions. A sibling fatal
  compilation traceback migration is authorized in comment6160234750, with assertions verbatim.
  These three are the complete list of lifecycle migrations; the standing authorization covers
  additional missing-default fixtures only. ReviewMarker retains the configured level as the
  monotonic floor, so a builder fix cannot lower a prior real review to none.
- **Qualification:** docs/validation/2026-10-14-t16.md will retain commands and actual results.
  All test services are fakes and local git. T16 requires no new live model turn; the full live
  CLI qualification remains T17/R1. U-1..U-7 and V-NEW/P3 carry in the single T17 backlog.


### D-038 R1 — Merge regression guard and unmatched critical locations

R1-F1 strengthens the static guard with injected SDK/GraphQL/REST/argv/constructed-name cases;
merge_state is an explicit read-only metadata allowance alongside the requested allowlist.
R1-F2 removes git's separator TAB and keeps quoted paths fail closed before dispatch. Unmatched
P0/P1 findings become recorded blockers requiring owner inspection, including lost-review-response
recovery. Verdict/explanation and dropped reasons are visible (X-3); W-3 needs a new adapter call
and carries with the other named non-blockers. No dependency, agent turn or live write added.

## D-039 — Minimal CLI and the R1 qualification boundary

- **Authority:** reviewer6160563054 authorizes one T17 branch stacked on T16 head2108897.
  Scope is run/report/doctor and family-calendar only. This supersedes the earlier optional-work
  landing note: local09c6c78 (R3-F6..F9) stays out of T17 and becomes a separate small PR after
  the first live run. No deferred hardening code is included.
- **CLI:** argparse produces a Pydantic request before configuration or capability access.
  make_context is the sole allow_live=True construction boundary for GitHub, git and Codex;
  it verifies the authenticated login against allowed owners. A per-issue flock prevents
  simultaneous dispatch; every run closes its owned harness. Report only reads local evidence.
  Exit0 success/merge_ready,2 waiting,3 blocked/closed,1 error. Argument/error text is redacted.
- **Doctor:** a small typed host port uses executable discovery and bounded subprocess status,
  not captured auth output. The pinned Codex CLI's login status uses exactly PATH/HOME/LANG/
  CODEX_HOME and the same profile lock as the harness, with no server or model turn. Writable
  state, gh login, git and configured tools are checked. New optional RepoConfig tool_minimums/
  tool_maximums carry numeric release-version bounds; existing configurations retain defaults.
- **Observed necessity:** family-calendar main fb473b5e2baf76f82d352dc39a26571a08bc75a5 requires
  Node>=24.20.0 and npm>=12.0.2,<13. The host's24.3.0/11.4.2 made an existence-only doctor
  falsely pass. Three test-first version cases now reject old tools and npm13, and accept the
  required versions. A prepared local toolchain, rather than changing checks or engines, enables
  actual CLI qualification. Both ordinary and bash-lc probes select24.20.0/12.0.2.
- **Operational toolchain evidence:** GitHub actions/node-versions release24.20.0-33034074684,
  node-24.20.0-darwin-arm64.tar.gz, SHA256
  1e637ea3c7d472dbc689609108f9aeff544a6a4ebf94f2534df3ac59c799a6b3 matched the release digest.
  Extracted with tar's data filter into ~/.lgcw/toolchains/node-24.20.0-darwin-arm64; npm12.0.2
  installed into that prefix. This is local operational state, not a workflow runtime dependency.
- **Dependency choice:** retain approved Python dependencies. argparse, fcntl, shlex, shutil,
  subprocess and tempfile are sufficient local interfaces; no CLI framework, process manager or
  new service client is needed. Existing SDK adapters remain the service boundary (D-008/D-034),
  and the T11 logger supplies reports. No pyproject/lockfile or runtime dependency change.
- **Family policy:** actual main CI and live run38441965084 verify CI/Node24.20.0,
  CI/Node26.8.1 and CI/Container build and smoke test. Setup npm ci, gate npm run check;
  all three jobs remain required. Lockfile sizing exclusion retains its supply-chain risk.
- **Live smoke:** explicit owner-created family-calendar issue selection launches the real CLI,
  observes newly appended ci_wait events, records public PR/dispatch/publication receipts and
  hashes of builder turns, then kills only its direct child and owned descendants. A retained
  intent/killed receipt prevents a second deliberate kill on retries. Resume must exit0, preserve
  prior receipts and turn files, have unique dispatch/push/review records, one exact-head ready
  receipt, an open non-draft PR and successful configured CI jobs. No fixture or manual patch
  substitutes for the actual issue execution. Unknown interruption outcome stops for inspection.
- **Qualification state:** doctor and read-only CI identity qualification pass without a paid
  model turn. Full R1 kill/resume remains unrun until Alex creates the issue. The source PR will
  say needs owner and retain the exact prerequisite; these checks do not claim complete execution.

### D-039 R1 — Doctor sandbox GitHub regression

PR7 review6161451205 requires a zero-model-turn pinned workspace-sandbox auth-status probe
with the harness's four-key environment. Doctor accepts only exit1 (credential denial); auth
success or an unavailable/timed-out probe fails the check. HostProbe uses -1 for unavailable
probes so failures cannot masquerade as denial. No raw auth output is returned or printed.
Reviewer authorization6161650797 permits FakeDoctor to return1 only for the exact new sandbox
argv, preserving every existing assertion. Explicit allowed/denied/unavailable cases are added.
This preserves the current-host D-004 observation, not a general home-isolation guarantee.
Y-1..Y-11 carry in the backlog; Y-10/Y-11 document the current gate/report behavior. No dependency.


## D-040 — First real execution: owner-delegated R1, with retained interruption proof

- **Authority:** Alex directly answered the prepared-issue/create-and-run question with
  “Proceed with real test!!! Exciting”. This overrides the earlier owner-creation reservation;
  [operator notice](https://github.com/bodegus/lg-code-workflow/pull/7#issuecomment-6165621941)
  records it. The builder created family-calendar#26 and ran merged sourceff51b95 unchanged.
- **Result:** lockfile-only proxy-addr2.0.7→2.0.8, PR27/head478db75, all three required jobs green,
  actual ci_wait SIGKILL/-9 and resume to one ready receipt. One earlier conservative publication
  head mismatch required verified operator retry6165770302; API lag is a hypothesis, not a verdict.
- **Boundary:** no target code edits, merge, default-branch push, test weakening or runtime change
  by the operator. The same builder receipt survived; one fresh light review executed for deep
  configuration under D-037. Post-ready rerun leaves durable snapshots unchanged. Human-adoption
  and recovered publication receipts refer to the same candidate, not additional commits.
- **Evidence:** [R1 inspection](runs/r1-proxy-addr-26.md) retains actual commands, cost, timeline,
  local receipt identities and hosted CI links. R1-OBS1..3 carry in the existing backlog; no new
  dependencies or speculative hardening. R2/R3 and their synthesis remain separate future work.

## D-041 — Owner response boundaries and P1 resumed workspace identity

- **Authority:** [owner decisions issue9](https://github.com/bodegus/lg-code-workflow/issues/9)
  requires a separate P1 harness fix before resuming R2. Real workflow execution uses merged
  harness code; no builder merges or pushes main. R1-OBS1/OBS4, CI policy migration, cron product
  changes and signature parsing are excluded from this fix.
- **Owner commands:** answers, protected approval and abort are owner-owned. The R2 restriction
  extended to all commands. Earlier four builder responses were unauthorized and remain in the
  R2 evidence; the later direct instruction “proceed - can you complete #3 I approve” narrowly
  delegates step3 after merged fixes and cron security corrections. Its
  [operator record](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6167192778)
  does not authorize earlier responses, merges, credentials or unmerged harness execution.
  Reviewer6167208491 accepts this scope and additionally requires the corrected protected diff
  and fingerprint on issue9 plus a reviewer verdict before delegated exact approval.
- **Cause:** SDK0.162.1 Thread.cwd is AbsolutePathBuf; str(value) produces root='path', not the
  filesystem path. Repeated cold resumes nested it into cwd. Use the typed `.root` value.
  FakeThread already returns the real SDK ThreadReadResponse model; previous tests did not
  assert the cwd passed to a resumed turn. New assertions cover that actual type and path.
- **Trusted identity:** CLI supplies run_directory(config, ref)/repo to CodexHarness. Fresh
  start may bind an otherwise unbound harness from its trusted SessionSpec; cold saved metadata
  cannot bind it. Every paid dispatch requires an existing absolute cwd resolving exactly to the
  bound worktree. Fresh read-only sessions bind their independent immutable checkout from the
  trusted SessionSpec; they cannot change the builder binding. Unknown cold read-only roots
  fail closed. Relative, missing, other existing or unbound builder workspaces fail closed as
  HarnessSessionLostError, preserving the graph's existing bounded handoff recovery.
- **Interface:** optional worktree constructor input leaves HarnessPort/SessionRef unchanged;
  standalone callers must supply it for cold resume. The existing live smoke's resumed harness
  receives its same root explicitly; every assertion remains unchanged. Canonical resolution
  permits platform path aliases without admitting another worktree. Role/network/deny-all
  settings, credential environment, SDK pin, assertions and timeouts remain unchanged.
- **Test first:** five new typed-SDK/identity cases failed before implementation (0.51s);
  the full harness boundary selection then passed25 (3.91s). Added live test checks the resumed
  turn_context's cwd, exact explicit writable path and an actual write after server restart.
  It is not run before merge under Alex's merged-code instruction; post-merge live proof is
  required before R2 resumes. No new dependency: approved SDK path model plus pathlib suffice.

Initial full local qualification passed1061 units,6 live deselected,95.32% (582.71s). Before
publishing, inspection of the real review node showed its immutable checkout differs from the
builder root. Two added reviewer/verifier checkout tests failed (0.49s); per-session trusted
read-only roots then pass together with the boundary suite (27 cases). The initial commit hook
was interrupted at101 passing tests to add this necessary regression; no commit/push occurred.
Final make check passes1063 units,6 live deselected,95.32% coverage (564.24s). The live check
remains pending on merged source; no R2 CLI was run on this branch.


Post-merge P1 qualification: PR11 merged as `0a1f3c6db44f19717df2244f1096fcce652c8e3f`.
From that exact merged source, `LGCW_LIVE=1 uv run pytest -m live
 tests/live/test_codex_smoke.py::test_restart_workspace_identity -s` passed (1 test,23.65s).
Both actual resumed cwd and the complete explicit writable-path set matched the temporary root;
`resume-proof.txt` contained `resumed`. Receipt: PR11/comment6168333557. No family-calendar CLI
or command was involved; the separate signed-command prerequisite still applies.

## D-042 — Blank-separated role signatures are command metadata, not authority

**Date:** 2026-10-14. **Status:** accepted for the R2 prerequisite in
[issue9/comment6167208491](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6167208491).

The contributor contract requires manual comments to end in `-builder` or `-reviewer`, while an
exact protected-path approval compares the parsed answer against `approve`. Previously a signed
answer retained that trailer in its payload and caused a redundant builder turn instead of
accepting the unchanged content-bound proposal. R2 observed this before the owner stopped the
unauthorized responses; correcting parsing does not authorize those historical actions.

Keep the existing first-nonempty-line command grammar. Remove exactly one terminal `-builder`,
`-reviewer` or `-owner` line only when a blank line separates it from the payload. Preserve all
other content, including adjacent signatures, quotes, unknown trailers and contradictory prose.
A role signature never grants permission: allowed GitHub authors and workflow-marker rejection
still run before command acceptance. Delegation remains an owner decision, and protected approval
still requires exact `approve` text bound to the question's paths and content fingerprint.

Tests first fail22 cases against the merged parser (19 already pass), then the same41-case
selection passes after the small normalization. Compiled-graph cases cover all three trailers
and prove an unchanged approved proposal publishes with one builder dispatch, not a second dispatch.
No dependency, port, schema, credential, sandbox, routing, assertion, fixture or timeout change.
The P1 live qualification above used merged source; no real command or CLI runs on this branch.

Signed-command full qualification: `make check` passes1092 units,6 live deselected,95.33%
coverage (741.71s). No real harness or family-calendar CLI ran from this unmerged branch.

## D-043 — R2: owner-delegated CI/dependency maintenance and weekly GitHub Action

- **Authority/scope:** Alex requested the next full issue-to-PR exercise, removing the two-Node
  matrix, consolidating every open Dependabot PR, adopting patch-only ranges, then adding a weekly
  cron GitHub Action to refresh dependencies and the lockfile. The builder created
  [family-calendar#28](https://github.com/bodegus/family-calendar/issues/28) with those criteria.
  Runtime agents implement target changes; the operator does not edit target code or merge PRs.
- **Policy migration:** replace CI/Node24.20.0 and CI/Node26.8.1 with stable CI/Quality; retain
  CI/Container build and smoke test. The issue requires the production audit unconditionally in
  the remaining quality lane. Node bounds become>=26.8.0,<26.9.0; npm bounds become>=12.0.2,<12.1.0 to match target engines~12.0.2.
  Quality/container are now qualified on exact target head2adfa1627a64696c91856f60f251463dc2768eae
  (run38553158311). Reviewer6166501403 authorized the narrow live fixture migration: only its
  run ID/docstring change, keeping both assertions, lane and required-check logic. Historical
  T17 specimen38441965084 belongs to the old Node24/26 policy; R1 run38546133890 remains
  recorded in the R1 inspection.
- **Version syntax:** npm uses `~x.y.z`, setup-node accepts26.8.x; the owner's `~>26.8` is intent,
  not valid npm syntax. Keep updated Actions commit SHAs because `uses:` cannot express tilde
  ranges. Docker must use a verified26.8 patch-line tag; other images remain outside this change.
  Inventory captures seven Dependabot heads, with its Node24 Docker proposal superseded by26.8.
  PR27's proxy-addr2.0.8 fix must survive regeneration while that PR remains unmerged.
- **Cron delivery:** weekly schedule plus workflow_dispatch in target source, one stable refresh
  branch/PR, no main push/approval/merge/release/deployment; avoid duplicate npm Dependabot work.
  Source validation, hosted CI and an actual cron/manual run are distinct evidence. A scheduled
  workflow must reach the default branch before scheduling starts.
- **Observed prerequisite:** repository Actions settings report read defaults and
  can_approve_pull_request_reviews=false, with no repository secrets configured. GitHub's
  [settings source](https://github.com/github/docs/blob/main/content/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository.md)
  documents that this flag controls GITHUB_TOKEN PR creation as well as approval. Owner approval
  is requested before changing it; the workflow itself never approves. Its design must also
  account for GitHub's
  [event restrictions](https://github.com/github/docs/blob/main/data/reusables/actions/actions-do-not-trigger-workflows.md)
  so refresh PRs receive CI (explicit workflow_dispatch is an exception).
- **Carry-forward:** reviewer6166068207 required R1-OBS4 (over-verification/cost) and R1-OBS5
  (delegated operator identity) in this next PR; both are in the backlog. Merged D-041 records
  the later owner/reviewer boundary decisions; D-042 is reserved for the separate signed-command fix.
  The R2 issue requests minimal local verification while retaining CI/container assertions.
  No new Python dependency or workflow runtime implementation change is introduced.

- **R2 outcome:** the final CLI used merged0a1f3c6 and one explicitly authorized retry6168470941,
  then fresh review and merge-ready (exit0). Four earlier unauthorized answers and two unmerged
  harness invocations remain breaches; later delegation does not retroactively authorize them.
  The full inspection is [R2](runs/r2-node26-weekly-deps-28.md).
- **Known defects and continuation:** the light reviewer missed both same-job fresh dependency
  execution/later PAT publication and the zero npm PR limit that suppresses minor/major proposals.
  No token exists or was created. Under reviewer6168424440, Alex merged the inert PR29 as
  22446af60dc545a696b25c0583bfa767b8ebf159 at12:48:50UTC. The decision requires an
  owner-approved R2b issue text and target main containing PR29 before the follow-up
  run. No PAT may be created until the isolation fix merges; hosted refresh is not qualified.
  The [draft](requests/r2b-safe-dependency-refresh.md) also carries the original minor/major/security
  policy. Non-build owner feedback and post-publication revocation are deferred, not patched here.

- **R2b authorization:** Alex explicitly approved creation and execution of the exact request at
  be1a3cb. Created family-calendar issue30 from that immutable body, with only the required
  contributor signature added. Its three allow paths authorize the named workflow, Dependabot
  configuration and necessary AGENTS guidance. The real run started from clean merged
  harness0a1f3c6 after target main contained22446af; unmerged PR12 code was not used. PR31 reached
  merge-ready on ea13244369eb49c0fb65086bacd26862b80b5618 at13:19:40UTC after a continuation
  from merged2ba0653. Exact-head Quality/container CI38569353866 and local gate passed;
  independent reviewer6169271911 accepted the isolation proposal. Credentialed publication
  and hosted missing-token behavior still require post-merge qualification. Issue approval does not grant credential provisioning or merge
  authority, nor authorize later answers beyond the listed protected scope.

- **Final policy live evidence:** read-only required-job identity test passed (1 test/1.75s) on
  run38553158311 with its Quality/container jobs. Doctor from merged2ba0653, reading this PR's
  configuration, accepted Node26.8.2 in>=26.8.0,<26.9.0 and npm12.0.2 in>=12.0.2,<12.1.0.
  Both adapters used measured live evidence; no assertion, lane or required-check logic changed.

- **Final source qualification:** full make check passes1092 units,6 live deselected,95.33%
  coverage in801.67s. This qualifies the final R2 policy/fixture migration together with merged
  P1 and signed-command prerequisites. The fixture change is only the reviewer-authorized run
  ID/docstring; both assertions and the live lane remain unchanged. Documentation-only changes
  used normal lint/render checks under Alex's exception; this mixed config/test PR uses full gates.

- **R2b inspection:** [run inspection](runs/r2b-safe-dependency-refresh-30.md) reads both actual
  Codex transcripts, the local event ledger, all27 fixture command receipts and GitHub records.
  One builder and one fresh reviewer consumed1839462 input tokens (1650048 cached),17674 output
  (3943 reasoning subset),617.62s agent time. One narrowly delegated retry recovered the repeated
  post-push head_moved; no repeated builder dispatch, manual answer/approval/abort, token creation
  or unmerged harness invocation. Independent verdict6169271911 accepted the exact protected
  proposal; residual transitive-lock data provenance and actual Dependabot security-patch behavior
  are explicitly unqualified follow-ups. Target PR31 remains owner-controlled; hosted no-token
  execution waits for main, and credentialed publication is separate.


## D-044 — Owner-delegated openclaw2-deploy#276 target and verification boundary

Alex explicitly delegates execution of that one issue, after a separate target-config PR is
reviewed and merged here. The target gates are exactly the requested Python3.12 uv-provisioned
whole test files (`test_github_issue_write.py`, `test_task_mcp.py`, xdist4, no cacheprovider) and
`uvx ruff@0.16.8 check ops tests`; setup is empty. Required identities CI/lint, CI/validate and
CI/unit match the target's current workflow. Protection/source/test/doc/risk globs follow the
owner's specification. No exclusions or known flaky patterns are introduced; pre-existing failure
policy retains the existing model's `note` setting. Python is selected per command through uv;
doctor checks uv/uvx availability rather than requiring the host interpreter itself to be3.12.
No runtime dependency or harness implementation change is included.

The outer builder does not implement the target patch. Merged lgcw graph code owns intake,
workspace, builder, gate, publication, CI and fresh review. Target scope is the two ops modules
and tests; argument refusals expose names only, descriptions spell out per-operation arguments,
and the target PR records its optional-title decision. Journal/request_id semantics stay intact.
The target reviewer separately dispatches native acceptance(scope=all) and requires its first
attempt to pass on the exact merge-ready head before merging. That acceptance is deliberately
outside lgcw's three configured required jobs. The final live ledger step after merge/release
also belongs to the target reviewer. No owner-answer, protected approval, abort, merge, release,
deployment, credential or ledger-write authority is inferred from this execution delegation.
Existing narrow verified-transient/head_moved retry policy remains binding, with evidence first.

Preflight on the unmodified issue finds five criteria: three checkbox items, the post-release
paragraph and the reviewer signature. The owner explicitly expects three. Preserve that issue
as the test input and repair checkbox-section extraction in a separate tested/merged PR before
any paid target run; this config PR records the finding and does not hide a parser change.

Local config qualification: `uv run lgcw doctor --repo bodegus/openclaw2-deploy` passes all
checks (gh/git/uv/uvx, owner login, sandbox login denial and dedicated Codex login). Full
`make check` passes1092 units,6 live deselected,95.33% coverage in535.01s. Real CI specimen
38967800886 reports lint,validate,unit all successful. No paid target turn has started.

## D-045 — Explicit checklists define criteria inside a named acceptance section

The unchanged openclaw2-deploy#276 has three `Done when` checkboxes followed by a separate
post-release reviewer paragraph and signature. The existing deterministic extractor freezes all
five as criteria, contradicting Alex's explicit three-criterion execution scope (D-044).
Prefer the named section's explicit checkbox items when present, including checked items as
before. Keep immediately wrapped text with its checkbox until a blank line, another list item or
heading. Ordinary prose and non-checkbox bullets in that section are then context, not additional
criteria. Sections without checkboxes retain their existing bullet/numbered/paragraph behavior;
the no-named-section fallback remains unchecked checkboxes only. Existing fence, HTML-comment,
indented-code and section-boundary filtering stays in place.

This is a small correction to the existing standard-library `re` parser, with no new dependency,
helper client, agent call, graph route or authorization rule. Four synthetic table cases fail on
the old extractor; a compiled-graph regression also fails because its durable RunMarker freezes
five criteria. The graph regression asserts that the original issue body is retained verbatim
in the snapshot. Do not rewrite the live issue, filter specific reviewer words, or use an owner
answer to conceal the extraction bug. Revisit if explicit acceptance criteria require mixed
checkbox and prose semantics; such a change needs a documented rule and regression evidence.

The config prerequisite PR14 merged as6c38551119087495e056a6129aed16daad06a42c. This source fix
must independently merge before running the paid target workflow. Only pure local extraction and
fake-port tests run on this branch; no live target turn is authorized from unmerged harness code.

Qualification: all five final regressions fail on the original parser (5 failed,56 deselected,
0.55s). All61 focused parser/intake-graph cases pass (21.98s). Full `make check` passes1097 units,
6 live deselected,95.34% coverage (568.10s), with100% coverage of the intake module. The initial
graph test incorrectly assumed one RunMarker; inspection of open_pr:164,179 proves the intended
issue/PR copies. The final test requires both copies, their identical contents and both unchanged
snapshots, and was independently re-proved red on the original parser. Existing tests stay intact.

## D-046 — Bounded complete path scan for the OpenClaw baseline

The first real OC2-276 run used clean merged main9e9e7ff. Intake correctly froze three criteria;
open_pr failed in GitWorkspace.prepare/_safe_links because Git's NUL-delimited all-path listing
was65,756 bytes, exceeding ordinary subprocess capture's65,536-byte bound. The existing refusal
is correct: clipped metadata cannot drive filesystem checks. The clean checkout remains at
4297cd11540bfb0022efb146f5e531b0e10a55d4, with no remote task branch, PR or paid agent turn.
Evidence: the run's events.jsonl:10–15 and the
[bootstrap failure receipt](https://github.com/bodegus/openclaw2-deploy/issues/276#issuecomment-6227756857).

Extend the existing standard-library subprocess capture with an explicit metadata_stdout flag,
selecting a fixed1MiB stdout ceiling. Only the complete _safe_links listing opts in. Stderr,
ordinary command logs and every other Git call retain64KiB capture. Both modes redact before
clipping, bound redaction expansion, mark incomplete output and kill owned descendants as before.
_checked still refuses a truncated stream; _paths still refuses redacted/ambiguous names. This
adds no dependency, service client, agent step, graph route, global-config setting or arbitrary
caller-selected limit. One1MiB path scan comfortably covers this baseline while keeping memory
bounded; a larger scan is refused rather than silently skipping paths. Revisit if real task
baselines exceed this separate bound; never bypass symlink checks or parse a clipped list.

Red-first synthetic local repositories reproduce preparation failure with >64KiB of tracked
paths and an escaping symlink sorted at the end. The fix must allow the complete safe baseline
and reject that late symlink. Subprocess tests prove metadata stdout completeness, unchanged
stderr bounds, and truncation after either raw overflow or redaction expansion. Existing64KiB
capture, credential, timeout, untracked-list truncation and symlink assertions stay unchanged.

The paused ask is node_error, outside issue9's delegated transient/head_moved policy. Alex then
explicitly requested "can you try again to complete the task with the workflow"; the target
issue comment records authorization for one retry of this current bootstrap failure only after
this fix independently merges. No answer, protected approval, abort, merge, native acceptance,
release, deployment or broader deterministic retry is authorized. Keep the original issue and
intake snapshot; never erase the failure or run this branch as the live harness.

A read-only local adapter check on the unchanged workflow checkout confirms the boundary:
ordinary stdout capture returns65,536 bytes/truncated=true; explicit metadata capture returns
all65,756 bytes/1,523 paths/truncated=false. It uses no token, network, controller run or target
mutation. Synthetic focused tests pass56 cases/15.76s; all five new cases were first observed
failing on the old implementation (5 failed,22 deselected/1.25s).

Full `make check` passes1102 units,6 live deselected,95.34% coverage in464.45s. Lint,
format and strict mypy pass; all existing bounded-capture and workspace assertions remain intact.
