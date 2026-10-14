"""Second-round protected approval and builder-continuation reproductions."""

from __future__ import annotations

import json
from pathlib import Path
from shlex import quote
from typing import Any

import pytest

from lgcw.graph.nodes.common import observe
from lgcw.harness.errors import HarnessQuotaError, HarnessSessionLostError
from lgcw.ledger.markers import parse_markers
from lgcw.models.github import IssueComment
from lgcw.models.harness import Usage
from tests.fakes.workspace import InjectedCrash
from tests.graph.conftest import GraphCase
from tests.graph.test_build_gate_publish import execute, markers, output, setup


def payload(text: str) -> dict[str, Any]:
    """Read the standard fenced evidence independently of the trusted owner suffix."""
    return dict(json.loads(text.split("```external-json\n", 1)[1].split("\n```", 1)[0]))


def high_usage() -> Usage:
    return Usage(
        input_tokens=700,
        cached_input_tokens=0,
        output_tokens=1,
        reasoning_output_tokens=0,
        context_window=1000,
        context_input_tokens=700,
    )


@pytest.mark.unit
async def test_later_denial_revokes_earlier_approval_even_when_bytes_return(
    graph_case: GraphCase,
    tmp_path: Path,
) -> None:
    flag = tmp_path / "gate-state"
    flag.write_text("fail")
    ctx, harness = await setup(
        graph_case,
        [{"AGENTS.md": "A\n"}, {"AGENTS.md": "B\n"}, {"AGENTS.md": "A\n"}],
        [output("AGENTS.md")] * 3,
        (f"grep -q pass {quote(str(flag))}",),
    )
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "protected_path"
    flag.write_text("pass")
    await ctx.github.create_issue_comment(
        ctx.issue_ref.repo, 100, "/lgcw answer No. Revert AGENTS.md entirely."
    )
    assert await execute(ctx) == "waiting"
    assert len(graph_case.workspace.pushes) == 1
    assert markers(graph_case, "ask")[-1].code == "protected_path"
    assert len(harness.turns) == 3


@pytest.mark.unit
async def test_matching_protected_approval_goes_to_gate_without_paid_turn(
    graph_case: GraphCase,
) -> None:
    ctx, harness = await setup(graph_case, [{"AGENTS.md": "A\n"}, {}], [output("AGENTS.md")] * 2)
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer approve")
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 2
    assert markers(graph_case, "gate")[-1].code == 0
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
@pytest.mark.parametrize("restart", [False, True])
async def test_latest_owner_answer_replaces_stale_pending_feedback(
    graph_case: GraphCase,
    restart: bool,
) -> None:
    blocked = output("app.py").model_copy(
        update={"status": "blocked", "open_questions": ["Version?"]}
    )
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "A\n"}, {"app.py": "B\n"}, {"app.py": "C\n"}],
        [blocked, blocked, output("app.py")],
    )
    assert await execute(ctx) == "waiting"
    if restart:
        harness.usage = high_usage()
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer OLDANSWER111")
    assert await execute(ctx) == "waiting"
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw answer NEWANSWER222")
    assert await execute(ctx) == "waiting"
    data = payload(harness.turns[-1][1].text)
    assert data.get("feedback") is None or data["feedback"].get("data") != "OLDANSWER111"
    assert "Authenticated owner instruction:\nNEWANSWER222" in harness.turns[-1][1].text
    assert len(harness.turns) == 3
    if restart:
        assert harness.turns[-1][0] != harness.turns[0][0]
    assert all(
        marker.pending_feedback is None or marker.pending_feedback.source != "owner"
        for marker in markers(graph_case, "build")
    )
    observed = await observe(ctx, await ctx.github.get_pr(ctx.issue_ref.repo, 100))
    assert observed.ledger.counts().gate_fix_rounds == 0


@pytest.mark.unit
async def test_unused_fresh_session_recovers_its_restart_prompt(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "bad\n"}, {"app.py": "fixed\n"}],
        [output("app.py")] * 2,
        ("grep -q fixed app.py",),
    )
    harness.usage = high_usage()

    def crash(comment: IssueComment) -> None:
        if any(
            marker.kind == "session" and getattr(marker, "reason", None) == "fresh_restart"
            for marker in parse_markers(comment.body)
        ):
            graph_case.github.after_comment = None
            raise InjectedCrash("fresh session receipt lost")

    graph_case.github.after_comment = crash
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    selected = markers(graph_case, "session")[-1].session_id
    assert await execute(ctx) == "waiting"
    assert len(harness.turns) == 2 and harness.turns[-1][0].session_id == selected
    restored = payload(harness.turns[-1][1].text)
    assert restored["issue"]["title"] and restored["previous_handoff"] is not None
    assert len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
@pytest.mark.parametrize("unknown", [False, True])
async def test_initial_retry_keeps_build_prompt_and_zero_gate_charge(
    graph_case: GraphCase,
    unknown: bool,
) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "A\n"}, {"app.py": "A\n"}],
        [
            output("app.py") if unknown else HarnessQuotaError("quota", resets_at=None),
            output("app.py"),
        ],
    )
    if unknown:
        harness.crash_after_turn = True
        with pytest.raises(InjectedCrash):
            await execute(ctx)
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == ("build_unknown" if unknown else "harness_quota")
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    restored = payload(harness.turns[-1][1].text)
    assert "issue" in restored and "intake" in restored and "repository_policy" in restored
    assert markers(graph_case, "build")[-1].source == "build"
    observed = await observe(ctx, await ctx.github.get_pr(ctx.issue_ref.repo, 100))
    assert observed.ledger.counts().gate_fix_rounds == 0
    assert len(harness.turns) == 2 and len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
async def test_fresh_quota_retry_keeps_restart_prompt(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{"app.py": "bad\n"}, {}, {"app.py": "fixed\n"}],
        [output("app.py"), HarnessQuotaError("quota", resets_at=None), output("app.py")],
        ("grep -q fixed app.py",),
    )
    harness.usage = high_usage()
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "harness_quota"
    fresh = markers(graph_case, "session")[-1].session_id
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    assert await execute(ctx) == "waiting"
    restored = payload(harness.turns[-1][1].text)
    assert "issue" in restored and restored["previous_handoff"] is not None
    assert harness.turns[-1][0].session_id == fresh
    assert len(harness.turns) == 3 and len(graph_case.workspace.pushes) == 2
    observed = await observe(ctx, await ctx.github.get_pr(ctx.issue_ref.repo, 100))
    assert observed.ledger.counts().gate_fix_rounds == 1


@pytest.mark.unit
async def test_granted_session_loss_marker_without_turn_is_reused(graph_case: GraphCase) -> None:
    ctx, harness = await setup(
        graph_case,
        [{}, {}, {"app.py": "fixed\n"}],
        [HarnessSessionLostError("first"), HarnessSessionLostError("second"), output("app.py")],
    )
    assert await execute(ctx) == "waiting"
    assert markers(graph_case, "ask")[-1].code == "harness_session_lost"

    def crash(comment: IssueComment) -> None:
        if any(marker.kind == "session" for marker in parse_markers(comment.body)):
            graph_case.github.after_comment = None
            raise InjectedCrash("granted fresh session receipt lost")

    graph_case.github.after_comment = crash
    await ctx.github.create_issue_comment(ctx.issue_ref.repo, 100, "/lgcw retry")
    with pytest.raises(InjectedCrash):
        await execute(ctx)
    selected = markers(graph_case, "session")[-1].session_id
    assert await execute(ctx) == "waiting"
    assert len(markers(graph_case, "session")) == 3
    assert len(harness.turns) == 3 and harness.turns[-1][0].session_id == selected
    assert len(graph_case.workspace.pushes) == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "allowed"),
    [
        ("Do NOT modify AGENTS.md under any circumstances.", False),
        ("<!-- AGENTS.md -->", False),
        ("lgcw-allow: AGENTS.md", True),
        ("lgcw-allow: AGENTS.md.bak", False),
        ("<!--\nlgcw-allow: AGENTS.md\n-->", False),
        ("```text\nlgcw-allow: AGENTS.md\n```", False),
        ("~~~\nlgcw-allow: AGENTS.md\n~~~", False),
    ],
)
def test_only_explicit_visible_allow_lines_preauthorize(body: str, allowed: bool) -> None:
    from lgcw.graph.claims import check_claims
    from tests.unit.ci.cases import repo

    policy = repo().model_copy(update={"protected_globs": ("AGENTS.md",)})
    result = check_claims(output("AGENTS.md"), ("AGENTS.md",), policy, body)
    assert result.ok == allowed
    if not allowed:
        assert result.ask is not None and result.ask.code == "protected_path"


@pytest.mark.unit
async def test_unicode_handoff_is_clipped_in_actual_marker_coordinates(
    graph_case: GraphCase,
) -> None:
    value = output("app.py").model_copy(update={"summary": ["→" * 12000]})
    ctx, harness = await setup(graph_case, [{"app.py": "fixed\n"}], [value])
    assert await execute(ctx) == "waiting"
    assert not markers(graph_case, "ask"), [marker.code for marker in markers(graph_case, "ask")]
    assert len(harness.turns) == 1 and len(graph_case.workspace.pushes) == 2
    assert markers(graph_case, "build")[-1].error is None
    assert all(
        len(comment.body) < 60000
        for comments in graph_case.github.comments.values()
        for comment in comments
    )
