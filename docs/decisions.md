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
