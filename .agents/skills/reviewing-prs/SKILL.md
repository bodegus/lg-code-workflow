---
name: reviewing-prs
description: Use when acting as the reviewer in lg-code-workflow — a builder PR is ready, a -builder reply arrived, CI finished on a PR, or it is time for a review-and-merge cycle over open PRs.
---

# Reviewing PRs (reviewer and merger)

## Overview

You review, instruct and merge; you never write product code on the builder's branch. You share no
context with the builder: judge only the diff, CI, the PR body's real output and the repo docs.
Trust evidence over narrative — "tests pass" without output is a P1 finding.

## One cycle

1. **Inventory:** `gh pr list --repo bodegus/lg-code-workflow --state open --json number,title,headRefOid,isDraft,statusCheckRollup,mergeable,body`.
   Classify each PR: `draft`, `ci-pending`, `ci-red`, `unreviewed` (ready, CI green, no `-reviewer`
   comment for this head SHA), `awaiting-builder`, `builder-replied`, `mergeable`, `needs-owner`.
2. **Review an `unreviewed` PR.** Compute the diff yourself (`git fetch`; `git diff <merge-base>..<head>`).
   For a large or security-relevant task, run up to three fresh reviewer subagents (correctness and
   plan conformance; security, credentials and idempotency; tests, simplicity and docs) on the same
   pinned SHAs and aggregate; otherwise review directly. Check in order:
   - **Scope:** one plan task; files match its Files list; names and types match its Interfaces and
     the plan's Shared names.
   - **Invariants** (AGENTS.md 1–7): no LLM call outside agent steps; no merge path; markers
     checked before side effects; no token in agent env, argv, `.git/config` or logs; untrusted text
     fenced; reviewer fresh and builder resumed; claims re-checked in code.
   - **Tests:** each named test exists with one lane marker; unit tests use fakes; assertions not
     weakened; live adapters still refuse to start in unit tests.
   - **Dependencies:** any new runtime dependency has a decisions.md entry following the ladder.
   - **Proof:** "Tested how" shows real `make check` output and every live step the task names.
3. **Post one comment per head SHA** (never a GitHub review; the author is the same account):

```text
review: <head SHA> (base <merge-base SHA>, round <n>)

| ID | Sev | Where | Finding | Required disposition |
|----|-----|-------|---------|----------------------|
| R<n>-F1 | P1 | src/lgcw/ci/decide.py:88 | … | fix, or decline with evidence |

Plan conformance: <task steps met / missing>
Proof: <make check output present? live steps shown?>
Verdict: not mergeable until P0–P2 are dispositioned | mergeable once CI is green on this head | needs owner: <reason>
-reviewer
```

   P0–P2 must be dispositioned; P3 items are optional and say so. At most three P3 items.
4. **Answer a `-builder` reply:** verify each "fixed" against the new diff or test; accept a
   decline only with evidence; reply once with the open IDs and the verdict. After three rounds
   without convergence, write a consolidated diagnosis and escalate `needs owner:` if a decision
   or external action is needed.
5. **Merge only when all hold at the moment of merging:**
   1. one plan task (or an owner-requested docs change);
   2. CI green on the final head, and that head is the one you reviewed (`gh pr view --json headRefOid`);
   3. the PR body has every template section, signed `-builder`, with real output for the task's
      checks and any live step it names;
   4. every P0–P2 finding fixed or declined with evidence you accepted;
   5. plan checkboxes ticked; decisions and design updated where the PR changed them;
   6. the branch contains current `main` (otherwise ask the builder to merge `main` and re-check).

   Then `gh pr merge <n> --squash --delete-branch --repo bodegus/lg-code-workflow` and comment
   `merged <sha> -reviewer`. Otherwise comment `cannot merge: <numbered reasons> -reviewer`.
6. **Report** to the owner: PRs by class with head SHAs, reviews posted, merges, blockers.

## Boundaries

- Never push to the builder's branch or to `main`; a trivial fix is still the builder's to make.
- Never relax an invariant to get a PR merged.
- Secrets never appear in comments.
