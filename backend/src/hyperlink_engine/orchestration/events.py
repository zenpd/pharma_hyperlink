"""Event bus for pipeline run state streaming.

Events are emitted by node functions and consumed by:
  - Synchronous consumers: via on_event callback
  - FastAPI:   via the SSE endpoint (GET /api/pipeline/stream/{run_id})
               which polls the asyncio.Queue for each run

Thread-safe: nodes run in a background thread; the SSE endpoint reads from
an asyncio.Queue that is fed by a thread-safe bridge.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from typing import Any, Callable

# ─────────────────────────────────────────────────────────────────────────────
# Event schema
# ─────────────────────────────────────────────────────────────────────────────

NODE_LABELS = {
    "load_dossier":       "Loading dossier",
    "parse_all":          "Parsing documents",
    "detect_references":  "Detecting references",
    "resolve_targets":    "Resolving cross-doc targets",
    "inject_links":       "Injecting hyperlinks",
    "validate":           "Validating links",
    "score_and_report":   "Scoring & reporting",
    "push_dossplorer":    "Pushing to Dossplorer",
    "flag_for_review":    "Flagging for review",
}


def make_event(
    node: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ts": time.time(),
        "node": node,
        "label": NODE_LABELS.get(node, node),
        "status": status,      # "running" | "done" | "error" | "skipped"
        "details": details or {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Event bus
# ─────────────────────────────────────────────────────────────────────────────


class _EventBus:
    """Thread-safe event bus with per-run subscriber queues."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Threading queues for sync consumers (on_event callback)
        self._t_queues: dict[str, list[Callable]] = defaultdict(list)
        # asyncio queues for SSE consumers (FastAPI)
        self._a_queues: dict[str, asyncio.Queue] = {}

    # ── Sync API (node functions call this) ───────────────────────────────

    def emit(
        self,
        run_id: str,
        node: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit an event for the given run. Thread-safe."""
        event = make_event(node, status, details)
        with self._lock:
            callbacks = list(self._t_queues.get(run_id, []))
            aq = self._a_queues.get(run_id)

        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                pass

        if aq is not None:
            try:
                aq.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe_sync(self, run_id: str, callback: Callable) -> None:
        """Register a synchronous callback for sync consumers."""
        with self._lock:
            self._t_queues[run_id].append(callback)

    # ── Async API (FastAPI SSE) ────────────────────────────────────────────

    def get_or_create_async_queue(self, run_id: str) -> asyncio.Queue:
        with self._lock:
            if run_id not in self._a_queues:
                self._a_queues[run_id] = asyncio.Queue(maxsize=200)
            return self._a_queues[run_id]

    async def subscribe_sse(self, run_id: str):  # type: ignore[return]
        """Async generator yielding SSE-formatted event strings."""
        import json

        q = self.get_or_create_async_queue(run_id)
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("done", "error") and event.get("node") in (
                    "push_dossplorer", "flag_for_review", "score_and_report"
                ):
                    # Terminal node — send a final sentinel and close
                    yield "data: {\"node\": \"__end__\", \"status\": \"done\"}\n\n"
                    break
            except asyncio.TimeoutError:
                # Heartbeat keeps the SSE connection alive
                yield ": heartbeat\n\n"

    def cleanup(self, run_id: str) -> None:
        with self._lock:
            self._t_queues.pop(run_id, None)
            self._a_queues.pop(run_id, None)


event_bus = _EventBus()
