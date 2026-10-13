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
