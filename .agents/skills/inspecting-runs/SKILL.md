---
name: inspecting-runs
description: Use when an lgcw workflow run has finished, paused or failed and its behaviour, cost or logs need analysing — Phase 1 runs R1–R3, a live smoke run, or questions like "why did this run loop", "what did the builder do", "where did the tokens go".
---

# Inspecting runs

## Overview

Phase 1's purpose is learning from real runs. Every claim in a findings file points at a log line,
a PR comment or a Codex transcript entry.

## Where the evidence is

| Source | Location |
|---|---|
| Run report | `uv run lgcw report <owner/repo>#<n>` (writes `report.md`) |
| Event log | `~/.lgcw/runs/<owner>__<repo>__<n>/events.jsonl` |
| Agent turns | `…/turns/<seq>-<role>.json` (prompt, output, usage, rollout path) |
| Full Codex transcripts | `~/.lgcw/codex/sessions/**/rollout-*<session_id>*.jsonl` |
| CI | `…/ci/<sha>/` (poll log, full and trimmed job logs) |
| Gate output | `…/gate/<round>.log` |
| Durable record | the PR: event comments with markers, review threads, body |

## Procedure

1. Read `report.md`: outcome, time per step, tokens per turn (cached separately), rounds.
2. Walk `events.jsonl` in order; note every loop (gate, CI, review) and why it started.
3. For each agent turn, open the Codex transcript: what it read, which commands it ran, how long,
   whether it followed its step skill, what it returned.
4. Check the PR matches the local log (one marker per decision, threads resolved as claimed).
5. Answer: what did each step cost; which rounds were avoidable; was any CI failure misclassified;
   which prompt, skill or config change would have helped; where did the owner have to step in.

## Findings file: `docs/runs/<id>.md`

```markdown
# <id>: <issue title>   (<owner/repo>#<n>, PR #<p>, outcome)

## Summary            (3–5 lines)
## Timeline           (step, start, duration)
## Cost               (turns, input/cached/output/reasoning tokens, credits if known)
## What worked
## Problems           (each: evidence file:line or comment link · impact · proposed fix · component)
## Proposed Phase 2 items   (ranked, with the problem each fixes)
```

## Common mistakes

- Summarising the report instead of reading the transcripts.
- Blaming the model when the prompt, skill or limits caused the behaviour.
- Copying tokens, private code or personal data into the findings file; link to files instead.
