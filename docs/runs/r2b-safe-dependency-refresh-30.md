# R2b: isolate weekly dependency publication (family-calendar#30, PR31, merge-ready)

## Summary

Alex approved the exact request at be1a3cb; issue30 was copied from that immutable draft after
Alex merged PR29. The real workflow built PR31 with separate secret-free verification and clean
publication jobs, safe absent-token skipping and patch-only npm Dependabot suppression. Local gate,
exact-head hosted Quality/container checks and a fresh light review passed. An independent source
reviewer accepted the protected proposal with bounded residual hardening. No agent merged or
created a publication credential. Actual hosted refresh/publication remains unqualified.

Target head: ea13244369eb49c0fb65086bacd26862b80b5618. Target main at intake:
22446af60dc545a696b25c0583bfa767b8ebf159. The initial CLI used merged harness0a1f3c6;
continuation used merged2ba0653. Runtime target writes belonged to plain controller code.

## Timeline

Local evidence prefix: `~/.lgcw/runs/bodegus__family-calendar__30/`.

| Step | Start UTC | Recorded seconds | Evidence |
|---|---|---:|---|
| Intake/reconcile |12:58:48|3.62|events.jsonl:1-6|
| Bootstrap PR |12:58:51|25.94|events.jsonl:9|
| Builder |12:59:17|536.64 node /524.10 paid turn|events.jsonl:12; turns/0001-builder.json|
| Gate |13:08:14|10.44 node /1.52 command|events.jsonl:15-16; gate-3806ba8c2ac99961.log|
| Publication |13:08:25|11.09|events.jsonl:19; publish operation baca6f71069bb0a8|
| False head-move ask |13:08:36|6.19|events.jsonl:22-24; PR31/comment6169099166|
| Authorized retry/reconcile |13:17:18|15.29|events.jsonl:25-27; PR31/comment6169265124|
| CI |13:17:33|7.59|events.jsonl:30-31; hosted run38569353866|
| Fresh review |13:17:41|102.06 node /93.52 paid turn|events.jsonl:34-35; turns/0002-reviewer.json|
| Merge-ready |13:19:23|17.62|events.jsonl:38-40; PR31/comment6169312797|

The first invocation exited2/waiting, the second exited0/merge_ready. Total wall span20m52.69s
includes8m36.09s between invocations while the published candidate/CI/authority were checked.
There was one builder turn, one reviewer turn, no gate/CI/review fix cycle and no repeated paid
builder dispatch. Publication has intent/result markers; those are not duplicate pushes. The later
push marker records authorized adoption of the already-published head after the retry.

## Cost

| Role | Input including cached | Cached input | Output including reasoning | Reasoning | Seconds |
|---|---:|---:|---:|---:|---:|
| Builder |1343202|1236480|15807|3462|524.10|
| Reviewer |496260|413568|1867|481|93.52|
| Total |1839462|1650048|17674|3943|617.62|

Uncached input189414. Cached input and reasoning are subsets, not additional tokens.
Credits/currency are unavailable; no price is inferred. Measured usage comes from both saved
turn outcomes and the generated report. Builder executed26 shell commands; reviewer8.

## What worked

- Owner-approved `lgcw-allow:` entries authorized exactly the workflow, Dependabot config and
  necessary AGENTS guidance. No manual protected approval, owner answer or abort was posted.
- The implementation confines the publication credential to availability checking and the pinned
  PR action on a separate runner. Publisher uses isolated standard-library Python over exactly
  three regular, non-executable JSON files, disables git hooks and runs no npm/repository code.
- Changed/no-change refresh fixtures execute actual workflow shell bodies using a loopback npm
  registry and stripped environment. ~1.2.0 advanced to~1.2.1 while1.3.0 was excluded. Twelve
  invalid artifacts were rejected before either target package file changed. Missing-token shell
  emitted notice/summary, available=false and zero write-command calls; later guards were checked.
  Actual transcript: builder rollout2026-10-14T07-59-23-01a13a7e-fa2c-76d2-aa8a-cee2bb753699.jsonl:125;
  fixture commands: `/private/tmp/family-calendar-30-fixtures-q3m4jnd0/commands.json` (27 commands).
- The controller independently re-ran npm run check:159 pass,0 fail. Hosted
  [CI38569353866](https://github.com/bodegus/family-calendar/actions/runs/38569353866) passed
  Quality and Container build and smoke test at the exact candidate. Existing gate/CI/container
  assertions and package files remained unchanged in this source-only safety follow-up.
- The fresh reviewer inspected the committed range and returned zero findings (configured deep,
  executed light under D-037). Independent
  [reviewer verdict6169271911](https://github.com/bodegus/lg-code-workflow/issues/9#issuecomment-6169271911)
  separately accepted the actual protected diff. Neither substitutes for hosted cron qualification.

## Problems

1. **False post-push head movement repeats.** The first invocation asks despite local/remote/PR
   agreeing on the owned publication. Evidence: events.jsonl:19-24 and
   [identity receipt6169261651](https://github.com/bodegus/family-calendar/pull/31#issuecomment-6169261651).
   The owner-delegated verified retry6169265124 recovered; evidence preceded the command. This is
   the R1-OBS1 class, observed across R1/R2/R2b. Proposed fix: bounded convergence reads after an
   owned push while preserving refusal for genuine foreign-head changes. Component: controller.
2. **Packaged skill context is not clearly exposed to the agents.** Builder searches
   ~/.lgcw, /private/tmp and /Users/alex/project, then reads the primary checkout skill. Reviewer
   searches ~/.lgcw, ~/.codex and the owner's home, generating65536characters in one tool result,
   then reads the primary skill and large gate/diff outputs. Evidence: builder transcript:15-44;
   reviewer rollout2026-10-14T08-17-45-01a13a8f-ce10-7f11-b51c-b1c1fb631929.jsonl:15,27,34,38,56.
   Saved turn metadata and harness SkillInput carry the exact absolute merged execution-worktree
   skill, but the model-visible transcript text says only "referenced packaged skill" and does not
   show that path. Both agents search broadly before reading the primary checkout copy. The SDK
   skill input therefore did not produce an obvious model-visible path in this evidence; this is
   a harness/prompt integration concern, not proven agent disregard of an explicit text path.
   Broad search causes avoidable input cost and unrelated-context exposure. Proposed fix: expose
   the exact trusted path or directly load the skill before dispatch, with bounded evidence access. Component: prompt/harness, separate PR.
3. **Fixture setup and unchanged Compose checks caused avoidable retries.** Initial refresh
   heredoc indentation failed actionlint, then was fixed. A synthetic command regex matched prose;
   after anchoring it, npm12 blocked the dependency lifecycle script and its marker was missing.
   Final fixture tests a root lifecycle script and retains the version/secret-free assertions.
   Compose validation first failed missing .env despite --env-file, then again with no-env-resolution;
   a temporary copy with .env.example finally parsed. Evidence: builder transcript:69,99,106,109,
   122,125,130,141. Whole-repo ShellCheck reports pre-existing SC2016 in unchanged ci/release;
   changed refresh passes actionlint with ShellCheck. Proposed fix: smallest required local proof,
   avoid unrelated Compose checks and account for pinned npm lifecycle policy. Component: skill.
4. **Generated report/ReviewPacket omit CI identity detail.** Report has a green ci_poll in its
   timeline yet says no CI decisions observed; reviewer notes no hosted run ID in its packet.
   Evidence: events.jsonl:30, report.md CI section, turns/0002-reviewer.json overall_explanation.
   PR operator receipt supplies actual run38569353866 and exact-head job results. Proposed fix:
   populate bounded code-produced CI identity summaries and align report event projection.
5. **Current two-job design accepts verifier-produced transitive lock data.** A compromised
   dependency can rewrite other lockfile resolved/integrity entries; strict manifest/root checks do
   not prove all transitive bytes. Independent reviewer accepted this as non-blocking because the
   output is a manually reviewed PR and cannot leak publication credentials. Proposed hardening:
   secret-free generate with --ignore-scripts -> verify generated artifact (pass/fail only) ->
   publish original generate bytes. Evidence: reviewer6169271911. Component: target cron workflow.
6. **Dependabot security-patch behavior is unqualified.** Patch-only ignore restores ordinary
   minor/major proposals, but actual security PR behavior was not observed. Independent reviewer
   asks to confirm after merge. Neither weekly refresh nor audit is evidence a security PR opened.
   Component: target configuration/hosted qualification; do not claim stronger delivery.

## Proposed Phase 2 items

1. Fix R1-OBS1 false post-push head moves without allowing foreign commits.
2. Bind agents to the supplied skill and bounded evidence; combine with OBS4 verification guidance.
3. Carry concrete exact-head CI identities into review packets and reports.
4. Harden target generation/verification data provenance with three jobs.
5. Qualify security-patch Dependabot behavior and owner-enabled credentialed publication separately.

Authority remains issue9/D-041/D-043. This run did not repeat R2's unauthorized operator answers or
unmerged harness execution. It used one narrowly delegated retry and did not manually edit target
code. Actual hosted missing-token dispatch awaits owner merge of PR31; token provisioning and
credentialed publication remain owner-controlled. A retry/resume is not a deliberate kill test;
R1's earlier controlled kill proof remains separate.
