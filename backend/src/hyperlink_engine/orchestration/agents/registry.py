"""Agent registry + preset profiles.

The registry maps each ``Layer`` to its available ``AgentSpec``s. A *profile*
is a ``{layer_value: agent_id}`` mapping resolved from a named preset plus
optional per-layer overrides.

Presets
-------
  * ``fast``     — regex-only detection, Word injection.
  * ``balanced`` — regex+NER detection (reproduces current default behavior).
  * ``max``      — full regex+NER+LLM cascade.
"""

from __future__ import annotations

from hyperlink_engine.orchestration.agents.base import AgentSpec, Layer
from hyperlink_engine.orchestration.agents.detect_agents import DETECT_AGENTS
from hyperlink_engine.orchestration.agents.inject_agents import INJECT_AGENTS
from hyperlink_engine.orchestration.agents.passthrough_agents import PASSTHROUGH_AGENTS

# ── Build the registry ────────────────────────────────────────────────────────

AGENT_REGISTRY: dict[Layer, dict[str, AgentSpec]] = {layer: {} for layer in Layer}
for _spec in [*PASSTHROUGH_AGENTS, *DETECT_AGENTS, *INJECT_AGENTS]:
    AGENT_REGISTRY[_spec.layer][_spec.id] = _spec


def _default_id(layer: Layer) -> str:
    for spec in AGENT_REGISTRY[layer].values():
        if spec.is_default:
            return spec.id
    # Fallback: first registered agent
    return next(iter(AGENT_REGISTRY[layer]))


DEFAULT_PROFILE: dict[str, str] = {layer.value: _default_id(layer) for layer in Layer}

# ── Presets ───────────────────────────────────────────────────────────────────

PRESETS: dict[str, dict[str, str]] = {
    "fast": {**DEFAULT_PROFILE, Layer.detect.value: "detect_regex"},
    "balanced": dict(DEFAULT_PROFILE),  # == current behavior
    "max": {**DEFAULT_PROFILE, Layer.detect.value: "detect_hybrid"},
}

PRESET_LABELS: dict[str, str] = {
    "fast": "Fast — regex only",
    "balanced": "Balanced — regex + NER",
    "max": "Max accuracy — regex + NER + LLM",
}


# ── Lookups ────────────────────────────────────────────────────────────────────


def get_agent(layer: Layer, agent_id: str) -> AgentSpec:
    """Return the AgentSpec for ``layer``/``agent_id`` or raise KeyError."""
    try:
        return AGENT_REGISTRY[layer][agent_id]
    except KeyError as exc:
        raise KeyError(f"no agent {agent_id!r} registered for layer {layer.value!r}") from exc


def resolve_profile(
    preset: str | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve a full ``{layer: agent_id}`` profile.

    Starts from the named preset (default ``balanced``), then applies any
    per-layer overrides. Unknown layers/agents in *overrides* are ignored so a
    stale UI selection can never break a run.
    """
    base = PRESETS.get(preset or "balanced", PRESETS["balanced"])
    profile = dict(base)
    for layer_value, agent_id in (overrides or {}).items():
        try:
            layer = Layer(layer_value)
        except ValueError:
            continue
        if agent_id in AGENT_REGISTRY[layer]:
            profile[layer_value] = agent_id
    return profile


def list_catalog() -> dict[str, object]:
    """Serializable catalog for ``GET /api/agents``."""
    return {
        "layers": [layer.value for layer in Layer],
        "agents": {
            layer.value: [spec.to_public() for spec in AGENT_REGISTRY[layer].values()]
            for layer in Layer
        },
        "presets": {
            name: {"label": PRESET_LABELS.get(name, name), "profile": profile}
            for name, profile in PRESETS.items()
        },
        "default_profile": DEFAULT_PROFILE,
    }
