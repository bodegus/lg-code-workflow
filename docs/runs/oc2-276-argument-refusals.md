# OC2-276: actionable issue-write refusals (openclaw2-deploy#276, PR280, merge-ready)

## Summary

The actual merged LangGraph workflow reached `merge_ready` at 2026-10-17T11:41:12Z on
[PR280](https://github.com/bodegus/openclaw2-deploy/pull/280), head
`357d3e576490ef41eba646b4291d79ab8309b8a0`, base `4297cd11540bfb0022efb146f5e531b0e10a55d4`.
One builder produced the scoped four-file patch; one fresh reviewer returned no findings.
The independent controller gate passed all 146 tests and Ruff; exact-head required CI passed.
This proves the supervised Phase 1 issue-to-PR path, with three recovery interventions. It does
not prove unattended reliability, full native acceptance, release, deployment or the live write.

Local evidence prefix: `~/.lgcw/runs/bodegus__openclaw2-deploy__276/`.
Generate the complete local report with `uv run lgcw report bodegus/openclaw2-deploy#276`;
the result is `report.md` beside `events.jsonl` and `turns/`. Raw local state is not committed.

## Timeline

All times below are UTC. Source prerequisites were independently merged before their live use:
[PR14](https://github.com/bodegus/lg-code-workflow/pull/14) registered the target;
[PR15](https://github.com/bodegus/lg-code-workflow/pull/15) fixed checkbox intake;
[PR16](https://github.com/bodegus/lg-code-workflow/pull/16) fixed the complete symlink path scan;
[PR17](https://github.com/bodegus/lg-code-workflow/pull/17) fixed both reviewer tree listings.
The final invocation used merged harness `581d4f00eb04a743894cfdf9b5ffb0bf5e8f12e5`.

| Step | Start | Seconds | Evidence |
|---|---|---:|---|
| Intake | 01:04:46 | 2.52 | events.jsonl:5-7; three frozen checkbox criteria |
| Initial bootstrap failure | 01:04:48 | 2.74 | events.jsonl:8-10; complete path list exceeded 64 KiB |
| Authorized bootstrap retry / PR creation | 10:59:55 | 20.38 | events.jsonl:20-22; PR16 already merged |
| Builder | 11:00:15 | 120.27 node / 110.84 agent | events.jsonl:23-25; turns/0001-builder.json |
| Gate | 11:02:16 | 15.23 node / 6.27 commands | events.jsonl:26-29; gate-493f44d06039c6dc.log |
| Publish | 11:02:31 | 11.02 | events.jsonl:30-32; one committed patch |
| Post-push head-move pause | 11:02:42 | 6.16 | events.jsonl:33-36; verified owned SHA, not a foreign commit |
| Delegated retry / reconcile | 11:03:39 | 11.33 | events.jsonl:38-40; builder not replayed |
| CI wait | 11:03:50 | 130.56 | events.jsonl:41-47; pending polls then success |
| Reviewer checkout failure | 11:06:01 | 5.65 | events.jsonl:48-51; no paid reviewer dispatched |
| Authorized review retry / reconcile | 11:40:12 | 7.40 | events.jsonl:57-60; PR17 already merged |
| Fresh review | 11:40:19 | 32.00 node / 20.96 agent | events.jsonl:61-64; turns/0002-reviewer.json |
| Merge-ready | 11:40:51 | 20.16 | events.jsonl:65-68; ready marker6233462409 |

Four CLI invocations ended waiting, waiting, waiting, then merge_ready. Their combined active
wall time was 398.94 seconds. The total span was 10h36m26.84s, dominated by time outside the
controller while source fixes, independent reviews and authority were obtained. There was no
builder fix round, repeated paid dispatch, CI rerun or target code edit by the outer builder.
Intent/result marker pairs are operation phases, not evidence of duplicate writes.

## Patch and proof

Only `ops/github_issue_write.py`, `ops/task_mcp.py` and their two unit-test files changed
([immutable diff](https://github.com/bodegus/openclaw2-deploy/compare/4297cd11540bfb0022efb146f5e531b0e10a55d4...357d3e576490ef41eba646b4291d79ab8309b8a0)).
The runtime diff adds 20 lines and removes three. It calculates missing/unexpected arguments
from fixed keyword names, sorts them and reports both sets together. Supplied values never enter
this new diagnostic. For the incident's three shapes:

| Refused shape | Exact diagnostic |
|---|---|
| Missing kind, supplied title | `update requires kind; title is not accepted on update` |
| Missing kind, no title | `update requires kind` |
| Valid kind, supplied title | `title is not accepted on update` |

The tool description now states the common arguments and the permitted arguments for all five
operations; the title property also says create-only. The PR's Decisions section explicitly
rejects optional title on update: the update payload changes only body, and its optimistic
concurrency hash protects only body. This preserves the existing API instead of adding retitling.
The argument matrix, valid-write payloads, journal schema/storage and request_id/idempotency logic
are unchanged. Refusals occur before journal creation or credential/network activity.

Twelve new parameterized cases cover the three incident shapes at both writer and model-facing
MCP boundaries, five-operation deterministic diagnostics, and the advertised description. They
assert exact messages, absence of private values and absence of I/O/state allocation. No existing
test, assertion or timeout changed. This is evidence for these operation-argument refusals, not
a claim that every pre-existing JSON-schema error in the MCP surface is value-private.

The builder ran both complete affected test files before editing, after adding tests, and after
the fix. Its sandbox reproduced two unchanged-baseline ownership/mode failures: baseline
132 passed / 2 failed; red-first 132 passed / 14 failed; final 144 passed / 2 failed. The controller
then independently ran the configured Python 3.12 command on the host, without weakening tests:

```text
uv run --no-project --python 3.12 --with-requirements images/ops/requirements.txt --with pytest --with pytest-xdist python -m pytest -q -p no:cacheprovider -n 4 tests/unit/test_github_issue_write.py tests/unit/test_task_mcp.py
146 passed, 1409 warnings in 4.11s
exit 0
uvx ruff@0.16.8 check ops tests
All checks passed!
exit 0
```

Evidence: gate log:1,504-512; builder transcript:60-69,73-89,93-113. The warnings include pytest
cleanup of old temporary directories; their exact cause was not repaired or hidden in this task.
The sandbox failures were `test_journal_entries_validate_against_schema_and_are_backup_safe` and
`test_concurrent_identical_create_calls_send_once`. Host success is distinct from sandbox success.

[CI39027194893](https://github.com/bodegus/openclaw2-deploy/actions/runs/39027194893) independently
passed lint, validate and unit on the exact head. Images/validate also passed; image build and
candidate-lock were skipped. The fresh
[workflow review](https://github.com/bodegus/openclaw2-deploy/pull/280#pullrequestreview-5557600350)
inspected the committed range and surrounding code, returned zero findings and explicitly said
tests were inspected, not rerun. No review threads exist. It was configured standard but executed
one general/light lens under the D-037 prototype policy, not full standard/deep review.

## Cost

| Role | Input including cached | Cached input | Output including reasoning | Reasoning | Agent seconds |
|---|---:|---:|---:|---:|---:|
| Builder, gpt-6.1-sol high | 952563 | 869504 | 5906 | 1112 | 110.84 |
| Reviewer, gpt-6.1-sol medium | 177347 | 116736 | 744 | 67 | 20.96 |
| Total | 1129910 | 986240 | 6650 | 1179 | 131.81 |

Uncached input: 143670. Cached input and reasoning are subsets, not extra tokens. Credits/currency
are unavailable; no price is inferred. These are the actual two saved workflow agent outcomes,
excluding outer builder/reviewer work on the prerequisite source PRs.

Both complete command timelines and returned evidence were inspected. Builder transcript:
`rollout-2026-10-17T06-00-19-01a14985-0d8e-7103-8004-0c4c96c56b7f.jsonl`; reviewer:
`rollout-2026-10-17T06-40-25-01a149a9-c335-7272-9c41-09382f18c355.jsonl`, both in the dedicated
Codex session directory for 2026/10/17. The builder read the target build-change skill, repository
instructions and scoped code/tests, added tests before implementation and did not commit/push.
The fresh reviewer read the target pr-review skill, checked the immutable range and live main,
and made no mutations. Plain controller code owned publication, review posting and readiness.

## What worked

- Intake froze exactly three checkboxes from the unchanged issue. The reviewer-only post-release
  paragraph and signature were retained in the snapshot but not promoted to builder criteria.
- All target changes came from the actual workflow builder; the outer builder only repaired and
  independently qualified harness prerequisites. No unmerged harness ran on the target.
- Recovery reconstructed from GitHub markers without replaying the paid builder. One build,
  one gate, one publication operation, one completed review and one ready marker are recorded.
- New diagnostics give a caller enough information to correct both errors in one attempt, with
  targeted regression coverage and no expanded write contract.
- The run stopped at a ready PR; merge, native qualification and live publication authority stayed
  with the target reviewer/owner.

## Problems

1. **Large-repository metadata assumptions blocked two different stages.** Events:10 and51;
   [stop/diagnosis](https://github.com/bodegus/openclaw2-deploy/pull/280#issuecomment-6233179613).
   The target's 65756-byte path listing exceeded 64 KiB. PR16 fixed the symlink scan but omitted
   reviewer head/base consumers. PR17 completed those bounded callsites with four red-first cases
   and independent mutation proof. Impact: two owner-authorized pauses and source review cycles.
   Component: workspace/preflight. Proposed follow-up: qualify all whole-tree consumers when
   onboarding a repo, retaining truncation refusal and bounded captures.
2. **The recurring false post-push head move needed operator recovery.** Events:30-36;
   [identity evidence](https://github.com/bodegus/openclaw2-deploy/pull/280#issuecomment-6233140087).
   The publication journal, local, remote and eventual PR head agreed; the immediate PR snapshot
   still showed the initial commit. This is consistent with the existing R1/R2/R2b convergence
   problem, not proof of a specific GitHub root cause. Proposed fix: bounded convergence reads
   after our exact leased push while preserving genuine foreign-head refusal. Component: publish.
3. **Context reads were large and repeated.** Builder transcript:19-32 and reviewer:13-25 contain
   whole PLAN/README reads, tool-output truncation warnings, then repeated PLAN reads. Both read
   the target skills; unlike R2b, these transcripts do not show broad home/session searches.
   Impact: 1.13M cumulative input tokens for a small diff despite only two short agent turns.
   Proposed fix: smaller complete tool batches and bounded applicable-plan excerpts; preserve
   mandatory instructions. The portion of tokens attributable to each read is not measured.
   Component: skill/prompt/tool budget.
4. **Report projections still lose recorded CI/review detail.** The report timeline includes
   successful ci_poll and review events, but its CI decisions and loop/findings sections say
   no observations recorded. Reviewer packet has a green marker but no concrete hosted run ID.
   Evidence: report.md sections, events:42-49, turns/0002-reviewer.json. This repeats R2b-OBS4;
   no CI failure was classified here. Proposed fix: project the actual event schema and carry
   exact-head hosted receipts into reviewer packets. Component: reporting/review packet.
5. **The final body mixes immutable builder history with current state.** PR280 correctly has
   Decisions, checked criteria and green CI/review status, but the handoff still says changes are
   uncommitted and review/CI did not run. Those were true when the builder returned and are stale
   as current claims. Proposed fix: clearly label historical builder claims and append the actual
   controller gate output/current receipts; adopt the target PR template. Component: PR rendering.
   The outer builder did not manually rewrite the workflow-produced body to conceal this defect.
6. **Sandbox and host filesystem qualification differ.** Builder transcript:69,113 versus host
   gate:504. The unchanged-baseline ownership/mode failures remain unexplained inside the sandbox;
   passing host tests do not prove they are fixed there. Proposed fix: a separate reproducible
   sandbox storage investigation, preserving all safety assertions. Component: test environment.

## Questions, retries and remaining qualification

No builder open question, owner answer, protected approval or abort occurred. Three retry commands
were used, each once with evidence recorded first:

| Ask | Authority / prerequisite | Consumed command |
|---|---|---|
| seq1 open_pr/node_error | Explicit Alex retry request; merged PR16 | [6233109091](https://github.com/bodegus/openclaw2-deploy/issues/276#issuecomment-6233109091) |
| seq2 reconcile/head_moved | Existing verified transient/head-move delegation; identity receipt6233140087 | [6233140210](https://github.com/bodegus/openclaw2-deploy/pull/280#issuecomment-6233140210) |
| seq3 review/node_error | Alex resumed the two-failure stop, delegation6233220427; merged PR17, evidence6233451981 | [6233452554](https://github.com/bodegus/openclaw2-deploy/pull/280#issuecomment-6233452554) |

Each command has an ack and command_done marker. The fresh review and ready marker follow the
third command. No additional retry or owner intervention is needed to complete this lgcw run.
This was not a deliberate process-kill test or a verification of every crash point.

Target reviewer merge order remains 279 → 280 → 277 → 271, followed by one release/deploy v0.0.54.
As observed at inspection, PR279 is still open. Before merging280, that reviewer must make it
current with main and require full native acceptance `scope=all`, first attempt green on the
exact final head. The scoped host gate and required CI do not substitute for that requirement.
No acceptance dispatch, merge, release, deployment or post-release live ledger update was
performed by this outer builder. The original reviewer-only live write remains unqualified.

## Proposed Phase 2 items

1. Fix owned-publication convergence without accepting foreign heads (repeats across real runs).
2. Add whole-repo metadata preflight and complete-consumer qualification during onboarding.
3. Repair report/PR projections and provide exact-head gate/CI receipts to reviewers.
4. Bound context/tool batches and measure per-step read cost without dropping repo instructions.
5. Investigate sandbox storage parity separately; retain native acceptance as an independent gate.

The patch is small and appropriate to the issue. The supervised workflow successfully built,
proved, reviewed and handed it off; the observed interruptions prevent calling this a reliable
unattended service yet. This additional repo test does not replace the planned memgo-app R3 run.
