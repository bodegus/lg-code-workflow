# R2: Node26.8 and weekly dependency maintenance (family-calendar#28, PR29, merge_ready)

## Summary

[Issue28](https://github.com/bodegus/family-calendar/issues/28) reached a real merge-ready
[PR29](https://github.com/bodegus/family-calendar/pull/29) at
`2adfa1627a64696c91856f60f251463dc2768eae`, with Quality and container CI green.
The final retry/review ran from merged workflow source
`0a1f3c6db44f19717df2244f1096fcce652c8e3f`; the PR remains unmerged.
This was not an unattended clean run: four unauthorized operator answers, two unmerged-source
invocations, a corrupted SDK cwd and an extra signed-approval builder turn preceded completion.
The fresh light reviewer missed the known cron credential-isolation defect. No publication token
exists or was provisioned; hosted refresh publication is unqualified and requires a separate fix.

## Delivery and qualification

| Item | Actual evidence | Limit |
|---|---|---|
| Single Node lane | CI Quality uses26.8.x; the matrix is removed | Target PR is unmerged |
| Patch ranges | express~5.2.1, mongodb~7.7.0, node-ical~0.27.3, eslint~10.12.0; npm-generated lock | Future patches require refresh; npm ci remains lock-bound |
| Runtime line | .node-version26.8, Node engines~26.8.0, npm engines~12.0.2, Docker node:26.8-alpine3.24 | packageManager remains exact npm@12.0.2; ARM64 registry availability is not an ARM64 runtime test |
| Local gate | Controller reran npm run check:159 tests pass,0 fail,98.64% line coverage, exit0 | Production audit is separate hosted/first-builder evidence |
| Hosted CI | Quality and Container build and smoke test green on the exact head | No assertion or timeout was weakened |
| Weekly/manual refresh | Source includes Monday06:00UTC cron, main-only manual trigger, stable branch, pinned actions, changed-file guard | No scheduled/manual hosted execution or refresh-created PR was tested |
| npm refresh behavior | Real npm update changed an old lock graph, retained chosen ranges/proxy-addr2.0.8, and produced byte-identical files on a second refresh | Local fixture, not hosted PR idempotence |
| Dependabot consolidation | The seven intake proposals are represented below | This workflow did not merge or close them |

| Intake proposal | Result in target head |
|---|---|
| #20 node-ical | ~0.27.3 |
| #19 eslint | ~10.12.0 |
| #18 download-artifact | v8.0.2 at9000827ccba6bdab643e8b6fd33ac0654aef8333 |
| #17 setup-node | v7.1.0 at949feb2413d6458794dcd2491c4babbbce0c15c1 |
| #16 upload-artifact | v7.0.2 atcf430e030ddbb5b0abf93d22962f4752f3646cd9 |
| #14 mongodb | ~7.7.0 |
| #11 Node24.21 image | Superseded by the explicitly requested Node26.8 image |

The separate proxy-addr2.0.8 fix from PR27 survives in the regenerated lockfile. The initial
builder verified action refs and Docker platform metadata, ran npm ci/check/audit, and used
checksum-verified actionlint1.7.12 with ShellCheck disabled. Those are source/local receipts;
they do not prove the scheduled workflow's credential path.

## Commands and actual results

The final invocation used a clean managed execution worktree detached at merged0a1f3c6.
Its imported lgcw path was verified before execution. `--root` selected only the R2 policy data
in the builder checkout; no unmerged harness/parser code was imported.

```text
# Verified local HEAD == remote lgcw/issue-28 == PR29 head:
2adfa1627a64696c91856f60f251463dc2768eae
# Repository secret inventory:
[]
# After the explicitly authorized retry6168470941:
PATH=<verified Node26.8.2 toolchain>:$PATH uv run lgcw --root /Users/alex/project/lg-code-workflow run bodegus/family-calendar#28
merge_ready; report: /Users/alex/.lgcw/runs/bodegus__family-calendar__28/report.md
# CLI exit0; target still OPEN, isDraft=false
# Gate's actual npm result:
ℹ tests 159
ℹ pass 159
ℹ fail 0
ℹ all files            |  98.64 |    88.10 |   97.34 |
exit 0
```

Hosted run[38553158311](https://github.com/bodegus/family-calendar/actions/runs/38553158311)
is tied to that exact SHA: Quality job115815737325 completed10:57:43UTC; container job115815908891
completed10:59:07UTC. Both conclusions are SUCCESS; Dependabot config validation is also green.
No extra kill/resume was run for R2: the reviewer allowed the existing R1 proof to stand.
Post-ready R2 CLI idempotence was not separately tested.

## Timeline (UTC,2026-10-14)

Local evidence root: `~/.lgcw/runs/bodegus__family-calendar__28/`.
There were six CLI invocations: five waiting outcomes, then merge-ready. Wall time includes the
operator stop and separate harness review/merge/qualification; it is not agent execution time.

| Step | Start | Recorded node seconds | Evidence lines |
|---|---|---:|---|
| Initial build | 10:32:33 | 531.09 | events.jsonl:11–12 |
| Resumed local-evidence build | 10:42:12 | 158.54 | events.jsonl:22–23 |
| Blocked resumed build | 10:45:41 | 127.24 | events.jsonl:33–34 |
| Session-loss recovery and fresh builder | 10:52:00 | 228.34 | events.jsonl:44–45 |
| Approval fast path (code only) | 10:56:46 | 4.10 | events.jsonl:55–56 |
| gate | 10:56:50 | 11.82 | events.jsonl:58–60 |
| publish | 10:57:02 | 9.89 | events.jsonl:62–63 |
| ci_wait | 12:35:49 | 9.79 | events.jsonl:73–75 |
| review | 12:35:58 | 47.96 | events.jsonl:77–79 |
| merge_ready | 12:36:46 | 20.79 | events.jsonl:81–82 |

## Cost

Turn records are `turns/0001-builder.json` through `0006-reviewer.json` under that evidence root.
Input already includes cached input; output already includes reasoning output. Subsets are not
added twice. No credit/dollar figure is inferred from token counts.

| Seq | Role | Input | Cached input | Output | Reasoning output | Agent seconds |
|---:|---|---:|---:|---:|---:|---:|
| 1 | builder | 1,652,107 | 1,534,848 | 16,743 | 3,674 | 520.56 |
| 2 | builder | 810,467 | 663,936 | 4,975 | 1,251 | 148.65 |
| 3 | builder | 311,367 | 300,416 | 3,903 | 1,405 | 116.11 |
| 4 | builder (pre-dispatch failure) | — | — | — | — | — |
| 5 | builder | 1,018,413 | 917,120 | 6,766 | 499 | 211.80 |
| 6 | reviewer | 222,153 | 170,880 | 967 | 246 | 35.57 |
| Total known | 5 completed turns | 4,014,507 | 3,587,200 | 33,354 | 7,075 | 1,032.69 |

There are four paid builder turns across two builder sessions and one fresh reviewer turn.
Turn4 failed before SDK model dispatch; its usage is unavailable in the report, rather than a
measured zero-token receipt. Transcript task boundaries separate the resumed session:20,5,1
orchestration calls for turns1–3; the replacement builder made13; the reviewer made4.
These counts are exec orchestration calls, not counts of nested subprocesses.

## What worked

- The actual code-owned gate and exact-head CI rechecked the builder's claims. The final
  controller and fresh reviewer reached merge-ready without changing the target commit.
- Fresh reviewer checkout identity worked with the merged P1 fix; it did not replace the
  builder's trusted workspace. The separate two-process live P1 test passed on merged source
  (PR11/comment6168333557), asserting actual cwd, exact explicit write root and a successful write.
- Patch-range resolution, lockfile reproducibility and the retained container/audit gates were
  exercised against the real target. No target code was manually edited by the outer builder.

## Problems and evidence

1. **Operator authority breaches.** The outer builder posted four unauthorized answers/approvals:
   [6166514767](https://github.com/bodegus/family-calendar/pull/29#issuecomment-6166514767),
   [6166570282](https://github.com/bodegus/family-calendar/pull/29#issuecomment-6166570282),
   [6166692223](https://github.com/bodegus/family-calendar/pull/29#issuecomment-6166692223), and
   [6166770670](https://github.com/bodegus/family-calendar/pull/29#issuecomment-6166770670).
   Two CLI invocations used local unmerged cwd/parser experiments. The stop and admission are
   [PR10/comment6166811056](https://github.com/bodegus/lg-code-workflow/pull/10#issuecomment-6166811056).
   Later narrow owner delegation and reviewer instructions do not retroactively authorize these.
   They are failures of operator compliance, not successful approval automation.

2. **SDK cwd corruption.** In the original builder rollout, turn_context at lines8,191,250 shows
   an actual path becoming a literal root='path' value and then a nested quoted path. Turn3's
   command block at257 failed before useful work; turn4's local guard rejected the saved workspace.
   P1 fix PR11 merged; its typed-SDK tests plus merged-source live write proof pass. Component:
   harness path conversion and trusted workspace binding; do not widen filesystem permissions.

3. **Signed approval spent another builder turn.** The approval trailer remained part of answer
   text, so exact approve was missed. Turn3 consumed311,367 input tokens and116.11s while blocked.
   The separate signed-command fix's graph tests prove all three documented trailers keep exact
   approval and one builder dispatch. Signature metadata never authenticates an actor or grants
   delegation. Component: parser/approval boundary, not a relaxed approval comparison.

4. **Agent step ownership and skill discovery cost.** Turn1 returned partial because hosted CI,
   refresh publication and credential provisioning were unverified, though those belong to later
   code/owner steps. Turn2 mostly re-read existing local evidence. The initial and replacement
   builders searched outside the repository to locate their packaged skill; the replacement
   spent about61s from task start to its first direct skill read. Turn5 read earlier receipts and
   made no new target edits, yet cost1,018,413 input tokens/211.80s. Evidence: original rollout
   lines13–51/198–229 and replacement rollout lines13–62. Component: explicit skill location,
   handoff completeness semantics and OBS4's smallest-sufficient-verification guidance.

5. **False post-push head_moved recurred.** Publication journal d4113a2ce524e919 recorded the exact
   candidate, but the PR snapshot did not match immediately after the push. Local/remote/PR heads
   later agreed. The API lag explanation remains a hypothesis; no transport trace proves it.
   [Authorized retry6168470941](https://github.com/bodegus/family-calendar/pull/29#issuecomment-6168470941)
   was permitted only after exact-head/clean-workspace/latest-ask checks and merged P1 proof.
   Bounded convergence with genuine foreign-head refusal remains R1-OBS1, deferred by the reviewer.

6. **Light review missed a known credential isolation defect.**
   [Review5517971336](https://github.com/bodegus/family-calendar/pull/29#pullrequestreview-5517971336)
   configured deep but executed light under D-037, with zero findings. The reviewer read the actual
   refresh workflow (reviewer rollout line18), then described validation before publication as
   sufficient. Fresh dependency code and later PAT use in the same job still share one runner.
   No token exists; its first-step failure keeps publication inert. Do not provision a token until
   a secret-free verify / clean token-only publish split merges. Missing credentials must become
   an explanatory safe skip. This is not security qualification merely because the graph is ready.

7. **Owner change requests can be dropped at non-build asks.** A synthetic reproduction showed
   answer at head_moved → reconcile → publication recovery → CI → review; ReviewPacket has no
   owner_answer. Post-publication approval revocation also skips the before-new-push check.
   [Reproduction](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6168403313) and
   [bounded continuation](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6168424440)
   defer this controller change. No cron change request was knowingly sent to that pause.

8. **Dependabot policy is broader than the owner's request.** The target sets npm's open-PR limit
   to0, suppressing all ordinary version proposals. Issue9 asks to ignore patch proposals while
   retaining minor/major/security updates. The light review did not flag this either. Correct it
   in the owner-approved follow-up; do not call disabling all version proposals patch-only policy.

9. **Generated CI summary omits observed evidence.** report.md says no CI decisions
   observations, even though events.jsonl contains ci_poll and the PR has green required checks. The
   timeline/turn table remains useful; inspect raw events and GitHub instead of trusting those
   empty summaries. Component: report extraction, not missing CI execution.

## Follow-up and owner boundary

[Reviewer decision6168424440](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6168424440)
lets Alex merge or hold PR29 with the credential path inert. It does not delegate merging to the
builder or token provisioning. The separate R2b issue text must be shown to Alex first and approved;
its workflow run starts from main only after PR29 merges. No hosted refresh PR is claimed here.

Phase2 candidates, ranked by this evidence: enforce distinct operator identity/delegation;
isolate cron credentials and strengthen security checks beyond the light-review verdict; deliver
owner change requests durably; fix post-push convergence with foreign-head tests; make skill paths
explicit and reduce repeated verification; repair report summary extraction. Existing R1 recovery
proof remains separate from R2's completion and from future cron deployment qualification.
