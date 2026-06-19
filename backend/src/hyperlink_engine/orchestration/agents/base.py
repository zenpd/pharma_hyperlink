"""Agent abstraction for the 6-layer engine.

A *layer agent* is a thin, swappable implementation of one pipeline layer.
Every agent has the same call shape as a pipeline node — ``run(state) -> state``
— so the runner can dispatch to a selected agent without any other change.

This module is **purely additive**. The existing ``orchestration/nodes.py``
functions are never modified; agents either wrap them (passthrough) or
re-implement a parametrized variant (e.g. the detection agents choose which
extractor cascade to run).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from hyperlink_engine.orchestration.state import PipelineState


class Layer(str, Enum):
    """The six selectable layers of the engine."""

    ingest = "ingest"
    parse = "parse"
    detect = "detect"
    inject = "inject"
    validate = "validate"
    report = "report"


# Canonical pipeline-node name each layer emits events under. Keeping these
# stable means the existing dashboard stepper (keyed by node name) lights up
# regardless of which agent implementation is selected.
NODE_NAME_BY_LAYER: dict[Layer, str] = {
    Layer.ingest: "load_dossier",
    Layer.parse: "parse_all",
    Layer.detect: "detect_references",
    Layer.inject: "inject_links",
    Layer.validate: "validate",
    Layer.report: "score_and_report",
}


@dataclass(frozen=True)
class AgentSpec:
    """A named, selectable implementation of one layer."""

    id: str
    layer: Layer
    label: str
    description: str
    run: Callable[[PipelineState], PipelineState]
    is_default: bool = False

    def to_public(self) -> dict[str, object]:
        """Serializable view for the ``GET /api/agents`` catalog."""
        return {
            "id": self.id,
            "layer": self.layer.value,
            "label": self.label,
            "description": self.description,
            "is_default": self.is_default,
        }
