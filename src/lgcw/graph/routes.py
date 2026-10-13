"""Pure routers: nodes explicitly choose, routers only project that choice."""

from __future__ import annotations

from lgcw.models.base import Step
from lgcw.models.state import RunState


def route_after_reconcile(state: RunState) -> Step:
    """Return the node's explicit next step."""
    return state.next_step


route_after_intake = route_after_reconcile
route_after_open_pr = route_after_reconcile
route_after_build = route_after_reconcile
route_after_gate = route_after_reconcile
route_after_publish = route_after_reconcile
route_after_ci = route_after_reconcile
route_after_review = route_after_reconcile

ROUTERS = (
    route_after_reconcile,
    route_after_intake,
    route_after_open_pr,
    route_after_build,
    route_after_gate,
    route_after_publish,
    route_after_ci,
    route_after_review,
)
