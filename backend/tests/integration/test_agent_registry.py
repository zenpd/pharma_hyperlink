"""Plan Three — selectable-agent registry + runner dispatch tests."""

from __future__ import annotations

from pathlib import Path

from hyperlink_engine.orchestration.agents.base import Layer
from hyperlink_engine.orchestration.agents.registry import (
    DEFAULT_PROFILE,
    PRESETS,
    get_agent,
    list_catalog,
    resolve_profile,
)
from hyperlink_engine.orchestration.runner import _NODES, _resolve_nodes
from hyperlink_engine.orchestration.state import PipelineState


def test_all_layers_have_a_default_agent() -> None:
    for layer in Layer:
        assert layer.value in DEFAULT_PROFILE
        # The default profile must reference a real registered agent
        get_agent(layer, DEFAULT_PROFILE[layer.value])


def test_presets_present_and_detect_differs() -> None:
    assert set(PRESETS) == {"fast", "balanced", "max"}
    assert PRESETS["fast"][Layer.detect.value] == "detect_regex"
    assert PRESETS["balanced"][Layer.detect.value] == "detect_ner"
    assert PRESETS["max"][Layer.detect.value] == "detect_hybrid"


def test_balanced_preset_equals_default_profile() -> None:
    # Balanced must reproduce the historical fixed-cascade behavior.
    assert PRESETS["balanced"] == DEFAULT_PROFILE


def test_resolve_profile_applies_overrides_and_ignores_garbage() -> None:
    prof = resolve_profile("fast", {"detect": "detect_hybrid", "bogus": "x", "inject": "nope"})
    assert prof[Layer.detect.value] == "detect_hybrid"   # valid override applied
    assert "bogus" not in prof                            # unknown layer dropped
    assert prof[Layer.inject.value] == PRESETS["fast"][Layer.inject.value]  # invalid id ignored


def test_list_catalog_shape() -> None:
    cat = list_catalog()
    assert cat["layers"] == [l.value for l in Layer]
    assert {a["id"] for a in cat["agents"]["detect"]} == {
        "detect_regex", "detect_ner", "detect_hybrid"
    }
    assert set(cat["presets"]) == {"fast", "balanced", "max"}


def test_runner_no_profile_uses_legacy_nodes() -> None:
    state = PipelineState.new([], Path("out"))
    resolved = _resolve_nodes(state)
    assert [n for n, _ in resolved] == [n for n, _ in _NODES]


def test_runner_profile_preserves_non_layer_nodes() -> None:
    state = PipelineState.new([], Path("out"), agent_profile=resolve_profile("max"))
    names = [n for n, _ in _resolve_nodes(state)]
    # resolve_targets has no layer mapping and must always survive
    assert "resolve_targets" in names
    assert names == [n for n, _ in _NODES]  # same order/length, only fns swapped


def test_runner_profile_swaps_detect_fn() -> None:
    state = PipelineState.new([], Path("out"), agent_profile=resolve_profile("max"))
    resolved = dict(_resolve_nodes(state))
    legacy = dict(_NODES)
    assert resolved["detect_references"] is not legacy["detect_references"]
    assert resolved["resolve_targets"] is legacy["resolve_targets"]
