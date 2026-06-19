"""Selectable layer-agents for the 6-layer engine (Plan Three).

Additive over orchestration/nodes.py — see base.py for the abstraction.
"""

from hyperlink_engine.orchestration.agents.base import (
    NODE_NAME_BY_LAYER,
    AgentSpec,
    Layer,
)
from hyperlink_engine.orchestration.agents.registry import (
    AGENT_REGISTRY,
    DEFAULT_PROFILE,
    PRESET_LABELS,
    PRESETS,
    get_agent,
    list_catalog,
    resolve_profile,
)

__all__ = [
    "AGENT_REGISTRY",
    "DEFAULT_PROFILE",
    "PRESETS",
    "PRESET_LABELS",
    "AgentSpec",
    "Layer",
    "NODE_NAME_BY_LAYER",
    "get_agent",
    "list_catalog",
    "resolve_profile",
]
