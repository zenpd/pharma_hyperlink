"""Plan Two orchestration layer — LangGraph-compatible pipeline runner.

Wraps the existing detection / injection / validation pipeline stages into a
named-node state machine that can be run synchronously (sync consumers) or
asynchronously (FastAPI SSE streaming).

The ``PipelineRunner`` interface is intentionally identical to a compiled
LangGraph ``StateGraph.invoke()`` / ``StateGraph.stream()`` call so the
internals can be swapped for real LangGraph when the dependency is installed.
"""

from hyperlink_engine.orchestration.events import event_bus
from hyperlink_engine.orchestration.runner import PipelineRunner
from hyperlink_engine.orchestration.state import PipelineState, run_store

__all__ = ["PipelineRunner", "PipelineState", "run_store", "event_bus"]
