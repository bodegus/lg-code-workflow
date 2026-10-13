---
name: choosing-dependencies
description: Use when about to add a package to pyproject.toml, import a library not yet used in src/, or write a helper that an existing library might already provide (HTTP or GitHub clients, git, retries, scheduling, parsing, CLI, config, logging).
---

# Choosing dependencies

## Overview

The order is fixed: **LangGraph plugin > Python SDK > our own code.** A rung may be skipped only
with written evidence that it is not viable. The standard library counts as "no new dependency"
and is preferred over a new package when it does the job.

## The ladder

1. **LangGraph / LangChain first.** A feature of LangGraph itself, or a maintained official
   integration (`langgraph-*`, `langchain-*` packages; docs.langchain.com integrations; the
   `langchain-ai` GitHub org).
2. **An established Python SDK** for the service: the vendor's official SDK if one exists,
   otherwise the best-maintained, typed SDK.
3. **Our own thin code**, only when neither rung is viable.

## "Not viable" means one of these, with a link or file:line

| Reason | Evidence to record |
|---|---|
| unmaintained | archived repo, or no release in 6+ months |
| missing capability | name each operation we need and show which is absent |
| wrong shape | e.g. sync-only where nodes must be async; string-in/string-out agent tools where we need typed data |
| licence | GPL/AGPL or unclear licence for a runtime dependency |
| security | needs broader credentials than we allow, or fetches code at runtime |

## Procedure

1. List the operations you need (e.g. "list check runs for a SHA", "resolve a review thread").
2. Search rung 1, then rung 2. For each candidate: version, last release, licence, and which of
   your operations it covers. Read source if the docs are unclear.
3. Pick the highest viable rung. Pin it in `pyproject.toml`.
4. **Add a `docs/decisions.md` entry in the same PR:**

```markdown
## D-0NN <what>: <choice>

- **Plugin check (step 1):** <candidates> — not viable: <reason + link>.
- **SDK check (step 2):** <candidates, versions, licences> — <chosen or not viable + reason>.
- **Decided:** <choice and pin>. <Who/when.>
- **Revisit when:** <condition>.
```

## Example

D-008 (GitHub): LangChain's GitHub toolkit lives in `langchain-community`, archived 2026-06-19,
needs App credentials and has no check runs or review threads → not viable. GitHub has no official
Python SDK; githubkit is async, typed, REST + GraphQL → chosen over PyGithub (sync, LGPL).

## Common mistakes

- Adding a convenience library (click, typer, structlog, pydantic-settings) where the standard
  library or Pydantic already works.
- Using a LangChain "toolkit" built for LLM tool-calling inside a deterministic node.
- Writing our own client before checking for an SDK, or recording the decision after the fact.
