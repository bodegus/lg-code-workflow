# R1: proxy-addr production audit fix (family-calendar#26, PR27, merge_ready)

## Summary

Alex explicitly delegated creation of the prepared issue and execution of the real test.
Merged workflow source `ff51b951069b255fd09950e80acaf417747e5a93` produced
[PR27](https://github.com/bodegus/family-calendar/pull/27) for [issue26](https://github.com/bodegus/family-calendar/issues/26).
The exact target head is `478db7554c0fba6242f804300cf98cd799f5d390`.
Only package-lock.json changes: proxy-addr2.0.7→2.0.8,7 additions/3 deletions.
The real CLI survived a ci_wait SIGKILL and reached merge-ready with green required CI.
One earlier verified operator retry was necessary; this was not unattended first-pass success.
The target PR remains OPEN/non-draft, MERGEABLE/CLEAN, labelled lgcw:merge-ready, and unmerged.

## Commands and actual results

All commands ran from this checkout with the prepared local runtime selected:

```text
export PATH=/Users/alex/.lgcw/toolchains/node-24.20.0-darwin-arm64/bin:$PATH
uv run lgcw doctor --repo bodegus/family-calendar
OK version:node: 24.20.0; needs >=24.20.0
OK version:npm: 12.0.2; needs >=12.0.2 and <13.0.0
OK github_sandbox_isolation: Builder sandbox must deny the owner's GitHub login.
OK codex_login: Dedicated profile: /Users/alex/.lgcw/codex; login there if this fails.
# All checks OK; exit0, no model turn.

LGCW_LIVE=1 LGCW_SMOKE_ISSUE=bodegus/family-calendar#26 uv run pytest -m live tests/live/test_smoke_e2e.py -s
AssertionError: CLI ended before ci_wait; inspect report.md
# CLI exit2, run outcome waiting, ask head_moved after publication.
1 failed, 1409 warnings in 394.09s

# After inspecting exact commit identity and posting one /lgcw retry:
LGCW_LIVE=1 LGCW_SMOKE_ISSUE=bodegus/family-calendar#26 uv run pytest -m live tests/live/test_smoke_e2e.py -s --basetemp=/tmp/lgcw-r1-live-retry1
merge_ready: https://github.com/bodegus/family-calendar/pull/27 478db7554c0fba6242f804300cf98cd799f5d390
1 passed in 117.98s

# A further real CLI run, with public snapshots and builder receipt hashes compared:
uv run lgcw run bodegus/family-calendar#26
merge_ready; report: /Users/alex/.lgcw/runs/bodegus__family-calendar__26/report.md
post-ready CLI exit0; durable snapshot and builder receipt hashes unchanged
build intents 1 reviews 1 ready 1 push receipts 3
```

The first pytest launch emitted shared-temp cleanup warnings. The retry selects its own basetemp;
no assertion, skip, timeout or lane was changed. No target edit, manual commit or push was performed
by the operator. The real builder and plain-code controller produced the dependency commit.

## Timeline (UTC, 2026-10-14)

Evidence is events.jsonl under `~/.lgcw/runs/bodegus__family-calendar__26/`.

| Step | Start | Recorded node seconds | Evidence lines |
|---|---|---:|---|
| Initial reconcile/intake | 09:51:02 | 2.18 /1.82 | 1–6 |
| Setup/bootstrap draft PR | 09:51:06 | 22.85 | 7–10 |
| Builder | 09:51:29 | 333.83 | 11–13 |
| Code gate | 09:57:03 | 10.08; command1.21 | 14–17 |
| First publication/ask | 09:57:13 | 9.94 /7.66 | 18–24 |
| Operator retry/reconcile | 09:59:25 | 12.82 | 25–28 |
| ci_wait kill | 09:59:38 | interrupted, no node-end | 29; smoke/killed.json |
| Resume/recover publication | 09:59:41 | 3.27 /10.30 | 30–36 |
| CI classification | 09:59:55 | 8.06 | 37–40 |
| Fresh review | 10:00:03 | 50.52; turn40.41 | 41–44 |
| Readiness | 10:00:53 | 23.52 | 45–48 |

The final run_end at10:01:17 is merge_ready. A later ready-state rerun also exits0 without new
turns or durable records. The timeline preserves both the failed first launch and the real kill.

## Cost

Both model sessions were gpt-6.1-sol. Input includes cached tokens; reasoning is reported
separately within output, not added again. Monetary credits/USD were not available.

| Turn | Seconds | Input | Cached input | Output | Reasoning output |
|---|---:|---:|---:|---:|---:|
| Builder0001 | 323.36 | 1,291,079 | 1,214,592 | 9,412 | 1,623 |
| Reviewer0002 | 40.41 | 200,730 | 150,144 | 848 | 12 |
| Total | 363.77 | 1,491,809 | 1,364,736 | 10,260 | 1,635 |

Uncached input:127,073. No second builder dispatch or verifier turn occurred. The reviewer used
a fresh session; configured deep executed light under D-037 (events line42).

## What worked

- The builder read its packaged skill and target instructions, reproduced the production audit
  failure, ran `npm update proxy-addr --package-lock-only`, and preserved all159 existing tests.
  Its transcript has21 tool calls; relevant final validation/cleanup entries are lines144–167.
- The plain-code gate re-ran `npm run check`: tests159, pass159, fail0, skipped0, exit0.
  Evidence: gate-6584bc8fae2f1c09.log:1,161–167 and events.jsonl:15.
- Hosted [Node24](https://github.com/bodegus/family-calendar/actions/runs/38546133890/job/115792535030),
  [Node26](https://github.com/bodegus/family-calendar/actions/runs/38546133890/job/115792535246),
  and [container](https://github.com/bodegus/family-calendar/actions/runs/38546133890/job/115792728681)
  jobs all succeeded on the exact target head. Both Node jobs show tests159/pass159/fail0 and
  `npm audit --omit=dev --audit-level=high`: `found 0 vulnerabilities`.
- The fresh reviewer had4 tool calls, read its packaged review skill, inspected the committed
  diff and saved build evidence, and returned no findings. It did not reuse the builder session.
- Smoke receipts preserve PR27/head478db75 through kill/resume. `smoke/killed.json` has exit-9.
  `smoke/completed-478db7554c0fba6242f804300cf98cd799f5d390.json` has one build intent,
  one review5516208919 and one ready head. Builder0001 SHA256 stays
  `13aa5b5cf3d7d1cb6d4a318d8141c1bdb7d8518a7c5e04d085701c70423cb41d`.
- There are three distinct push receipts: bootstrap388edfd, authorized adoption478db75/human,
  recovered publication478db75/build. The last two describe the same existing commit. Recovery
  skips a push when the remote already equals the journaled candidate; no additional commit or
  duplicate dispatch/push/review record is present. Post-ready snapshots compare equal.
- [Ready receipt](https://github.com/bodegus/family-calendar/pull/27#issuecomment-6165805001)
  matches current GitHub head/draft/label/CI facts. [Operator output receipt](https://github.com/bodegus/family-calendar/pull/27#issuecomment-6165861845)
  publishes real command output and clarifies the handoff's historical CI caveats.

## Problems and proposed Phase 2 items (ranked)

1. **R1-OBS1: conservative publication mismatch required operator help.** Events19–24 and
   [question6165737637](https://github.com/bodegus/family-calendar/pull/27#issuecomment-6165737637).
   The later PR/ref/local SHA all matched journaled candidate478db75 and exact owned trailers.
   [Retry6165770302](https://github.com/bodegus/family-calendar/pull/27#issuecomment-6165770302)
   recovered without another builder. API observation lag is a hypothesis; SDK HTTP caching is
   disabled. Investigate with a sandbox spike, then consider a bounded convergence read that
   continues to refuse genuine foreign-head changes. Component: publication/GitHub observation.
2. **R1-OBS2: builder container preflight inherited production NODE_ENV.** Builder0001 tests
   record a missing-ESLint failure before a corrected clean install. Required checks ultimately
   passed. Make the existing container-first preflight explicit; do not skip canonical checks.
   Component: builder skill/runtime instructions. No CI failure was misclassified.
3. **R1-OBS3: historical partial handoff claims remain visible after readiness.** PR body says
   hosted CI/PR output was unverified at build time, while current code-owned status is green.
   Operator receipt supplies the actual outputs. Label historical claims clearly; related to
   W-8/X-6. Component: PR rendering. No agent claim substitutes for code/CI evidence.

## Local evidence index

Run report: `~/.lgcw/runs/bodegus__family-calendar__26/report.md` (regenerated by report/CLI).
Controller history: events.jsonl; turns/0001-builder.json and turns/0002-reviewer.json.
Each turn retains its exact rollout_path; builder session01a139d3-02b1-70d1-b4dc-bb97fed31202,
reviewer session01a139da-dac2-7ec0-bca6-c522922f3961. Full transcripts were inspected as data;
reasoning/private source/auth material is not copied here. Kill intent/killed/completed receipts
and interrupted/resumed CLI logs are in smoke/. All raw local state remains uncommitted.

T17's live checkbox and Phase1bR1 are complete. R2/R3 and their combined priority synthesis remain
future work; this report does not claim full deep review, unattended success or any target merge.
