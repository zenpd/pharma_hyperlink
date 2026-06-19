"""Real LangGraph ``StateGraph`` for the hyperlink pipeline.

This builds an actual compiled LangGraph graph — nodes wired with explicit
edges plus a **conditional edge** for the score-based push/flag routing — so
the orchestration is a genuine state machine, not a hand-rolled loop.

The pipeline shape:

    load_dossier → parse_all → detect_references → resolve_targets
        → inject_links → validate → score_and_report
                                          │
                       ┌──────────────────┴──────────────────┐
                  score ≥ 80                              score < 80
                       ▼                                       ▼
                push_dossplorer                        flag_for_review
                       └──────────────────┬──────────────────┘
                                          ▼
                                        END

Graceful fallback: if ``langgraph`` is not installed, :func:`build_pipeline_graph`
returns ``None`` and ``PipelineRunner`` transparently uses its sequential loop —
so the engine still runs on machines without the dependency.

Per-run agent selection (Plan Three) is preserved: each selectable layer node is
wrapped in a dispatcher that looks up the chosen agent from
``state['agent_profile']`` at call time, exactly like the sequential runner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.orchestration.nodes import (
    node_flag_for_review,
    node_push_dossplorer,
)

_log = get_logger("orchestration.graph")

if TYPE_CHECKING:
    # Type-checkers always see the real LangGraph symbols, so the graph-builder
    # calls (add_node / add_edge / add_conditional_edges / compile) resolve to
    # the real StateGraph API instead of a bare ``object``.
    from langgraph.graph import END, StateGraph

    _LANGGRAPH_AVAILABLE = True
else:
    try:
        from langgraph.graph import END, StateGraph

        _LANGGRAPH_AVAILABLE = True
    except ImportError:  # pragma: no cover — exercised only on bare environments
        _LANGGRAPH_AVAILABLE = False
        StateGraph = object
        END = "__end__"


def langgraph_available() -> bool:
    """True when the real LangGraph runtime is importable."""
    return _LANGGRAPH_AVAILABLE


def _make_dispatch_node(
    node_name: str,
    default_fn: Callable[[Any], Any],
    node_to_layer: dict[str, str],
) -> Callable[[dict], dict]:
    """Wrap a node so per-run ``agent_profile`` selection still applies.

    When the run carries an agent profile, the matching layer's selected agent
    runs instead of the default node function — identical dispatch logic to the
    sequential runner's ``_resolve_nodes``.
    """

    def _node(state: dict) -> dict:
        fn = default_fn
        profile = state.get("agent_profile")
        if profile:
            from hyperlink_engine.orchestration.agents.base import Layer
            from hyperlink_engine.orchestration.agents.registry import get_agent

            layer_value = node_to_layer.get(node_name)
            agent_id = profile.get(layer_value) if layer_value else None
            if layer_value and agent_id:
                try:
                    fn = get_agent(Layer(layer_value), agent_id).run
                except (KeyError, ValueError):
                    _log.warning("agent_resolve_failed", node=node_name, agent=agent_id)
        return fn(state)

    _node.__name__ = f"node_{node_name}"
    return _node


def build_pipeline_graph() -> Any | None:
    """Compile and return the LangGraph pipeline, or ``None`` if unavailable."""
    if not _LANGGRAPH_AVAILABLE:
        return None

    # Opt-in, compliance-guarded LangSmith tracing (no-op unless enabled
    # against a local/self-hosted endpoint). Dev-only debugging aid.
    try:
        from hyperlink_engine.orchestration.tracing import configure_tracing

        configure_tracing()
    except Exception as exc:  # noqa: BLE001 — tracing must never break a build
        _log.warning("tracing_config_failed", error=str(exc))

    # Imported here (not at module top) to avoid a circular import:
    # runner imports this module lazily, and this module needs the runner's
    # node registry + routing threshold.
    from hyperlink_engine.orchestration.runner import (
        _NODE_TO_LAYER,
        _NODES,
        _READINESS_FLOOR,
    )

    graph = StateGraph(dict)

    node_names = [name for name, _ in _NODES]
    for node_name, default_fn in _NODES:
        graph.add_node(node_name, _make_dispatch_node(node_name, default_fn, _NODE_TO_LAYER))

    # Terminal routing nodes.
    graph.add_node("push_dossplorer", node_push_dossplorer)
    graph.add_node("flag_for_review", node_flag_for_review)

    # Linear backbone: each main node flows to the next.
    graph.set_entry_point(node_names[0])
    for left, right in zip(node_names, node_names[1:]):
        graph.add_edge(left, right)

    # Conditional edge: score gate decides push vs. flag.
    def _route_after_report(state: dict) -> str:
        return "push" if state.get("score", 0.0) >= _READINESS_FLOOR else "flag"

    graph.add_conditional_edges(
        node_names[-1],
        _route_after_report,
        {"push": "push_dossplorer", "flag": "flag_for_review"},
    )
    graph.add_edge("push_dossplorer", END)
    graph.add_edge("flag_for_review", END)

    compiled = graph.compile()
    _log.info("langgraph_compiled", nodes=len(node_names) + 2)
    return compiled
