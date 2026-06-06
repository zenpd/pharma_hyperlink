"""LangGraph-compatible pipeline runner.

``PipelineRunner`` has the same interface as a compiled LangGraph
``StateGraph`` — ``.invoke(state)`` and ``.stream(state)`` — so the
internals can be swapped for real LangGraph without changing callers.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Generator

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

_READINESS_FLOOR = 80.0


# ─────────────────────────────────────────────────────────────────────────────
# PipelineRunner
# ─────────────────────────────────────────────────────────────────────────────


class PipelineRunner:
    """Synchronous / async-compatible pipeline runner.

    Usage (synchronous — Streamlit)::

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
        """Run all nodes synchronously, calling *on_event* after each transition."""
        if on_event:
            event_bus.subscribe_sync(state["run_id"], on_event)

        for node_name, node_fn in _NODES:
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
        """
        def _run() -> None:
            self.invoke(state, on_event=on_event)

        t = threading.Thread(target=_run, daemon=True, name=f"pipeline-{state['run_id']}")
        t.start()
        return t
