"""Real node registry assembled as T13–T16 are implemented; never success stubs."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from lgcw.graph.context import NodeFn
from lgcw.graph.nodes.ask import ask
from lgcw.graph.nodes.blocked import blocked
from lgcw.graph.nodes.build import build
from lgcw.graph.nodes.ci_wait import ci_wait
from lgcw.graph.nodes.gate import gate
from lgcw.graph.nodes.intake import intake
from lgcw.graph.nodes.merge_ready import merge_ready
from lgcw.graph.nodes.open_pr import open_pr
from lgcw.graph.nodes.publish import publish
from lgcw.graph.nodes.reconcile import reconcile
from lgcw.graph.nodes.review import review
from lgcw.models.base import Step

DEFAULT_NODES: Mapping[Step, NodeFn] = MappingProxyType(
    {
        "reconcile": reconcile,
        "intake": intake,
        "open_pr": open_pr,
        "ask": ask,
        "blocked": blocked,
        "build": build,
        "gate": gate,
        "publish": publish,
        "ci_wait": ci_wait,
        "review": review,
        "merge_ready": merge_ready,
    }
)
