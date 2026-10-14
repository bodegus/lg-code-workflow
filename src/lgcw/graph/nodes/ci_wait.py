"""Deterministic bounded CI polling, evidence hydration and journaled rerun recovery."""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.runtime import Runtime

from lgcw.ci.classify import classify, latest_runs, owned_runs
from lgcw.ci.decide import decide
from lgcw.ci.feedback import failure_feedback
from lgcw.ci.logs import clean_evidence, trim_job_log
from lgcw.ci.observe import ci_history, effective_required
from lgcw.github.port import CiEvidenceLimitError, RequiredPolicyError
from lgcw.graph.context import RunContext
from lgcw.graph.nodes.common import attention, finish_command, observe, post_once
from lgcw.ledger.markers import fingerprint
from lgcw.models.ledger import CiMarker, FeedbackMarker, PushMarker, RerunMarker, RunMarker
from lgcw.models.state import RunState


async def ci_wait(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
    """Turn incomplete oversized evidence into an explicit owner question."""
    try:
        return await _ci_wait(state, runtime)
    except CiEvidenceLimitError as error:
        return attention("ci_evidence_limit", str(error), "ci_wait")


async def _ci_wait(state: RunState, runtime: Runtime[RunContext]) -> dict[str, Any]:
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
        candidates = await ctx.github.runs_for_sha(repo, push.head_sha, pr)
        head_prs = await ctx.github.open_prs_for_head(repo, pr.head_ref)
        if (
            len(head_prs) != 1
            or head_prs[0].number != number
            or head_prs[0].base_ref != pr.base_ref
            or any(len(run.pull_requests) > 1 for run in candidates)
        ):
            return attention(
                "ci_ownership_ambiguous",
                "Multiple or unproven PR owners for this CI head.",
                "ci_wait",
            )
        runs = latest_runs(owned_runs(candidates, repo, pr), push.head_sha)
        batches = await asyncio.gather(*(ctx.github.jobs_for_run(repo, run.run_id) for run in runs))
        jobs = tuple(job for batch in batches for job in batch)
        if len(jobs) > 200:
            raise CiEvidenceLimitError("CI aggregate job count exceeds the 200 observation limit.")
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
            raw = await ctx.github.job_log(repo, job.job_id)
            path = f"ci/{push.head_sha}/{job.run_id}-{job.run_attempt}-{job.job_id}"
            ctx.log.artifact(path + "-full.log", clean_evidence(raw))
            tail = trim_job_log(raw, job.failed_steps)
            tails[job.job_id] = tail
            ctx.log.artifact(path + "-trimmed.log", tail)
        base_batches = await asyncio.gather(
            *(
                ctx.github.latest_base_jobs(
                    repo,
                    workflow,
                    pr.base_ref,
                    next(run.workflow_path for run in runs if run.workflow == workflow),
                )
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
            paths = await ctx.workspace.commit_paths(run_marker.base_sha, push.head_sha)
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
        # A durable decision spends the allowance once. If its intent was never written,
        # continue that already-authorized operation instead of charging/deciding it again.
        resumable = next(
            (
                entry.marker
                for entry in reversed(obs.ledger.entries)
                if isinstance(entry.marker, CiMarker)
                and entry.marker.head_sha == push.head_sha
                and entry.marker.action == "rerun"
                and any(
                    run.run_id == entry.marker.run_id
                    and run.run_attempt == entry.marker.run_attempt
                    for run in runs
                )
                and not any(
                    isinstance(other.marker, RerunMarker)
                    and other.marker.head_sha == push.head_sha
                    and other.marker.run_id == entry.marker.run_id
                    and other.marker.from_attempt == entry.marker.run_attempt
                    for other in obs.ledger.entries
                )
            ),
            None,
        )
        if resumable is not None and status == "failure":
            resumed_job = next((job for job in failing if job.run_id == resumable.run_id), None)
            if resumed_job is not None:
                decision = decision.model_copy(
                    update={
                        "action": "rerun",
                        "klass": resumable.klass,
                        "fingerprint": resumable.fingerprint,
                        "job": resumed_job,
                        "note": "Resume the recorded CI rerun decision before its missing intent.",
                    }
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
        current = await ctx.github.get_pr(repo, number)
        if current.state != "OPEN":
            return {"pr": current, "outcome": "closed", "next_step": "end"}
        if (
            current.head_sha != push.head_sha
            or await ctx.github.branch_head(repo, pr.head_ref) != push.head_sha
        ):
            return attention(
                "head_moved", "PR/remote head changed during CI observation.", "reconcile"
            )
        if decision.action == "fix":
            feedback = failure_feedback(decision, failing, tails, runs)
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
            # Validate before intent so an already changed run cannot strand an intent.
            # Validate again after its write to retain the head/closure/ownership race guard.
            for before_intent in (True, False):
                fresh_run = await ctx.github.get_run(repo, selected.run_id)
                current = await ctx.github.get_pr(repo, number)
                if current.state != "OPEN":
                    return {"pr": current, "outcome": "closed", "next_step": "end"}
                if (
                    current.head_sha != push.head_sha
                    or await ctx.github.branch_head(repo, pr.head_ref) != push.head_sha
                ):
                    return attention(
                        "head_moved", "PR changed before CI rerun dispatch.", "reconcile"
                    )
                head_prs = await ctx.github.open_prs_for_head(repo, current.head_ref)
                if (
                    len(head_prs) != 1
                    or head_prs[0].number != number
                    or head_prs[0].base_ref != current.base_ref
                    or len(fresh_run.pull_requests) > 1
                ):
                    return attention(
                        "ci_ownership_ambiguous", "PR ownership changed before rerun.", "ci_wait"
                    )
                if (
                    not owned_runs((fresh_run,), repo, current)
                    or fresh_run.head_sha != push.head_sha
                    or fresh_run.run_attempt != selected.run_attempt
                    or fresh_run.workflow != selected.workflow
                    or fresh_run.status != "completed"
                    or fresh_run.conclusion != selected.conclusion
                ):
                    return attention(
                        "ci_run_changed",
                        "Run ownership or attempt changed before rerun.",
                        "ci_wait",
                    )
                if before_intent:
                    await post_once(
                        ctx,
                        number,
                        intent,
                        "CI rerun intent; unknown completion will not dispatch again.",
                    )
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
