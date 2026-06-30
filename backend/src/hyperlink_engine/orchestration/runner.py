"""LangGraph-compatible pipeline runner.

``PipelineRunner`` has the same interface as a compiled LangGraph
``StateGraph`` — ``.invoke(state)`` and ``.stream(state)`` — so the
internals can be swapped for real LangGraph without changing callers.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.orchestration.events import event_bus
from hyperlink_engine.orchestration.nodes import (
    node_detect_references,
    node_flag_for_review,
    node_inject_links,
    node_load_dossier,
    node_parse_all,
    node_push_dossplorer,
    node_resolve_targets,
    node_score_and_report,
    node_validate,
)
from hyperlink_engine.orchestration.state import PipelineState, run_store

_log = get_logger("orchestration.runner")

# Cancel events per run_id — set to cancel a running pipeline.
_cancel_events: dict[str, threading.Event] = {}


def cancel_run(run_id: str) -> bool:
    """Signal a running pipeline to stop after the current node.

    Returns True if a running pipeline was found and signalled, False otherwise.
    """
    ev = _cancel_events.get(run_id)
    if ev is None:
        return False
    ev.set()
    return True


def _persist_run(state: PipelineState) -> None:
    """Write-through a finished run to Neo4j (best-effort, never fatal).

    Degrades to a no-op when Neo4j is unavailable or ``graph_backend`` isn't
    "neo4j" — the in-memory run store remains the live source of truth.
    """
    if state.get("status") != "done":
        return
    try:
        from hyperlink_engine.core.graph.dossier_schema import get_dossier_store

        store = get_dossier_store()
        if store is not None:
            store.persist_run(state)
    except Exception as exc:  # noqa: BLE001 — persistence must never break a run
        _log.warning("run_persist_failed", run_id=state.get("run_id"), error=str(exc))

# ─────────────────────────────────────────────────────────────────────────────
# Node registry — ordered sequence
# ─────────────────────────────────────────────────────────────────────────────

_NODES: list[tuple[str, Callable]] = [
    ("load_dossier",      node_load_dossier),
    ("parse_all",         node_parse_all),
    ("detect_references", node_detect_references),
    ("resolve_targets",   node_resolve_targets),
    ("inject_links",      node_inject_links),
    ("validate",          node_validate),
    ("score_and_report",  node_score_and_report),
]

# Which canonical node names map to a selectable layer. Nodes absent here
# (e.g. resolve_targets) always run their default implementation.
_NODE_TO_LAYER: dict[str, str] = {
    "load_dossier": "ingest",
    "parse_all": "parse",
    "detect_references": "detect",
    "inject_links": "inject",
    "validate": "validate",
    "score_and_report": "report",
}

_READINESS_FLOOR = 80.0

# Compiled LangGraph graph, built lazily once per process. None when langgraph
# is not installed (the runner then uses the sequential fallback loop below).
_compiled_graph: Any = None
_graph_initialized = False


def _get_graph() -> Any:
    """Return the compiled LangGraph pipeline (built once), or None."""
    global _compiled_graph, _graph_initialized
    if not _graph_initialized:
        _graph_initialized = True
        try:
            from hyperlink_engine.orchestration.graph import build_pipeline_graph

            _compiled_graph = build_pipeline_graph()
            if _compiled_graph is not None:
                _log.info("orchestration_engine", engine="langgraph")
            else:
                _log.info("orchestration_engine", engine="sequential")
        except Exception as exc:  # noqa: BLE001 — never let graph build break a run
            _log.warning("langgraph_build_failed_fallback_sequential", error=str(exc))
            _compiled_graph = None
    return _compiled_graph


def _resolve_nodes(state: PipelineState) -> list[tuple[str, Callable]]:
    """Return the ordered node list, substituting selected agents per layer.

    If ``state['agent_profile']`` is unset the legacy ``_NODES`` list is
    returned verbatim — guaranteeing byte-identical default behavior.
    """
    profile = state.get("agent_profile")
    if not profile:
        return _NODES

    from hyperlink_engine.orchestration.agents.base import Layer
    from hyperlink_engine.orchestration.agents.registry import get_agent

    resolved: list[tuple[str, Callable]] = []
    for node_name, default_fn in _NODES:
        layer_value = _NODE_TO_LAYER.get(node_name)
        agent_id = profile.get(layer_value) if layer_value else None
        if layer_value and agent_id:
            try:
                resolved.append((node_name, get_agent(Layer(layer_value), agent_id).run))
                continue
            except (KeyError, ValueError):
                _log.warning("agent_resolve_failed", node=node_name, agent=agent_id)
        resolved.append((node_name, default_fn))
    return resolved


# ─────────────────────────────────────────────────────────────────────────────
# PipelineRunner
# ─────────────────────────────────────────────────────────────────────────────


class PipelineRunner:
    """Synchronous / async-compatible pipeline runner.

    Usage (synchronous — sync consumer)::

        runner = PipelineRunner()
        state = PipelineState.new(input_files, output_dir, dossier_id)
        run_store.create(state)
        final = runner.invoke(state, on_event=lambda e: print(e))

    Usage (background thread — FastAPI)::

        runner = PipelineRunner()
        state = PipelineState.new(input_files, output_dir, dossier_id)
        run_store.create(state)
        runner.run_in_background(state)
        # SSE consumers subscribe via event_bus.subscribe_sse(run_id)
    """

    def invoke(
        self,
        state: PipelineState,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> PipelineState:
        """Run all nodes synchronously, calling *on_event* after each transition.

        Uses the real LangGraph state machine when available; otherwise falls
        back to the equivalent sequential loop. Both paths produce identical
        results — same node functions, same score-based push/flag routing.
        """
        if on_event:
            event_bus.subscribe_sync(state["run_id"], on_event)

        graph = _get_graph()
        if graph is not None:
            return self._invoke_langgraph(graph, state)

        return self._invoke_sequential(state)

    # ── LangGraph path ───────────────────────────────────────────────────────

    def _invoke_langgraph(self, graph: Any, state: PipelineState) -> PipelineState:
        """Drive the compiled LangGraph graph, syncing the run store per node.

        ``graph.stream`` yields ``{node_name: state_update}`` after each node.
        We merge each update back into our PipelineState object so the run
        store (and any /status pollers) see live progress; the nodes themselves
        emit SSE events to the event bus exactly as in the sequential path.
        """
        try:
            for chunk in graph.stream(state):
                for node_name, node_update in chunk.items():
                    if isinstance(node_update, dict):
                        state.update(node_update)
                    state["current_node"] = node_name
                    run_store.update(state)
        except Exception as exc:  # noqa: BLE001 — mirror sequential error handling
            _log.error("pipeline_graph_error", run_id=state["run_id"], error=str(exc))
            state["status"] = "error"
            state["error"] = str(exc)
            event_bus.emit(
                state["run_id"], state.get("current_node", "?"), "error", {"error": str(exc)}
            )
            run_store.update(state)

        # The graph already handled push/flag routing via its conditional edge.
        state["status"] = "done" if state.get("status") != "error" else "error"
        state["current_node"] = "__end__"
        run_store.update(state)
        _persist_run(state)
        event_bus.emit(state["run_id"], "__end__", state["status"])
        return state

    # ── Sequential fallback path (no langgraph installed) ─────────────────────

    def _invoke_sequential(self, state: PipelineState) -> PipelineState:
        cancel_ev = _cancel_events.get(state["run_id"])
        for node_name, node_fn in _resolve_nodes(state):
            if cancel_ev is not None and cancel_ev.is_set():
                _log.info("pipeline_cancelled", run_id=state["run_id"], at_node=node_name)
                state["status"] = "cancelled"
                state["error"] = "Pipeline cancelled by user"
                event_bus.emit(state["run_id"], node_name, "cancelled", {})
                run_store.update(state)
                return state
            try:
                state = node_fn(state)
                run_store.update(state)
            except Exception as exc:
                _log.error(
                    "pipeline_node_error",
                    run_id=state["run_id"],
                    node=node_name,
                    error=str(exc),
                )
                state["status"] = "error"
                state["error"] = str(exc)
                event_bus.emit(state["run_id"], node_name, "error", {"error": str(exc)})
                run_store.update(state)
                break

        # Terminal routing: push vs. flag
        if state.get("status") != "error":
            if state.get("score", 0.0) >= _READINESS_FLOOR:
                state = node_push_dossplorer(state)
            else:
                state = node_flag_for_review(state)

        state["status"] = "done" if state.get("status") != "error" else "error"
        state["current_node"] = "__end__"
        run_store.update(state)
        _persist_run(state)
        event_bus.emit(state["run_id"], "__end__", state["status"])
        return state

    def run_in_background(
        self,
        state: PipelineState,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> threading.Thread:
        """Run the pipeline in a background daemon thread.

        The caller can stream results via ``event_bus.subscribe_sse(run_id)``.
        Returns the thread so callers can join() if needed.
        Cancel via ``cancel_run(run_id)``.
        """
        run_id = state["run_id"]
        cancel_ev = threading.Event()
        _cancel_events[run_id] = cancel_ev

        def _run() -> None:
            try:
                self.invoke(state, on_event=on_event)
            finally:
                _cancel_events.pop(run_id, None)

        t = threading.Thread(target=_run, daemon=True, name=f"pipeline-{run_id}")
        t.start()
        return t
