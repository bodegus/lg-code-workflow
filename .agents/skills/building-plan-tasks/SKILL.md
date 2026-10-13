---
name: building-plan-tasks
description: Use when acting as the builder in lg-code-workflow — implementing a task from docs/plan.md (T0–T17 or a Phase 1b run task), answering a review signed -reviewer, or continuing a task until its PR is merged.
---

# Building plan tasks

## Overview

You are the builder. Each plan task is one PR that you build test-first, prove locally, and carry
until the **reviewer merges it**. The task's **Interfaces** block and the plan's **Shared names**
are binding. You talk to the reviewer only through PR comments; you share no other context.

## 1. Pick the task

- The next unchecked task in `docs/plan.md` whose consumed tasks are merged on `main`. Phase 1 runs
  in order; do not start a second task while your previous PR is open, unless the reviewer says so.
- Read `AGENTS.md`, the design sections the task touches, the whole task, and decisions it cites.
- Branch `<agent>/<task-id>-<slug>` from a fresh `origin/main`.

## 2. Build test-first

1. Write the failing tests exactly as the task names them, one lane marker each; fakes only in
   unit tests.
2. Run them; see them fail for the expected reason.
3. Implement to the Interfaces signatures; keep I/O behind ports.
4. `make check` until green (lint, format, mypy strict, unit lane, coverage ≥ 90%).
5. Live steps the task names: run them yourself with `LGCW_LIVE=1` when the owner's prerequisites
   exist (e.g. the workflow's Codex login). If something only the owner can do is missing, comment
   on the PR `needs owner: <exact action> -builder` and continue with what you can.
6. Same PR: tick the task's checkboxes, add decisions.md entries for open choices (the
   `choosing-dependencies` skill for any new library), fix design.md if it was wrong.

## 3. Open the PR and prove it

`gh pr create --draft` early is fine; mark it ready (`gh pr ready`) only when `make check` passes
and the body is complete. Body: the template sections. **Tested how** contains the real commands
and their output (trim long output, keep the summary lines and any failure), and says what you did
not run. Sign the body `-builder`. Watch CI (`gh pr checks <n> --watch`); on red, reproduce locally
and fix the cause.

## 4. Answer every review

The reviewer posts one comment per head SHA with IDs such as `R1-F2`. Fix or decline each, push,
then reply once:

```text
reply to review <head SHA>:
| ID | Disposition | Commit or evidence |
|----|-------------|--------------------|
| R1-F1 | fixed | abc1234, test_x added |
| R1-F2 | declined | <evidence: file:line, requirement, or scope boundary> |
new head: <sha>; make check: <pass/fail>; CI: <state>
-builder
```

Push before replying so the head you name exists. A `-reviewer` instruction within the task's
scope is binding; a scope or design dispute goes to the owner as `needs owner:`.

## 5. Stay until merged

Check the PR about every ten minutes (Claude Code: `/loop 10m`; Codex: native goal continuation;
never a shell sleep loop) until the reviewer comments `merged <sha> -reviewer`. Then pull `main`
and go back to step 1. A `cannot merge … needs owner` comment ends the task until the owner answers.

## Rules that are not negotiable

- Never change an assertion, timeout, skip marker or fixture to make a check pass; argue a wrong
  test with evidence instead. Exit 137 / `Killed` is re-run, not "fixed".
- Never merge, never push to `main`, never force-push after a review has started.
- Never read or print tokens (`gh auth token`, `~/.lgcw/codex/auth.json`).
- A check you did not run is reported as not run. Second failed attempt at the same problem: stop
  and write what you tried, the exact output and the assumption it breaks.

## Common mistakes

- Code before the test, or a test that cannot fail.
- `unittest.mock` inside our modules instead of a fake at the port.
- A counter stored locally instead of derived from the PR ledger.
- A Codex session inheriting the parent environment.
- Two tasks, or an unrelated refactor, in one PR.
