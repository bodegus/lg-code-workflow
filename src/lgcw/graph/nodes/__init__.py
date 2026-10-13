"""Real node registry assembled as T13–T16 are implemented; never success stubs."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from lgcw.graph.context import NodeFn
from lgcw.models.base import Step

DEFAULT_NODES: Mapping[Step, NodeFn] = MappingProxyType({})
