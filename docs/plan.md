# lg-code-workflow Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task by task; in this repo the
> `building-plan-tasks` skill wraps either. Steps use checkbox (`- [ ]`) syntax; tick them in the
> same PR. One task per PR, built and proven locally by the builder agent, reviewed and merged by the
> reviewer agent (AGENTS.md "Roles and merge authority").

**Goal:** a `lgcw` command that takes a GitHub issue to a merge-ready PR on the owner's Mac, records
every decision on the PR, and leaves a run folder and report detailed enough to study.

**Architecture:** a LangGraph `StateGraph` whose nodes are plain async code behind three ports
(GitHub via githubkit, git via the `git` CLI, Codex via the official Python SDK); the LLM runs only
in the build, review and verify-finding agent steps; every run starts by reconciling from the PR's
markers, so GitHub is the durable state.

**Tech Stack:** Python 3.13, uv, hatchling, LangGraph 1.2, `openai-codex` 0.162.1, githubkit
0.16.1, Pydantic v2, pytest + pytest-asyncio + pytest-cov, ruff, mypy strict, pre-commit.

**Spec:** [design.md](design.md) (read it first), decisions in [decisions.md](decisions.md),
background in [research/README.md](research/README.md).

## Phase 1 prototype priority (owner decision, 2026-10-14)

[Reviewer-relayed owner decision6159291007](https://github.com/bodegus/lg-code-workflow/pull/4#issuecomment-6159291007)
supersedes the former T16/T17 scope: prove one real issue end to end, then harden from logs.
Before merge, fix P0/P1 and security-relevant P2s (credentials, protected paths, owner commands,
wrong bytes and impostor CI). Other P2/P3 findings go in the single Hardening backlog under T17.
One verifier per fix round; keep fixes small and report a fix exceeding about300lines before
building it. T14 df82dc9 remains frozen under verification; T16 may start stacked on T15 only
after the signed and independently verified T14 merge. D-037 records the revised scope.

## Global Constraints

- Python `>=3.13`; build backend hatchling; package `lgcw` under `src/`; console script `lgcw = "lgcw.cli:main"`.
- Runtime dependencies exactly: `langgraph>=1.2.15,<1.3`, `openai-codex==0.162.1`, `openai-codex-cli-bin==0.162.1` (D-034), `githubkit==0.16.1`, `pydantic>=2.12`. Any other runtime dependency needs a `choosing-dependencies` entry in decisions.md in the same PR.
- Dev dependencies: `pytest>=8.4`, `pytest-asyncio>=1.4`, `pytest-cov>=5`, `ruff`, `mypy`, `pre-commit`.
- ruff: `line-length = 100`, `target-version = "py313"`, lint `select = ["E","F","I","N","W","UP","B"]`; mypy `strict = true`, `plugins = ["pydantic.mypy"]`.
- pytest: `asyncio_mode = "auto"`, `addopts = "--strict-markers --strict-config"`, markers `unit` and `live`, exactly one per test; live tests run only with `LGCW_LIVE=1`.
- Coverage gate 90% lines on `src/lgcw`, omitting `src/lgcw/harness/codex.py` and `src/lgcw/github/client.py`.
- Marker text: `<!-- lgcw:v1 ` + compact JSON + ` -->`; `flow_version = 1`.
- Branch `lgcw/issue-<n>`; labels `lgcw:active`, `lgcw:waiting`, `lgcw:merge-ready`, `lgcw:blocked`, owner overrides `lgcw:review-none|light|standard|deep`.
- `LGCW_HOME` default `~/.lgcw`; Codex home `<LGCW_HOME>/codex`; runs `<LGCW_HOME>/runs/<owner>__<repo>__<n>/`; mirrors `<LGCW_HOME>/mirrors/<owner>__<repo>.git`.
- Limits defaults: `gate_fix_rounds=2`, `ci_fix_rounds=3`, `reruns_per_head=2`, `reruns_per_pr=5`, review fix rounds light 1 / standard 2 / deep 2, `ci_start_grace_s=600`, `ci_deadline_s=5400`, poll 15 s doubling to 120 s, `context_restart_ratio=0.6`.
- Agent node timeouts (run / idle seconds): build 3600/600, review 1200/300, verify 300/120.
- Review thresholds: light `< 100` changed lines and `< 8` files; standard 100–499 lines or ≥ 8 files; deep ≥ 500 lines or any risk class or a new dependency.
- Trimmed CI log ≤ 8,192 bytes per job and ≤ 16,384 bytes in total; PR body ≤ 60,000 characters.
- No code path calls a merge endpoint or the `mergePullRequest` mutation.
- Codex app-server environment exactly `PATH`, `HOME`, `LANG`, `CODEX_HOME`; `approval_mode=deny_all` on every turn and the complete role sandbox/network policy immediately before each turn (D-034).

## Review Focus

1. **The owner pushes to the PR branch mid-run.** Expect `ask` ("head moved"), never a push over it. Tests: T12 `test_next_step_head_moved_asks`, T16 `test_review_after_human_push_asks`.
2. **A comment carries a forged marker or a `/lgcw` command from someone else.** Expect it ignored: ledger entries need the workflow login and a marker; commands need an allowed author and no marker. Test: T3 `test_forged_marker_and_foreign_command_ignored`.
3. **Codex login expires or quota runs out mid-turn.** Expect `ask` with the re-login or reset time, and no push. Test: T14 `test_auth_error_asks_without_push`.
4. **A required check never reports** (path filter, disabled workflow). Expect `missing` after the grace period and `ask`, not an endless wait. Test: T6 `test_classify_missing_after_grace`.
5. **The issue is edited after pickup.** Expect the snapshot to be used and the merge-ready summary to say the issue changed. Test: T16 `test_merge_ready_notes_issue_edit`.

## Shared names (binding across tasks)

| Name | Module | Defined in |
|---|---|---|
| `Strict`, `strict_json_schema`, `SchemaNotStrictError` | `lgcw.models.base` | T1 |
| `WorkflowConfig`, `RepoConfig`, `Limits`, `RequiredCheck`, `RiskClass`, `ReviewThresholds` | `lgcw.models.config` | T1 |
| `IssueRef`, `IssueSnapshot`, `IntakeResult` | `lgcw.models.issue` | T1 |
| `PrSnapshot`, `IssueComment`, `ReviewThread`, `ThreadComment`, `ReviewCommentDraft`, `RunView`, `JobView` | `lgcw.models.github` | T1 |
| `PrReview` (submitted review receipt; D-020) | `lgcw.models.github` | T4 |
| `Marker` (union), `RunMarker`, `SessionMarker`, `PushMarker`, `CiMarker`, `ReviewMarker`, `FindingMarker`, `AskMarker`, `AckMarker`, `ReadyMarker`, `BlockedMarker`, `LedgerEntry`, `PrLedger`, `Command`, `LedgerCounts` | `lgcw.models.ledger` | T1; `PrLedger` methods and `LedgerCounts` T3 |
| `BuildHandoff`, `Decision`, `AcceptanceItem`, `FileNote`, `TestRun`, `Risk`, `Disposition` | `lgcw.models.handoff` | T1 |
| `ReviewLevel`, `Lens`, `ReviewVerdict`, `ReviewFinding`, `CodeLocation`, `LineRange`, `FindingCheck`, `LevelDecision`, `GatedFinding`, `GateResult`, `DiffStat`, `FileChange`, `LensVerdict` | `lgcw.models.review` | T1 |
| `CiStatus`, `CiClass`, `CiAction`, `CiDecision`, `CiHistory` | `lgcw.models.ci` | T1 |
| `Role`, `SessionSpec`, `SessionRef`, `TurnInput`, `Usage`, `TurnOutcome` | `lgcw.models.harness` | T1 |
| `Step`, `RunOutcome`, `Feedback`, `PendingAsk`, `RunState` | `lgcw.models.state` | T1 |
| `GitHubPort`, `TokenProvider` | `lgcw.github.port` | T4 |
| `WorkspacePort`, `WorkspaceInfo`, `CommandResult`, `PushAuth`, `PushRejectedError` | `lgcw.git.port` | T8 |
| `GitResult`, `git` | `lgcw.git.run` | T8 |
| `HarnessPort`, `HarnessError` family | `lgcw.harness.port`, `lgcw.harness.errors` | T9 |
| `Clock`, `SystemClock` | `lgcw.clock` | T1 |
| `redact` (D-021: brought forward for T5 token safety) | `lgcw.runlog` | T5 |
| `RunLog`, `render_report` | `lgcw.runlog` | T11 |
| `RunContext`, `ReconcileView`, `ReconcileOutcome`, `next_step`, `build_graph`, `run_issue` | `lgcw.graph` | T12 |
| `FakeGitHub`, `FakeHarness`, `FakeClock` | `tests.fakes` | T4, T9, T1 |

---

## Phase 1a — build

### Task T0: Project skeleton and toolchain

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `Makefile`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.python-version` (`3.13`)
- Create: `src/lgcw/__init__.py` (`__version__ = "0.1.0"`), `src/lgcw/py.typed`
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/unit/test_package.py`, `tests/unit/test_lanes.py`

**Interfaces:**
- Produces: `lgcw.__version__: str`; markers `unit`, `live`; autouse fixture `isolated_env` (sets `LGCW_HOME` to `tmp_path/"lgcw"`, removes `GH_TOKEN`, `GITHUB_TOKEN`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_HOME`, removes `LGCW_LIVE` for `unit` items while preserving opt-in for `live` items, sets `LANGSMITH_TRACING=false`); `pytest_collection_modifyitems` rejects a test without exactly one lane; `live` tests skipped unless `LGCW_LIVE=1`.

- [x] **Step 1: Write the failing tests**

```python
@pytest.mark.unit
def test_version() -> None:
    assert lgcw.__version__ == "0.1.0"

@pytest.mark.unit
def test_lane_marker_required(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(CONFTEST_SOURCE)          # copy of tests/conftest.py
    pytester.makepyfile("def test_no_lane(): pass")
    result = pytester.runpytest()
    result.stdout.fnmatch_lines(["*exactly one explicit execution lane*"])

@pytest.mark.unit
def test_isolated_env_removes_tokens() -> None:
    assert "GH_TOKEN" not in os.environ and os.environ["LANGSMITH_TRACING"] == "false"
```

- [x] **Step 2: Run them to see them fail** — `uv run pytest -m unit` → errors (no package, no conftest).
- [x] **Step 3: Create the project files.** `pyproject.toml` with the Global Constraints' versions, tool sections and coverage settings (`[tool.coverage.run] source = ["lgcw"]`, `omit` the two live adapters, `[tool.coverage.report] fail_under = 90`). `Makefile` targets: `setup` (`uv sync` + `uv run pre-commit install`), `lint` (`uv run ruff check src tests` and `uv run ruff format --check src tests`), `type` (`uv run mypy src tests`), `test` (`uv run pytest -m unit --cov=lgcw`), `check` (lint, type, test), `live` (`LGCW_LIVE=1 uv run pytest -m live`). Pre-commit: gitleaks, trailing-whitespace, end-of-file-fixer, check-toml, check-yaml, check-added-large-files, ruff check/format, mypy, `pytest -m unit`. CI workflow on `pull_request` and `push` to `main`: ubuntu-latest, `astral-sh/setup-uv`, `uv sync --locked`, `make check`.
- [x] **Step 4: Run** `uv sync && make check` → all pass, coverage report printed.
- [x] **Step 5: Commit** `chore: project skeleton, toolchain and test lanes`.

### Task T1: Core models and strict output schemas

**Files:**
- Create: `src/lgcw/models/{__init__,base,config,issue,github,ledger,handoff,review,ci,harness,state}.py`, `src/lgcw/clock.py`
- Create: `tests/unit/models/test_base.py`, `test_config_models.py`, `test_ledger_models.py`, `test_handoff.py`, `test_review_models.py`, `test_state.py`; `tests/fakes/__init__.py`, `tests/fakes/clock.py`

**Interfaces:**
- Produces (all `Strict` = `BaseModel` with `extra="forbid", frozen=True` unless noted):
  - `strict_json_schema(model: type[BaseModel]) -> dict[str, Any]`: model JSON schema; raises `SchemaNotStrictError` if any object has a property missing from `required`, a default, or `additionalProperties` not `false`.
  - `RequiredCheck(workflow: str, job: str)`; `RiskClass(name: str, globs: tuple[str, ...])`; `ReviewThresholds(light_max_lines: int = 99, standard_max_lines: int = 499, many_files: int = 8)`; `Limits` with the Global Constraints defaults (`review_fix_rounds: dict[ReviewLevel, int]`).
  - `RepoConfig(full_name, default_branch, allowed_authors: tuple[str, ...], setup: tuple[str, ...], gate: tuple[str, ...], required_checks: tuple[RequiredCheck, ...], protected_globs, excluded_globs, source_globs, tests_globs, docs_globs: tuple[str, ...], risk_classes: tuple[RiskClass, ...], known_flaky: tuple[str, ...] = (), pre_existing_policy: Literal["note", "ask"] = "note")`.
  - `WorkflowConfig(home: Path, codex_home: Path, model: str | None, builder_effort: str, reviewer_effort: dict[ReviewLevel, str], verifier_effort: str, limits: Limits, thresholds: ReviewThresholds, repos: dict[str, RepoConfig])`.
  - `IssueRef(repo: str, number: int)` with `IssueRef.parse("owner/repo#12")`; `IssueSnapshot(repo, number, title, body, author, state, labels: tuple[str, ...], updated_at: datetime, url, is_pull_request: bool = False)` (D-021: typed intake discrimination); `IntakeResult(status: Literal["ok", "incomplete", "rejected"], acceptance_criteria: tuple[str, ...], reason: str | None)`.
  - `PrSnapshot(number, node_id, url, state: Literal["OPEN", "CLOSED", "MERGED"], head_ref, head_sha, base_ref, is_draft: bool, mergeable: Literal["MERGEABLE", "CONFLICTING", "UNKNOWN"], merge_state: str, labels: tuple[str, ...])`; `IssueComment(id: int, author: str, body: str, created_at: datetime)`; `ThreadComment(id: int, author: str, body: str)`; `ReviewThread(node_id: str, is_resolved: bool, path: str, line: int | None, comments: tuple[ThreadComment, ...])`; `ReviewCommentDraft(path: str, line: int, start_line: int | None, body: str)`; `RunView(run_id, workflow, event, status, conclusion: str | None, head_sha, run_attempt: int, created_at: datetime | None = None)`; `JobView(job_id, run_id, workflow, name, status, conclusion: str | None, run_attempt, failed_steps: tuple[str, ...], annotations: tuple[str, ...], runner_name: str | None, url)`.
  - Markers (field `kind` is the discriminator; field lists in design §3.1): `RunMarker`, `SessionMarker`, `PushMarker`, `CiMarker`, `ReviewMarker`, `FindingMarker`, `AskMarker`, `AckMarker`, `ReadyMarker`, `BlockedMarker`; `Marker = Annotated[Union[...], Field(discriminator="kind")]`; `LedgerEntry(comment_id: int, created_at: datetime, where: Literal["issue", "pr", "thread", "review"], marker: Marker)`; `PrLedger(entries: tuple[LedgerEntry, ...])`; `Command(verb: Literal["answer", "retry", "abort"], text: str, comment_id: int, author: str)`.
  - Strict output models (no defaults): `Decision(decision, alternatives_rejected: list[str], reason, evidence)`, `AcceptanceItem(criterion, status: Literal["met", "partial", "not_met"], evidence)`, `FileNote(path, why)`, `TestRun(command, result: Literal["pass", "fail", "not_run"], note)`, `Risk(area, why)`, `Disposition(finding_id, decision: Literal["fixed", "wont_fix", "invalid"], note, paths: list[str])`, `BuildHandoff(status: Literal["done", "blocked", "partial"], summary: list[str], approach: str, decisions, assumptions: list[str], acceptance, files, tests, not_done: list[str], risks, open_questions: list[str], followups: list[str], dispositions: list[Disposition])`; `LineRange(start: int, end: int)`, `CodeLocation(absolute_file_path: str, line_range: LineRange)`, `ReviewFinding(title, body, confidence_score: float (0..1), priority: int (0..3), category: str, code_location: CodeLocation)`, `ReviewVerdict(findings: list[ReviewFinding], overall_correctness: Literal["patch is correct", "patch is incorrect"], overall_explanation: str, overall_confidence_score: float)`, `FindingCheck(valid: bool, introduced_by_change: bool, reason: str)`.
  - Policy models: `ReviewLevel = Literal["none", "light", "standard", "deep"]`, `Lens = Literal["general", "security", "tests", "ops"]`, `LevelDecision(level, lenses: tuple[Lens, ...], reasons: tuple[str, ...], fix_round_cap: int)`, `FileChange(path, added: int, deleted: int)`, `DiffStat(files: tuple[FileChange, ...])` with `changed_lines` and `paths` properties, `LensVerdict(lens: Lens, verdict: ReviewVerdict)`, `GatedFinding(id: str, lens: Lens, path: str, finding: ReviewFinding, blocking: bool, reason: str)`, `GateResult(blocking, nonblocking, dropped: tuple[GatedFinding, ...])`.
  - CI: `CiStatus`, `CiClass`, `CiAction = Literal["wait", "rerun", "fix", "proceed_note", "ask"]`, `CiDecision(head_sha, status, klass: CiClass | None, action, job: JobView | None, fingerprint: str | None, note: str)`, `CiHistory(reruns_by_head: dict[str, int], reruns_total: int, ci_fix_rounds: int, fingerprints: tuple[str, ...], reruns_by_class_head: dict[str, dict[CiClass, int]] = {})`.
  - Harness: `Role = Literal["builder", "reviewer", "verifier"]`, `SessionSpec(role, cwd: Path, sandbox: Literal["workspace_write", "read_only"], network: bool, effort: str, model: str | None)`, `SessionRef(session_id: str, role: Role)`, `TurnInput(skill: str, text: str, data: str | None, data_label: str | None)`, `Usage(input_tokens: int, cached_input_tokens: int, output_tokens: int, reasoning_output_tokens: int, context_window: int | None)`, `TurnOutcome[M](session_id: str, output: M, usage: Usage, duration_s: float, rollout_path: Path | None)` (generic `BaseModel`).
  - State (mutable model, `frozen=False`): `Step = Literal["reconcile", "intake", "open_pr", "build", "gate", "publish", "ci_wait", "review", "merge_ready", "ask", "blocked", "end"]`, `RunOutcome = Literal["merge_ready", "waiting", "blocked", "closed", "error"]`, `Feedback(source: Literal["gate", "ci", "review", "owner", "no_changes"], summary: str, data: str | None, fingerprint: str | None)`, `PendingAsk(question: str, return_to: Step, code: str)`, `RunState` (fields: `issue_ref`, `issue`, `intake`, `branch`, `base_sha`, `pr`, `ledger`, `threads`, `builder_session`, `handoff`, `feedback`, `ci`, `level`, `gated`, `last_reviewed_sha`, `ask`, `owner_answer`, `next_step`, `outcome`; counters are derived, not stored).
  - `Clock` Protocol (`now() -> datetime`, `async sleep(seconds: float) -> None`), `SystemClock`; `tests.fakes.clock.FakeClock(start: datetime)` whose `sleep` advances `now()`.

- [x] **Step 1: Write the failing tests**

```python
def test_strict_schema_build_handoff_is_strict():
    s = strict_json_schema(BuildHandoff)
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(BuildHandoff.model_fields)

def test_strict_schema_rejects_defaults():
    class Loose(Strict):
        x: int = 1
    with pytest.raises(SchemaNotStrictError):
        strict_json_schema(Loose)

def test_models_forbid_extra():
    with pytest.raises(ValidationError):
        IssueRef.model_validate({"repo": "a/b", "number": 1, "x": 1})

def test_marker_union_discriminates():
    entry = LedgerEntry.model_validate({"comment_id": 1, "created_at": NOW, "where": "pr",
        "marker": {"kind": "push", "head_sha": "a" * 40, "source": "build", "round": 1}})
    assert isinstance(entry.marker, PushMarker)

def test_finding_bounds():
    with pytest.raises(ValidationError):
        ReviewFinding.model_validate(FINDING | {"priority": 4})

def test_limits_defaults():
    assert Limits().review_fix_rounds == {"none": 0, "light": 1, "standard": 2, "deep": 2}

def test_issue_ref_parse():
    assert IssueRef.parse("bodegus/family-calendar#12") == IssueRef(repo="bodegus/family-calendar", number=12)
```
(all marked `@pytest.mark.unit`)

- [x] **Step 2: Run** `uv run pytest tests/unit/models -m unit` → FAIL (import errors).
- [x] **Step 3: Implement the models** in the listed modules; `strict_json_schema` walks `$defs` and every object schema.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(models): core Pydantic models and strict output schemas`.

### Task T2: Configuration loading

**Files:**
- Create: `src/lgcw/config.py`, `config/workflow.toml`, `config/repos/bodegus__oc2-publish-sandbox.toml`
- Create: `tests/unit/test_config.py`, `tests/fixtures/config/` (small TOML cases)

**Interfaces:**
- Consumes: `WorkflowConfig`, `RepoConfig` (T1).
- Produces: `load_config(root: Path, *, home: Path | None = None) -> WorkflowConfig` (reads `root/config/workflow.toml` and every `root/config/repos/*.toml`; `home` defaults to `$LGCW_HOME` or `~/.lgcw`); `WorkflowConfig.repo(full_name: str) -> RepoConfig` raising `UnknownRepoError`; `ConfigError` for a file name that does not match `full_name` (`owner__repo.toml`).

- [x] **Step 1: Write the failing tests**: `test_load_defaults` (limits equal the Global Constraints), `test_home_from_env` (`LGCW_HOME` → `config.codex_home == home / "codex"`), `test_repo_filename_must_match`, `test_unknown_key_rejected`, `test_unknown_repo_raises`, `test_sandbox_repo_config_valid`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** with `tomllib` and `model_validate`; sandbox config: `setup = []`, `gate = []`, `required_checks` from its `ci.yml` job names (read the workflow file; record the names).
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(config): load workflow and per-repo configuration`.

### Task T3: Markers, commands and the ledger (pure)

**Files:**
- Create: `src/lgcw/ledger/{__init__,markers,commands,ledger}.py`
- Create: `tests/unit/ledger/test_markers.py`, `test_commands.py`, `test_ledger.py`

**Interfaces:**
- Consumes: marker models, `IssueComment`, `ReviewThread`, `Command` (T1).
- Produces: `render_marker(marker: Marker) -> str`; `parse_markers(body: str) -> list[Marker]` (one complete trailing marker; multiple complete markers, malformed JSON or unknown kind are ignored, never raises); `strip_markers(body: str) -> str`; `parse_command(body: str) -> tuple[Literal["answer", "retry", "abort"], str] | None` (first non-empty line `/lgcw <verb> [text]`; text = rest of the line plus following lines); `fingerprint(*parts: str) -> str` (sha256 hex, first 16 chars); `build_ledger(issue_comments: Sequence[IssueComment], pr_comments: Sequence[IssueComment], threads: Sequence[ReviewThread], workflow_login: str, *, reviews: Sequence[PrReview] = ()) -> PrLedger`; `owner_commands(comments: Sequence[IssueComment], allowed_authors: Collection[str], after_comment_id: int) -> list[Command]`; `PrLedger` methods `latest(kind) -> LedgerEntry | None`, `of_kind(kind) -> list[LedgerEntry]`, `pending_ask() -> LedgerEntry | None` (an `ask` without a later `ack` of the same `seq`), `last_push() -> PushMarker | None`, `ci_for(head_sha) -> CiMarker | None`, `reviews_for(head_sha) -> list[ReviewMarker]`, `counts() -> LedgerCounts` (gate/ci/review fix rounds, reruns per head and total, review rounds, fresh restarts, retry grants by step/code — all derived from `push`, `ci`, `review`, `session`, `ask`, `ack` markers).

- [x] **Step 1: Write the failing tests**

```python
def test_marker_round_trip_with_hostile_text():
    m = BlockedMarker(kind="blocked", reason="x --> <!-- y")
    assert parse_markers("Stopped.\n" + render_marker(m)) == [m]

def test_forged_marker_and_foreign_command_ignored():
    forged = comment(1, author="mallory", body="hi " + render_marker(READY))
    ours = comment(2, author="bodegus", body="ok " + render_marker(PUSH))
    led = build_ledger([], [forged, ours], [], workflow_login="bodegus")
    assert [e.comment_id for e in led.entries] == [2]
    cmds = owner_commands([comment(3, "mallory", "/lgcw abort"),
                           comment(4, "bodegus", "/lgcw abort " + render_marker(PUSH))],
                          allowed_authors={"bodegus"}, after_comment_id=0)
    assert cmds == []

def test_parse_command_answer_multiline():
    assert parse_command("/lgcw answer use UTC\nand ISO dates") == ("answer", "use UTC\nand ISO dates")

def test_pending_ask_cleared_by_ack():
    led = ledger_of(ask(seq=1), ack(seq=1, command_id=9), ask(seq=2))
    assert led.pending_ask().marker.seq == 2

def test_counts_derived_from_markers():
    led = ledger_of(push("a", "initial"), push("b", "build"), ci("b", action="fix"),
                    push("c", "ci_fix", round=1), ci("c", action="rerun"))
    c = led.counts()
    assert (c.ci_fix_rounds, c.reruns_by_head["c"], c.reruns_total) == (1, 1, 1)
```

- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.** `render_marker` uses `json.dumps(..., separators=(",", ":"), ensure_ascii=True)` and then replaces every `--` in that text with a hyphen followed by the JSON escape for a hyphen (backslash, `u002d`), which is valid inside JSON strings and never needed elsewhere in compact JSON, so ` -->` can never occur inside a marker; `parse_markers` uses the regex `<!-- lgcw:v1 (\{.*?\}) -->` and `TypeAdapter(Marker)`.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(ledger): markers, owner commands and the PR ledger`.

### Task T4: GitHub port, fake and renderers

**Files:**
- Create: `src/lgcw/github/{__init__,port,render}.py`, `src/lgcw/github/templates/{pr_body,question,event}.md`
- Create: `tests/fakes/github.py`, `tests/unit/github/test_render.py`, `tests/unit/github/test_fake_github.py`, `tests/contract/__init__.py`, `tests/contract/github_scenarios.py`

**Interfaces:**
- Produces `GitHubPort` (Protocol, all `async`): `viewer_login() -> str`; `get_issue(ref: IssueRef) -> IssueSnapshot`; `list_issue_comments(repo: str, number: int) -> list[IssueComment]` (also PR conversation comments); `create_issue_comment(repo, number, body) -> IssueComment`; `find_open_pr(repo, head_branch) -> PrSnapshot | None`; `get_pr(repo, number) -> PrSnapshot` (GraphQL: head, draft, mergeable, merge state); `create_draft_pr(repo, head, base, title, body) -> PrSnapshot`; `update_pr_body(repo, number, body) -> None`; `set_labels(repo, number, add: Sequence[str], remove: Sequence[str]) -> None`; `mark_ready(pr_node_id: str) -> None`; `create_review(repo, number, commit_sha, body, comments: Sequence[ReviewCommentDraft]) -> int` (event `COMMENT`); `list_review_threads(repo, number) -> list[ReviewThread]`; `list_pr_reviews(repo, number) -> list[PrReview]` (D-020: review-body recovery, including no-inline reviews); `reply_to_review_comment(repo, number, comment_id, body) -> None`; `resolve_thread(node_id, reason: Literal["ADDRESSED", "WONT_FIX", "INVALID"]) -> None`; `runs_for_sha(repo, head_sha) -> list[RunView]`; `jobs_for_run(repo, run_id) -> list[JobView]` (annotations filled for failed or cancelled jobs); `job_log(repo, job_id) -> str`; `rerun_failed_jobs(repo, run_id) -> None`; `latest_base_jobs(repo, workflow, branch) -> list[JobView]`. `TokenProvider` Protocol: `token() -> str`.
- Produces `FakeGitHub(GitHubPort)`: in-memory issues, comments (ids increase), PRs, threads, labels; `script_runs(head_sha, timeline: list[tuple[float, list[RunView], list[JobView]]])` keyed to `FakeClock` time; `calls: list[tuple[str, dict]]`; `fail_after(method: str, n: int, exc: Exception)` for crash tests; `merge` does not exist.
- Produces: `PrReview(id: int, author: str, body: str, head_sha: str | None, submitted_at: datetime)` in `models/github.py` (D-020).
- Produces renderers: `render_pr_body(issue: IssueSnapshot, handoff: BuildHandoff | None, status: PrStatus) -> str` (`PrStatus(checklist: tuple[tuple[str, bool], ...], ci: str, review: str, notes: tuple[str, ...])`); `render_event(text: str, marker: Marker) -> str`; `render_question(question: str, marker: AskMarker) -> str` (lists the three commands).

- [x] **Step 1: Write the failing tests**: `test_pr_body_starts_with_fixes`, `test_pr_body_capped_at_60000` (a handoff with 5,000 decisions renders ≤ 60,000 chars and says "more omitted"), `test_pr_body_model_text_between_markers`, `test_event_ends_with_marker`, `test_question_lists_commands`, and contract scenarios in `tests/contract/github_scenarios.py` (`scenario_issue_comments_round_trip`, `scenario_draft_pr_then_ready`, `scenario_review_thread_reply_and_resolve`) run here against `FakeGitHub` via `tests/unit/github/test_fake_github.py`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** the Protocol, renderers (templates via `string.Template`) and the fake.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(github): port, renderers and in-memory fake`.

### Task T5: GitHub client (githubkit) and token

**Files:**
- Create: `src/lgcw/github/client.py`, `src/lgcw/github/token.py`, `src/lgcw/live.py`
- Create: `tests/unit/github/test_token.py`, `tests/unit/github/test_client_guard.py`, `tests/unit/github/test_mapping.py`, `tests/fixtures/github/*.json` (synthetic payloads), `tests/live/test_github_contract.py`

**Interfaces:**
- Consumes: `GitHubPort` (T4), models (T1).
- Produces: `require_live(component: str, allow_live: bool) -> None` raising `LiveAdapterDisabledError` unless `allow_live` or `LGCW_LIVE=1`; `GhCliTokenProvider(TokenProvider)` (`gh auth token`, cached 50 minutes, never logged); `GitHubClient(token_provider: TokenProvider, *, allow_live: bool = False)` implementing every `GitHubPort` method with githubkit (REST; GraphQL for `get_pr`, `mark_ready`, `list_review_threads`, `resolve_thread`); pure mapping functions `pr_from_graphql(data: dict[str, Any]) -> PrSnapshot`, `job_from_rest(job: dict[str, Any], annotations: list[dict[str, Any]]) -> JobView`, `thread_from_graphql(node: dict[str, Any]) -> ReviewThread`.

- [x] **Step 1: Write the failing tests**: `test_client_refuses_without_live` (constructing `GitHubClient(..., allow_live=False)` raises), `test_token_from_fake_gh` (a fake `gh` script on a temp `PATH` prints a token; the provider returns it and `redact` of the log line hides it), mapping tests over the synthetic fixtures (`test_pr_from_graphql_maps_mergeable`, `test_job_from_rest_timeout_annotation`), and the live contract test running the three T4 scenarios against owner-approved `bodegus/family-calendar` (D-032) (`@pytest.mark.live`).
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.** Mutating calls wait at least 1 s between each other (GitHub best practice); node retry policies (T12) handle transient errors, so the client does not retry 4xx.
- [x] **Step 4: Run** `make check` → PASS; then `LGCW_LIVE=1 uv run pytest tests/live/test_github_contract.py -m live` → PASS (the builder runs it; output pasted in the PR).
- [x] **Step 5: Commit** `feat(github): githubkit client behind GitHubPort`.


T5 live qualification (D-032/D-033): the original D-022 fixture attempt failed with HTTP 410 and was cleaned up. The owner-approved family-calendar target now passes the exact named live command: 1 passed in 32.76s. Fixture issue #24 and PR #25 are closed, branch deleted, and main unchanged; any-state lookup finds the closed PR after deletion. Local make check: 538 unit tests, strict mypy, 97.66% coverage. This qualifies the named adapter contract, not a complete workflow or Codex harness.

### Task T6: CI policy — classifier, decision table, log trimming (pure)

**Files:**
- Create: `src/lgcw/ci/{__init__,classify,decide,logs,patterns}.py`
- Create: `tests/unit/ci/test_classify.py`, `test_decide.py`, `test_logs.py`, `tests/fixtures/ci/` (synthetic `JobView` JSON and a generated 2,900-line log)

**Interfaces:**
- Consumes: `RequiredCheck`, `Limits`, `PrSnapshot`, `RunView`, `JobView`, `CiDecision`, `CiHistory` (T1).
- Produces: `classify(required: Sequence[RequiredCheck], runs: Sequence[RunView], jobs: Sequence[JobView], pr: PrSnapshot, pushed_sha: str, pushed_at: datetime, now: datetime, limits: Limits) -> tuple[CiStatus, tuple[JobView, ...]]` (a required job `cancelled` with the timeout annotation counts as `failure`; without it, `blocked`); `decide(status: CiStatus, failing: Sequence[JobView], runs: Sequence[RunView], base_jobs: Sequence[JobView] | None, history: CiHistory, diff_paths: Sequence[str], log_tails: Mapping[int, str], repo: RepoConfig, limits: Limits, *, pushed_sha: str) -> CiDecision` (design §8 rows, top to bottom); `trim_job_log(raw: str, failed_steps: Sequence[str], max_bytes: int = 8192) -> str`; `failure_fingerprint(workflow: str, job: str, step: str, first_error: str) -> str` (digits and paths normalised); regex constants in `patterns.py` (`TIMEOUT_ANNOTATION`, `INFRA_PATTERNS`, `RESOURCE_PATTERNS`, `ERROR_START`).

- [x] **Step 1: Write the failing tests** (table-driven):

```python
@pytest.mark.parametrize("case", CLASSIFY_CASES, ids=lambda c: c.name)
def test_classify(case): assert classify(**case.inputs)[0] == case.expected
# cases: no_runs_yet→pending, required_running→pending, all_green→success,
# required_failed→failure, cancelled_with_timeout_annotation→failure,
# cancelled_superseded→blocked, head_moved→head_moved, conflict→conflict,
# past_deadline→timeout

def test_classify_missing_after_grace():
    status, _ = classify(REQ, runs=[], jobs=[], pr=PR, pushed_sha=SHA,
                         pushed_at=T0, now=T0 + timedelta(seconds=601), limits=Limits())
    assert status == "missing"

@pytest.mark.parametrize("case", DECIDE_CASES, ids=lambda c: c.name)   # one per design §8 row
def test_decide(case): assert (decide(**case.inputs).klass, decide(**case.inputs).action) == case.expected

def test_rerun_caps():   # 2 per head, 5 per PR
    assert decide(**infra_case(history=CiHistory(reruns_by_head={SHA: 2}, reruns_total=2,
                  ci_fix_rounds=0, fingerprints=()))).action == "ask"

def test_trim_keeps_errors_and_caps_size():
    out = trim_job_log(BIG_LOG, failed_steps=["Run tests"])
    assert len(out.encode()) <= 8192 and "##[error]" in out and "\x1b[" not in out
```

- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** the three pure functions and the pattern table.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(ci): classifier, fix-or-move-on table and log trimming`.


T6 proof: missing CI modules produced three collection errors first. Final `make check` passed: 220 unit tests, 1 live deselected, strict mypy (61 files), lint/format, 99.78% coverage. D-023 records exact-head/class-history inputs and terminal qualification semantics. No live call is required for this pure task.

### Task T7: Review policy — diff stats, level picker, finding gate (pure)

**Files:**
- Create: `src/lgcw/review/{__init__,diffstat,level,gate}.py`
- Create: `tests/unit/review/test_diffstat.py`, `test_level.py`, `test_gate.py`

**Interfaces:**
- Consumes: `DiffStat`, `FileChange`, `LevelDecision`, `LensVerdict`, `GatedFinding`, `GateResult`, `Risk`, `RepoConfig`, `ReviewThresholds`, `Limits` (T1).
- Produces: `parse_numstat(text: str, excluded_globs: Sequence[str]) -> DiffStat` (binary files count as 1 line); `pick_level(diff: DiffStat, owner_labels: Sequence[str], builder_risks: Sequence[Risk], repo: RepoConfig, thresholds: ReviewThresholds, limits: Limits, *, previous: LevelDecision | None = None) -> LevelDecision` (first match in design §7; owner label wins; `previous` can only be raised); `finding_id(path: str, title: str, category: str) -> str`; `gate_findings(results: Sequence[LensVerdict], level: LevelDecision, ranges: Mapping[str, Sequence[LineRange]], repo_root: Path, known_ids: Collection[str]) -> GateResult`. Glob matching with `PurePosixPath.full_match`.

- [x] **Step 1: Write the failing tests** (table-driven): docs-only → `none`; 40 source lines → `light`; 120 lines → `standard` with lens `general`; source without tests → lenses include `tests`; `.github/workflows/ci.yml` → `deep` with `("general", "security", "tests")`; owner label `lgcw:review-light` on a deep change → `light`; a builder risk raises light → standard; `previous=deep` stays `deep`; gate: P1 inside range blocks, P1 outside range dropped, P2 at standard non-blocking, P2 `security` at deep blocking, confidence 0.6 at light non-blocking, a known id is not repeated.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(review): review levels and finding gate`.


T7 proof: three missing-module collection errors first; a new deep+ops regression failed with a fourth reviewer before the implementation fix. Final `make check`: 270 unit tests, 1 live deselected, strict mypy (68 files), lint/format, 99.53% coverage. D-024 records conservative manifests, owner-label/previous-depth precedence, confidence and lexical location admission. No live calls required.

### Task T8: Workspace — git wrapper and per-issue clone

**Files:**
- Create: `src/lgcw/git/{__init__,port,run,workspace}.py`
- Create: `tests/unit/git/test_run.py`, `tests/unit/git/test_workspace.py` (real `git`, a bare repo in `tmp_path` as `origin`)

**Interfaces:**
- Produces: `async git(*args: str, cwd: Path, env: Mapping[str, str] | None = None, timeout_s: float = 120) -> GitResult(argv: tuple[str, ...], code: int, out: str, err: str)` (always `-c core.hooksPath=/dev/null -c core.fsmonitor=false`, `GIT_TERMINAL_PROMPT=0`); `PushAuth(token: SecretStr)` with `env() -> dict[str, str]` producing `GIT_CONFIG_COUNT/KEY_0/VALUE_0` (`http.https://github.com/.extraheader`, `AUTHORIZATION: basic <base64(x-access-token:token)>`); `WorkspaceInfo(repo_dir: Path, branch: str, base_sha: str, resumed: bool)`; `CommandResult(ok: bool, command: str, code: int, tail: str, fingerprint: str | None, duration_s: float, log_path: Path)`; `PushRejectedError`; `WorkspacePort` Protocol and `GitWorkspace(home: Path, *, origin: Path | None = None, token_provider: TokenProvider | None = None, allow_live: bool = False)` (D-025) with `prepare(repo: RepoConfig, issue: IssueRef, branch: str) -> WorkspaceInfo`, `head_sha() -> str` (existing local commit for recovery; D-025), `run_commands(cwd: Path, commands: Sequence[str], timeout_s: float, log_path: Path) -> CommandResult`, `numstat(base_sha: str) -> str` (includes untracked files), `changed_paths(base_sha: str) -> tuple[str, ...]`, `commit_all(message: str, trailers: Mapping[str, str]) -> str | None`, `commit_empty(message: str) -> str`, `push(branch: str, expected_remote_sha: str | None, auth: PushAuth) -> str`, `diff_text(from_sha: str, to_sha: str, max_bytes: int) -> str`, `adopt_remote_head(branch: str) -> str`, `reviewer_checkout(head_sha: str, base_sha: str) -> Path`.

- [x] **Step 1: Write the failing tests**: `test_prepare_new_branch_from_default`, `test_prepare_resumes_existing_remote_branch`, `test_commit_all_returns_none_when_clean`, `test_push_lease_rejects_unexpected_remote` (raises `PushRejectedError`), `test_push_new_branch_rejected_if_exists`, `test_token_never_in_argv_or_config` (`"tok123" not in " ".join(result.argv)` and not in `.git/config`), `test_hooks_disabled` (a `pre-commit` hook that writes a file does not run), `test_reviewer_checkout_overlays_base_instructions` (head changed `AGENTS.md`; checkout shows base content), `test_run_commands_failure_tail_and_timeout`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** with `asyncio.create_subprocess_exec` (explicit argv, never a shell for git; repo setup/gate commands run with `bash -lc` because they are trusted config).
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(git): workspace wrapper over the git CLI`.


T8 proof: two missing-module collection errors first. Additional unchanged regressions failed before fixes for a base instruction parent alias, token-shaped argv, and missing head-read capability. Final `make check`: 293 unit tests, 1 live deselected, strict mypy (75 files), lint/format, 98.21% coverage. Real local bare repos prove stale leases, owner head preservation, hook suppression, clean commit idempotence, review overlays and process-group timeout. No GitHub/LLM calls made. D-025 records private fetch auth and recovery inputs.

### Task T9: Harness port, fake, prompts and step skills

**Files:**
- Create: `src/lgcw/harness/{__init__,port,errors,prompts,skills}.py`, `src/lgcw/harness/templates/{build,fix,restart,review,verify}.md`
- Create: `src/lgcw/skills/{build,fix,review,review-security,review-tests,verify-finding}/SKILL.md`
- Create: `tests/fakes/harness.py`, `tests/unit/harness/test_prompts.py`, `tests/unit/harness/test_skills.py`, `tests/unit/harness/test_fake_harness.py`

**Interfaces:**
- Produces `HarnessPort` (Protocol): `async start_session(spec: SessionSpec) -> SessionRef`; `async run_turn(session: SessionRef, turn: TurnInput, output: type[M], *, heartbeat: Callable[[], None]) -> TurnOutcome[M]`; `async close() -> None`. Errors: `HarnessError`, `HarnessAuthError`, `HarnessQuotaError(resets_at: datetime | None)`, `HarnessOutputError`, `HarnessSessionLostError`.
- Produces renderers: `render_build_turn(issue: IssueSnapshot, intake: IntakeResult, repo: RepoConfig, owner_answer: str | None) -> TurnInput`; `render_fix_turn(feedback: Feedback, criteria: Sequence[str], open_findings: Sequence[GatedFinding], handoff: BuildHandoff | None, owner_answer: str | None) -> TurnInput`; `render_restart_turn(issue: IssueSnapshot, criteria: Sequence[str], handoff: BuildHandoff | None, open_findings: Sequence[GatedFinding], feedback: Feedback | None) -> TurnInput`; `ReviewPacket(issue_title, criteria, base_sha, head_sha, range_from: str, diffstat: str, level: LevelDecision, lens: Lens, ci_summary: str, gate_summary: str, approach: str, decisions: list[Decision], assumptions: list[str], not_done: list[str], risks: list[Risk], files: list[FileNote], acceptance_evidence: list[str], open_findings: list[GatedFinding], do_not_repeat: list[str])`; `render_review_turn(packet: ReviewPacket) -> TurnInput`; `render_verify_turn(finding: GatedFinding, hunk: str) -> TurnInput`; `fence(data: str, label: str) -> str` (backtick run longer than any in `data`); `skill_path(name: str) -> Path`.
- Produces `FakeHarness(HarnessPort)`: `script(role: Role, outputs: list[BaseModel | Exception])`; `sessions: list[SessionSpec]`; `turns: list[tuple[SessionRef, TurnInput]]`; usage values configurable to drive the context-restart rule.

- [x] **Step 1: Write the failing tests**: `test_fix_turn_restates_findings_and_criteria` (every open finding id and every criterion appear in `turn.text`), `test_untrusted_data_is_fenced` (data containing a 3-backtick fence cannot close the fence), `test_review_packet_hides_builder_grades` (rendered review turn contains no handoff `summary` line and no acceptance `status` words), `test_skills_have_frontmatter_and_budget` (each `SKILL.md` has `name` and `description`, < 5,000 bytes), `test_fake_harness_records_and_raises`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** the port, errors, templates, renderers, step skills (build: plan, edit, run the repo's tests, return `BuildHandoff`, never commit; fix: address each listed finding or failure, one disposition per finding id; review: Codex review rubric, only issues introduced by the change, priority P0–P3, stay inside the given range; review-security and review-tests: the lens focus; verify-finding: confirm or reject one finding) and the fake.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(harness): port, prompts, step skills and fake`.


T9 proof: three missing-module collection errors first. Wheel inspection exposed a missing build skill; the git-ignore regression failed before anchoring /build/. Final `make check`: 324 unit tests, 1 live deselected, strict mypy (85 files), lint/format, 98.25% coverage. All six quick_validate skill checks pass; rebuilt wheel has five harness templates and six skills; fresh wheel import outside source resolves every exact skill path and renders a verify prompt. D-026 records self-contained fences and review packet boundaries. SDK invocation behavior is still T10 live work.

### Task T10: Codex harness (live adapter) and its spike

**Files:**
- Create: `src/lgcw/harness/codex.py`, `src/lgcw/harness/env.py`
- Create: `tests/unit/harness/test_env.py`, `tests/unit/harness/test_codex_guard.py`, `tests/live/test_codex_smoke.py`
- Modify: `docs/decisions.md` (a new entry with the spike results)

**Interfaces:**
- Consumes: `HarnessPort`, models (T1, T9), `require_live` (T5).
- Produces: `build_codex_env(config: WorkflowConfig, base: Mapping[str, str]) -> dict[str, str]` (exactly `PATH`, `HOME`, `LANG`, `CODEX_HOME`); `CodexHarness(config: WorkflowConfig, *, allow_live: bool = False)` (one `AsyncCodex` per instance; `start_session` → `thread_start(cwd, sandbox, approval_mode=deny_all, model, ...)`; `run_turn` → `thread_resume` when needed, then a turn with the skill reference and text, `output_schema=strict_json_schema(output)`, heartbeat on every streamed event, `interrupt()` on cancellation, one retry on `HarnessOutputError`; maps SDK errors to the harness error family); `rollout_path(codex_home: Path, session_id: str) -> Path | None` (glob `sessions/**/rollout-*<session_id>*.jsonl`).

- [x] **Step 1: Spike (live, the builder runs it after the owner has created the workflow's Codex login, < 1 hour):** in a temp git repo, with a fresh `CODEX_HOME`, check (a) a turn input of skill reference + text, (b) `output_schema` on a resumed thread, (c) `usage` fields incl. cached input, (d) rollout file location, (e) `read_only` sandbox refuses a write, (f) interrupt on cancel. Record each answer and the exact SDK calls in a new decisions.md entry. If (a) or (b) fails, choose the fallback named there before Step 2.
- [x] **Step 2: Write the failing tests**: `test_env_is_minimal` (`GH_TOKEN` and `OPENAI_API_KEY` in base are absent from the result), `test_codex_harness_refuses_without_live`, `test_rollout_path_found` (temp tree), and the live `test_codex_smoke` (start builder session, run a turn returning a 2-field strict model, resume and run again, assert `usage.input_tokens > 0` and a rollout file exists).
- [x] **Step 3: Run** → FAIL.
- [x] **Step 4: Implement** `env.py` and `codex.py` per the spike's findings.
- [x] **Step 5: Run** `make check` → PASS; `LGCW_LIVE=1 uv run pytest tests/live/test_codex_smoke.py -m live` → PASS (the builder runs it; output in the PR).
- [x] **Step 6: Commit** `feat(harness): Codex SDK harness`.

T10 qualification refinements (D-034): use the owner-created dedicated login without copying
credentials; fresh first-turn handle vs post-materialization resume; explicit thread policy
immediately before each turn preserves builder network access. Usage includes nullable
context_input_tokens separately from per-turn cumulative counter deltas. Additional files:
harness/records.py, tests/fakes/codex.py and its unit boundary tests, typings/codex_cli_bin.pyi,
and RunLog.next_turn_seq plus its restart regression (reviewer carry-forward R2-X3).

### Task T11: Run log, redaction and report

**Files:**
- Reuse: `src/lgcw/runlog/{__init__,redact}.py` and redaction tests (brought forward in T5, D-021).
- Create: `src/lgcw/runlog/{log,report}.py`
- Create: `tests/unit/runlog/test_redact.py`, `test_log.py`, `test_report.py`

**Interfaces:**
- Produces: `redact(text: str) -> str` (masks `gh[pousr]_…`, `github_pat_…`, `sk-…`, three-part JWTs, `Authorization:` headers, `x-access-token:` URLs); `RunLog(run_dir: Path, *, clock: Clock | None = None)` (D-027) with `event(kind: str, *, node: str | None = None, **fields: JsonValue) -> None` (JSONL with ISO timestamp, redacted), `turn(seq: int, role: Role, turn: TurnInput, outcome: TurnOutcome[Any] | None, error: str | None) -> Path`, `artifact(rel: str, content: str) -> Path`, `posted(kind: str, body: str, ids: Mapping[str, str | int]) -> Path`; `write_report() -> Path` (atomically saves the semantically redacted derived view), `render_report(run_dir: Path) -> str`.

- [x] **Step 1: Write the failing tests**: one redaction case per pattern; `test_events_are_jsonl_with_timestamps`; `test_report_has_timeline_turns_and_totals` (a synthetic run folder: report contains the step table, one row per turn with input, cached, output and reasoning tokens, and totals); `test_report_empty_run`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(runlog): run log, redaction and report`.


T11 proof: missing RunLog imports caused two collection errors first. New report regressions failed before fixes for neighboring-field loss after header redaction, outside-run turn symlinks, an earlier completed outcome after a newer unfinished invocation, and a second redaction pass on saved report cells. Final `make check`: 345 unit tests, 1 live deselected, strict mypy (89 files), lint/format, 97.99% coverage. The two failed E501 attempts were recorded on PR #1; independent type/runtime checks and a measured shorter-literal probe resolved formatting without suppression. D-027 records evidence/derived-view distinctions. T10 stays pending its owner-login/live spike.

### Task T12: Graph skeleton — context, reconcile, routers, wiring

**Files:**
- Create: `src/lgcw/graph/{__init__,context,reconcile,routes,build_graph,runner,policies}.py`, `src/lgcw/graph/nodes/__init__.py`
- Create: `tests/unit/graph/test_next_step.py`, `test_routes.py`, `test_wiring.py`

**Interfaces:**
- Consumes: everything from T1–T11.
- Produces: `RunContext` (Pydantic, `arbitrary_types_allowed=True, frozen=True`: `config`, `repo`, `issue_ref`, `github: GitHubPort`, `workspace: WorkspacePort`, `harness: HarnessPort`, `clock: Clock`, `log: RunLog`, `workflow_login: str`); `ReconcileView(issue: IssueSnapshot | None, pr: PrSnapshot | None, ledger: PrLedger, threads: tuple[ReviewThread, ...], commands: tuple[Command, ...])`; `next_step(view: ReconcileView) -> ReconcileOutcome(step: Step, command: Command | None, ask: PendingAsk | None, reason: str)` implementing design §3.4; routers `route_after_reconcile`, `route_after_intake`, `route_after_open_pr`, `route_after_build`, `route_after_gate`, `route_after_publish`, `route_after_ci`, `route_after_review` (each `(state: RunState) -> Step`, reading `state.next_step`); `NodeFn = Callable[[RunState, Runtime[RunContext]], Awaitable[dict[str, Any]]]`; `build_graph(nodes: Mapping[Step, NodeFn] | None = None, *, limits: Limits | None = None) -> CompiledStateGraph` (defaults from `lgcw.graph.nodes.DEFAULT_NODES`, node policies from `policies.py`: transient-only `RetryPolicy(max_attempts=4, initial_interval=2.0)`, `TimeoutPolicy` for agent nodes per Global Constraints, default `error_handler` that sets `ask` with the node name and error class); `async run_issue(ctx: RunContext, *, nodes: Mapping[Step, NodeFn] | None = None) -> RunOutcome`.

- [x] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("case", NEXT_STEP_CASES, ids=lambda c: c.name)
def test_next_step(case): assert next_step(case.view).step == case.expected
# cases: no_pr→intake; pr_closed→end; blocked→end; pending_ask_no_command→end;
# pending_ask_answer→its step (command returned); abort→blocked; ready_for_head→end;
# only_initial_push→build; push_without_ci→ci_wait; ci_fix→build; ci_success_no_review→review;
# review_with_open_blocking_threads→build; review_clean→merge_ready

def test_next_step_head_moved_asks():
    out = next_step(view(pr_head="beef", last_push="cafe"))
    assert out.step == "ask" and out.ask.code == "head_moved"

def test_every_router_target_is_a_node():   # compile with trivial nodes, walk each edge
    g = build_graph(nodes=trivial_nodes_returning_each_step())
    assert set(edges_of(g)) >= ROUTER_TARGETS
```

- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement**; `run_issue` invokes the graph with `context=ctx` and returns `state.outcome`, logging every update from `astream(stream_mode="updates")` to `ctx.log`.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(graph): reconcile, routers and graph wiring`.


T12 proof: missing graph modules caused three collection errors first; the no-inline review-ingestion regression failed before adding reviews= and the review ledger namespace. Pinned free probes confirmed context/error-handler/idle behavior and identified runtime-checkable Protocol and typed-callable requirements. Actual-Codex environment follow-up remains inconclusive after two setup failures; T10 is untouched. Final `make check`: 404 unit tests, 1 live deselected, strict mypy (102 files), lint/format, 98.15% coverage. Compiled graph tests cover configured timeout, cancellation, fatal fallback, terminal-writer failure, all declared router targets, and refusal of implicit success. Default registration deliberately fails until T13–T16 supply real nodes. D-028/D-029 record boundaries and refinements.

### Task T13: Nodes — intake, open_pr, ask, blocked

**Files:**
- Create: `src/lgcw/intake.py` (`extract_acceptance_criteria(body: str) -> tuple[str, ...]`), `src/lgcw/graph/nodes/{reconcile,intake,open_pr,ask,blocked}.py`
- Create: `tests/unit/test_intake.py`, `tests/graph/__init__.py`, `tests/graph/conftest.py` (builds a `RunContext` from fakes and a temp origin repo), `tests/graph/test_intake_open_pr.py`

**Interfaces:**
- Consumes: T12 graph, fakes.
- Produces: node functions registered in `DEFAULT_NODES`; `reconcile` node applies an owner command by writing an `ack` marker before routing.
- Recovery extensions (D-031): typed `IntakeMarker`, `BootstrapMarker` (including linked PR number), `SetupMarker`, `CommandDoneMarker`; optional frozen intake/checkpoint fields on `RunMarker` and command/step/adoption fields on `AckMarker`; `LedgerEntry.where` additionally accepts `pr_body` for atomic initial identity. `GitHubPort.branch_head/get_pr_document`, `PrDocument`, and `WorkspacePort.commit_message` supply plain-code verification reads. `RunContext.tokens` is excluded/non-repr and used only by `push_auth`. Identical run body/comment copies are one fact; setup results and command continuations never replay blindly.

- [x] **Step 1: Write the failing tests**: criteria table (`## Acceptance criteria` list, `### Done when`, checklist only, none → empty); graph tests `test_incomplete_issue_asks_on_issue` (one `ask` comment on the issue, label `lgcw:waiting`, outcome `waiting`), `test_rerun_while_waiting_posts_nothing`, `test_owner_answer_resumes_to_open_pr` (one `ack`, then a draft PR), `test_open_pr_once_across_crash` (`fail_after("create_draft_pr", 1)` then rerun → exactly one PR, one push of the empty commit, its message contains `[skip ci]`), `test_foreign_author_issue_blocked`, `test_abort_blocks`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** the nodes; every side effect checks the ledger or the remote first.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(graph): intake, open_pr, ask and blocked`.

T13 proof: criteria/module failures first, then 11/20 compiled-graph cases failed before the real
registry/nodes existed. Additional unchanged regressions failed for marker-safe posted receipts,
answered-intake re-entry, exact human-head adoption and duplicate grants for one question.
The original bootstrap case checks commit/push/draft/label response losses; every comment boundary
and every owner-answer boundary also recover to one initial commit, push and PR. Setup unknown
results ask without replay; closed PRs remain linked; human adoption retains owner history across
ack/push-marker/completion losses. Unit-only continuation stops at a build checkpoint; this is not
a full workflow execution. Live prerequisites are now available (D-032), but no live call ran for
this task. The default graph still refuses missing T14–T16 nodes.

### Task T14: Nodes — build, gate, publish (with the fresh-builder rule)

**Files:**
- Create: `src/lgcw/graph/nodes/{build,gate,publish}.py`, `src/lgcw/graph/claims.py`
- Create: `tests/unit/graph/test_claims.py`, `tests/graph/test_build_gate_publish.py`

**Interfaces:**
- Produces: `check_claims(handoff: BuildHandoff, changed: Sequence[str], repo: RepoConfig, issue_body: str) -> ClaimsResult(ok: bool, feedback: Feedback | None, ask: PendingAsk | None)` (empty diff on `done` → `no_changes`; protected path without an explicit `lgcw-allow: <path>` line outside HTML comments/code fences → ask); `should_restart_builder(usage: Usage | None, fingerprints: Sequence[str], restarts_by_cause: Mapping[str, int], ratio: float) -> str | None` (returns the cause or None).

R1 extends `check_claims` with optional content fingerprint / structured protected approval,
and WorkspacePort with owned restoration and an optional immutable push SHA (D-035 R1).

R2 requires explicit allow lines (one exact relative path per line, outside HTML comments and
Markdown code fences). Ordinary mentions/denials never authorize. Only the latest answered
protected-path question can approve its exact paths/content; a later denial revokes prior approval.
An unchanged approved proposal resumes at gate with zero additional paid turns.

- [x] **Step 1: Write the failing tests**: `test_happy_build_gate_publish` (one `session` marker, one `push` with source `build`, PR body contains the handoff approach, commit trailers present), `test_gate_failure_then_fix` (second turn's text contains the gate tail and every criterion), `test_same_gate_failure_twice_restarts_then_asks`, `test_no_changes_counts_as_failure`, `test_protected_path_asks`, `test_handoff_blocked_asks_with_question`, `test_auth_error_asks_without_push`, `test_context_ratio_restarts_builder` (FakeHarness usage 0.7 × window before a fix round → new `session` marker with reason `fresh_restart`), `test_publish_once_across_crash` (crash after push before marker → rerun finds the remote head and writes one marker).
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(graph): build, gate and publish`.

T14 R3 qualification:801 unit tests,2 live deselected,96.00% coverage;13/13 guard removals
caught with isolated basetemp directories. Approval/gate crash recovery, no-progress owner ask,
later command revocation before continuation/after gate/before push, CommonMark scope, and
restored-parent rebuild prompt are proved in docs/validation/2026-10-14-t14-r3.md. D-035 R3
records the accepted creator/editor residual and optional carry to T17.

### Task T15: Node — ci_wait

**Files:**
- Create: `src/lgcw/graph/nodes/ci_wait.py`
- Create: `tests/graph/test_ci_wait.py`

**Interfaces:**
- Consumes: `classify`, `decide`, `trim_job_log`, `failure_fingerprint` (T6); `FakeGitHub.script_runs`, `FakeClock`.

- [x] **Step 1: Write the failing tests**: `test_pending_then_success_goes_to_review`, `test_change_failure_sends_trimmed_log_to_builder`, `test_same_ci_failure_after_fix_restarts_then_asks`, `test_infra_rerun_once_then_success` (exactly one `rerun_failed_jobs` call), `test_pre_existing_failure_moves_on_with_note` (base job fails the same step), `test_missing_after_grace_asks`, `test_deadline_asks`, `test_decision_reused_after_crash` (no duplicate `ci` marker or rerun), `test_rerun_cap_per_pr`.
- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement** the poll loop (`clock.sleep`, heartbeat, deadline) and actions.
- [x] **Step 4: Run** `make check` → PASS.
- [x] **Step 5: Commit** `feat(graph): CI wait and fix-or-move-on`.

T15 R2 qualification:903 unit tests,3 live deselected,96.14% coverage;18/18 guard removals
killed. Structural service phase, one transient rerun then builder, unique PR/base ownership,
cancelled timeout dispatch, workflow-specific base lookup (actual live filename correction),
and bounded terminal/feedback evidence. D-036 R2 and docs/validation/2026-10-14-t15-r2.md
record policy changes and the partial provenance live evidence. Full execution remains T17.

Combined T14 R3/T15 R2 qualification:939 units,3 live deselected,96.13% coverage;
append merge preserves df82dc9 and b3c905f histories and both regression sets.

### Task T16: Minimal review and merge_ready

**Files:** `src/lgcw/graph/nodes/{review,merge_ready}.py`,
`tests/graph/test_review_loop.py`, `tests/graph/test_merge_ready.py`, `tests/unit/test_no_merge.py`.

**Interfaces:** consumes `pick_level`, review models/renderers, `reviewer_checkout`, `diff_text`
and `numstat`. Execute only none/light. Map configured standard/deep to light and log both levels.
A light review uses one fresh reviewer session on the diff and publishes findings in one COMMENT
review. Only P0/P1 block; feed blockers to the existing resumed build → gate → publish → CI path,
then re-review. The prototype round cap is2, then ask; an explicit retry grants exactly one more.
`merge_ready` marks ready through GraphQL, switches labels and writes an idempotent ready marker.
Existing authority, head/content, CI and no-merge invariants remain binding.

- [ ] **Step 1: Write failing tests:** `test_level_none_goes_straight_to_merge_ready`,
  `test_light_clean_review_marks_ready_once`, `test_blocking_finding_round_trip`,
  `test_round_cap_asks_then_retry_grants_one`, `test_no_merge_calls`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the one-reviewer prototype and once-only readiness writes.
- [ ] **Step 4: Run** `make check` → PASS.
- [ ] **Step 5: Commit** `feat(graph): minimal review loop and merge-ready`.

Verifier, disputed findings, thread resolution, interdiff range_from, three-lens deep review and
review human-push adoption are deferred under the owner decision; see the backlog below.

### Task T17: Minimal CLI, doctor, family-calendar config and live R1

**Files:** `src/lgcw/{cli,doctor}.py`, `config/repos/bodegus__family-calendar.toml`,
`tests/unit/test_cli.py`, `tests/unit/test_doctor.py`, `tests/live/test_repo_configs.py`,
`tests/live/test_smoke_e2e.py`, README quickstart. memgo-app configuration waits for Phase1bR3.

**Interfaces:** `main(argv: Sequence[str] | None = None) -> int` with doctor, run R#N and report R#N;
exit0 success/merge-ready,2 waiting,3 blocked/closed,1 error. `make_context(config, ref) -> RunContext`
is the sole real-adapter allow_live=True construction boundary. `doctor(config, repo) -> list[Check]`
checks gh login, Codex account login without a model turn, git, configured tools and writable home.

- [ ] **Step 1: Write failing tests:** CLI parsing/exit codes with injected fake context;
  doctor missing npm; live configured workflow/job identity on real recent family-calendar runs.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** run/report/doctor and the family-calendar config from its actual CI:
  Node24.20.0, Node26.8.1, Container build and smoke test (re-confirm); setup npm ci, gate npm run check.
- [ ] **Step 4: Run** `make check` → PASS. The live smoke is Phase1bR1, the family-calendar
  proxy-addr production-audit fix. Once Alex has created its issue, run
  `uv run lgcw run bodegus/family-calendar#<n>`, kill once during ci_wait, rerun to merge-ready,
  and retain report/usage/CI/side-effect receipts proving no duplicate dispatch or publication.
  Proposed owner-created issue text: [R1 issue proposal](requests/r1-proxy-addr-issue.md).
- [ ] **Step 5: Commit** `feat(cli): doctor, run, report and family-calendar live smoke`.

#### Hardening backlog

Non-blocking items are recorded here, one line per review ID/source, for prioritization from the
first real run logs. Local optional work is preserved separately; it does not change df82dc9.

- R3-F6 (PR4): unused granted session-loss marker can allow one extra fresh session/paid turn.
- R3-F7 (PR4): approved handoff/diff mismatch should feed exact paths to a charged gate fix.
- R3-F8 (PR4): changed builder receipt should ask workspace_changed directly, avoiding approval again.
- R3-F9 (PR4): embedded sk-ant/sk-admin keys and long task-* name redaction need correction.
- 6159291252/flaky (PR5): trim duplicates pytest summaries and the runner exit line prevents real flaky reruns.
- 6159291252/head-override (PR5): fix-after-rerun override covers all failures on the head.
- 6159291252/base-404 (PR5): qualify the workflow-specific base-run404 behavior.
- 6159291252/stacked-PR (PR5): qualify association counting for stacked pull requests.
- 6159291252/limits-docs (PR5): reconcile the dead per-head guard, configuration and documentation.
- R2-F12 (PR5): real runner-loss and literal printed-::error live specimens remain unavailable.
- 6159291007/verifier: defer the fresh finding-verifier step until after first-run evidence.
- 6159291007/disputes: defer disputed-finding handling until after first-run evidence.
- 6159291007/threads: defer finding-thread resolution until after first-run evidence.
- 6159291007/interdiff: defer last-reviewed range_from packets until after first-run evidence.
- 6159291007/deep: defer three parallel deep-review lenses; log configured-to-light mapping meanwhile.
- 6159291007/human-adoption: defer review-specific human-push adoption; preserve head-move safeguards.
- 6159291007/status: defer CLI status; prototype exposes run, report and doctor.

---

## Phase 1b — three runs and inspection (owner and agent together)

Each run: the owner writes the issue (with acceptance criteria). The builder executes an
authorized `uv run lgcw run <ref>`, then uses `inspecting-runs` and writes `docs/runs/<id>.md`.

- [ ] **R1 simple (T17 live smoke; manifest risk configured deep, executed light under D-037):** family-calendar — update the transitive `proxy-addr` dependency so `npm audit --omit=dev --audit-level=high` passes (it currently fails CI on every open PR). Watch: dependency change with builder network; CI green proves it.
- [ ] **R2 medium (expected: standard):** a family-calendar feature chosen by the owner.
- [ ] **R3 complex (expected: deep):** a memgo-app feature chosen by the owner (candidates: bodegus/memgo-app#262, #261, #197). Watch: 12–32 minute CI on self-hosted runners, the known Mongo flake (bodegus/memgo-app#192), the long-wait cache question.
- [ ] **Synthesis:** `docs/runs/phase-2-priorities.md` — the improvement areas ranked by cost, failures and owner effort, with evidence from the three runs. This ranking replaces the Phase 2 list below where they differ.

## Phase 2+ — toward a durable local workflow (outline; planned after Phase 1b)

Candidate work items, to be ranked by the Phase 1b evidence:

1. Background service: `lgcw tick` over PRs labelled `lgcw:active`/`lgcw:waiting` under launchd; graceful drain on SIGTERM.
2. Kill-anywhere test in the live lane (side effects exactly once).
3. GitHub App identity (`lg-code-workflow[bot]`), repo-scoped tokens, `checks:read`.
4. Isolation: Docker task sandbox or Codex `exec-server` split; deny-read on `CODEX_HOME`; builder egress allowlist.
5. Budget guard: `account/rateLimits/read` before agent turns; pause on threshold.
6. Deep-level scanners (zizmor, gitleaks, dependency review) feeding the security lens.
7. Use each target repo's own PR template; re-fit review thresholds.
8. `ExternalMessage` for untrusted text; measured cache behaviour across long CI waits.

Exit: design §15 Phase 2 criteria.

## Phase 3+ — move to OpenClaw (outline)

Package an `lgcw` image; run on horse first under an OpenClaw cron command job (`lgcw tick`);
own Codex login and GitHub App on the host through home-infra Ansible; notifications through
OpenClaw; record the workflow in openclaw2-deploy's PLAN.md §6 and amend its AGENTS.md for the
hosted component. Exit: design §15 Phase 3 criteria.


### Round-2 foundation corrections (PR #1)

The T1–T12 review identified SDK UNSET mapping, ambiguous markers, partial level maps, CI
consequence/baseline/log layout errors, lockfile risk loss, git config transport attacks,
case-insensitive instructions, moving resume bases, and graph recovery/logging defects.
Regression tests cover every required R2 finding. R2-E3 changes the old no-push expectation
from ask to verified `open_pr` recovery; the concrete writer/recovery proof remains T13.
The former multi-marker parsing test encoded behavior contrary to design §3.1; its assertion
now rejects the entire ambiguous comment while still proving prose-preserving stripping.
No gate, coverage threshold, timeout, or assertion was relaxed to hide a failure.


T13 R1 corrections: reconcile-target commands finish before fresh routing; any-state PR lookup
prevents recreation after closure; a lost unpublished clone can re-checkpoint/setup on the current
default while the remote is absent; resumed PR labels repair; HTML comments/indented code are not
criteria. New ownership/redaction/body-source tests are backed by fourteen independent guard-removal
failures. Setup tails stay local. D-033 and the review-mutations spike retain the evidence.
