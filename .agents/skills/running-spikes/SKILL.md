---
name: running-spikes
description: Use when a design or plan decision depends on behaviour of LangGraph, the Codex SDK, GitHub or git that has not been verified on the pinned versions, or when a plan task contains a spike step.
---

# Running spikes

## Overview

A spike answers one question with evidence, in under an hour. Its output is a recorded answer, not
code: probe code is throwaway (`spikes/` is gitignored); the transcript and verdict are kept.

## Procedure

1. **Write the question and the expected answer** before probing (e.g. "Does `thread_resume` accept
   `output_schema`? Expect yes.").
2. **Use the pinned versions** from `uv.lock`, a temp directory, and the sandbox repository for
   anything touching GitHub. Never a real target repository.
3. **Smallest probe that can answer it.** One script under `spikes/<YYYY-MM-DD>-<slug>/`.
4. **Run it and keep the exact commands and output** (redact tokens; never print `gh auth token`
   or `auth.json`).
5. **Record:** `docs/spikes/<YYYY-MM-DD>-<slug>.md` with question, expected, commands, output,
   verdict (confirmed, refuted, inconclusive) and consequence; plus a `docs/decisions.md` entry if
   a decision follows.

## Quick reference

| Probe kind | Cost |
|---|---|
| LangGraph behaviour (timeouts, error handlers, context) | free, local |
| GitHub API on the sandbox repository | free; rate limits apply |
| Codex SDK turns | uses the workflow login's plan quota; keep prompts tiny |

## Common mistakes

- Turning a spike into product code (start a plan task instead).
- Concluding from docs alone when the question is about runtime behaviour.
- Testing against an unpinned version.
