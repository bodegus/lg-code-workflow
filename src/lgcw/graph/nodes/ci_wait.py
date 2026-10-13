"""Deterministic bounded CI polling, evidence hydration and journaled rerun recovery."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.runtime import Runtime

from lgcw.ci.classify import classify, latest_runs
from lgcw.ci.decide import decide
from lgcw.ci.logs import trim_job_log
from lgcw.ci.observe import ci_history, effective_required
from lgcw.ci.patterns import INFRA_PATTERNS
from lgcw.github.port import RequiredPolicyError
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once
from lgcw.ledger.markers import fingerprint
from lgcw.models.ledger import CiMarker, FeedbackMarker, PushMarker, RerunMarker, RunMarker
from lgcw.models.state import Feedback, RunState
from lgcw.runlog import redact


async def ci_wait(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Observe only the owned head and never repeat an unknown rerun request."""
    ctx = runtime.context
    if state.pr is None:
        raise ValueError("CI requires a PR")
    repo, number = ctx.issue_ref.repo, state.pr.number
    interval = 15.0
    while True:
        runtime.heartbeat()
        pr = await ctx.github.get_pr(repo, number)
        if pr.state != "OPEN":
            return {"pr": pr, "outcome": "closed", "next_step": "end"}
        obs = await observe(ctx, pr)
        state = state.model_copy(update={"pr": pr, "ledger": obs.ledger})
        push_entry = next(
            (
                entry
                for entry in reversed(obs.ledger.entries)
                if isinstance(entry.marker, PushMarker)
            ),
            None,
        )
        if push_entry is None or not isinstance(push_entry.marker, PushMarker):
            raise ValueError("CI has no owned pushed head")
        push = push_entry.marker
        if (
            pr.head_sha != push.head_sha
            or await ctx.github.branch_head(repo, pr.head_ref) != push.head_sha
        ):
            return attention(
                "head_moved", "PR/remote head changed while waiting for CI.", "reconcile"
            )
        runs = latest_runs(await ctx.github.runs_for_sha(repo, push.head_sha), push.head_sha)
        batches = await asyncio.gather(*(ctx.github.jobs_for_run(repo, run.run_id) for run in runs))
        jobs = tuple(job for batch in batches for job in batch)
        try:
            contexts = await ctx.github.required_check_contexts(repo, pr.base_ref)
        except RequiredPolicyError as error:
            return attention("ci_policy_unsupported", str(error), "ci_wait")
        required = effective_required(ctx.repo.required_checks, contexts, runs, jobs)
        policy = ctx.repo.model_copy(update={"required_checks": required})
        limits = ctx.config.limits
        elapsed = (ctx.clock.now() - push_entry.created_at).total_seconds()
        outstanding = next(
            (
                entry
                for entry in reversed(obs.ledger.entries)
                if isinstance(entry.marker, RerunMarker) and entry.marker.head_sha == push.head_sha
            ),
            None,
        )
        if outstanding is not None and isinstance(outstanding.marker, RerunMarker):
            requested = outstanding.marker
            progressed = any(
                run.run_id == requested.run_id and run.run_attempt > requested.from_attempt
                for run in runs
            )
            if not progressed:
                age = (ctx.clock.now() - outstanding.created_at).total_seconds()
                if elapsed >= limits.ci_deadline_s or age >= limits.ci_start_grace_s:
                    return attention(
                        "ci_rerun_unknown",
                        "Rerun has no observable next attempt. Inspect Actions and start "
                        "the missing attempt manually, then /lgcw retry. "
                        "No second dispatch was made.",
                        "ci_wait",
                    )
                await ctx.clock.sleep(interval)
                interval = min(interval * 2, 120)
                continue
            if requested.phase == "intent":
                await post_once(
                    ctx,
                    number,
                    requested.model_copy(update={"phase": "accepted"}),
                    "Rerun recovered from its observed next attempt.",
                )
        status, failing = classify(
            required, runs, jobs, pr, push.head_sha, push_entry.created_at, ctx.clock.now(), limits
        )
        tails: dict[int, str] = {}
        for job in failing:
            # Runner acquisition/loss can have annotations without an available job log.
            # Strong service annotation evidence must not depend on downloading that log.
            annotated_infra = any(
                pattern.search("\n".join(job.annotations)) for pattern in INFRA_PATTERNS
            )
            raw = "" if annotated_infra else await ctx.github.job_log(repo, job.job_id)
            path = f"ci/{push.head_sha}/{job.run_id}-{job.run_attempt}-{job.job_id}"
            ctx.log.artifact(path + "-full.log", redact(raw))
            tail = trim_job_log(raw, job.failed_steps)
            tails[job.job_id] = tail
            ctx.log.artifact(path + "-trimmed.log", tail)
        base_batches = await asyncio.gather(
            *(
                ctx.github.latest_base_jobs(repo, workflow, pr.base_ref)
                for workflow in sorted({job.workflow for job in failing})
            )
        )
        base_jobs = tuple(job for batch in base_batches for job in batch)
        run_marker = next(
            (
                entry.marker
                for entry in reversed(obs.ledger.entries)
                if isinstance(entry.marker, RunMarker)
            ),
            None,
        )
        if run_marker is None:
            raise ValueError("CI run identity missing")
        paths: tuple[str, ...] = ()
        if status == "failure":
            await ctx.workspace.prepare(ctx.repo, ctx.issue_ref, pr.head_ref)
            paths = tuple(await ctx.workspace.changed_paths(run_marker.base_sha))
        history = ci_history(obs.ledger)
        grants = obs.ledger.counts().retry_grants.get("ci_wait", {})
        # A retry of an exhausted CI fix allowance grants exactly one extra fix, while
        # head/PR rerun caps remain hard. Failed reruns are never implicitly replayed.
        if grants.get("ci_fix_limit", 0):
            limits = limits.model_copy(
                update={"ci_fix_rounds": limits.ci_fix_rounds + grants["ci_fix_limit"]}
            )
        decision = decide(
            status,
            failing,
            runs,
            base_jobs,
            history,
            paths,
            tails,
            policy,
            limits,
            pushed_sha=push.head_sha,
        )
        selected_job = decision.job
        selected = next(
            (run for run in runs if selected_job is not None and run.run_id == selected_job.run_id),
            None,
        )
        marker = CiMarker(
            head_sha=push.head_sha,
            status=decision.status,
            klass=decision.klass,
            action=decision.action,
            fingerprint=decision.fingerprint,
            run_id=selected.run_id if selected else None,
            run_attempt=selected.run_attempt if selected else None,
        )
        if decision.action == "fix":
            pieces: list[str] = []
            budget = 16384
            ordered = sorted(
                failing,
                key=lambda failed: failed.job_id != (selected_job.job_id if selected_job else None),
            )
            for failed in ordered:
                header = (
                    f"Workflow: {failed.workflow}; job: {failed.name}; "
                    f"conclusion: {failed.conclusion}\nAnnotations: "
                    + "\n".join(failed.annotations)
                    + "\n"
                )
                text = (
                    (header + tails.get(failed.job_id, ""))
                    .encode()[:budget]
                    .decode(errors="ignore")
                )
                pieces.append(text)
                budget -= len(text.encode())
                if budget <= 0:
                    break
            feedback = Feedback(
                source="ci",
                summary=decision.note,
                data="\n".join(pieces).encode()[:16384].decode(errors="ignore"),
                fingerprint=decision.fingerprint,
            )
            # Hydrate before the decision so a crash cannot route the builder with a
            # lossy generic CI message instead of the measured bounded failure evidence.
            await post_once(
                ctx,
                number,
                FeedbackMarker(head_sha=push.head_sha, feedback=feedback),
                "CI failure evidence retained for the resumed builder.",
            )
        await post_once(ctx, number, marker, decision.note)
        ctx.log.event(
            "ci_poll",
            node="ci_wait",
            head_sha=push.head_sha,
            elapsed_s=elapsed,
            decision=decision.model_dump(mode="json"),
        )
        if decision.action == "wait":
            await ctx.clock.sleep(interval)
            interval = min(interval * 2, 120)
            continue
        if decision.action == "rerun":
            if selected is None:
                raise ValueError("rerun decision lacks an exact failed run")
            intent = RerunMarker(
                operation_id=fingerprint(
                    "rerun", push.head_sha, str(selected.run_id), str(selected.run_attempt)
                ),
                head_sha=push.head_sha,
                run_id=selected.run_id,
                from_attempt=selected.run_attempt,
                phase="intent",
            )
            await post_once(
                ctx, number, intent, "CI rerun intent; unknown completion will not dispatch again."
            )
            # Re-check the exact owned head immediately before the write.
            current = await ctx.github.get_pr(repo, number)
            if current.state != "OPEN" or current.head_sha != push.head_sha:
                return attention("head_moved", "PR changed before CI rerun dispatch.", "reconcile")
            await ctx.github.rerun_failed_jobs(repo, selected.run_id)
            await post_once(
                ctx,
                number,
                intent.model_copy(update={"phase": "accepted"}),
                "CI rerun request accepted.",
            )
            await ctx.clock.sleep(interval)
            interval = min(interval * 2, 120)
            continue
        await finish_command(ctx, state, number)
        refreshed = await observe(ctx, pr)
        fields: dict[str, Any] = {"pr": pr, "ledger": refreshed.ledger, "owner_command": None}
        if decision.action == "proceed_note":
            return fields | {"next_step": "review"}
        if decision.action == "fix":
            return fields | {"feedback": feedback, "next_step": "build"}
        code = (
            "ci_fix_limit"
            if history.ci_fix_rounds >= limits.ci_fix_rounds and status == "failure"
            else "ci_" + status
        )
        return fields | attention(code, "CI needs owner attention: " + decision.note, "ci_wait")
