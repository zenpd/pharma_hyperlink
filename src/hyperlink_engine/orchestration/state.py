"""Pipeline run state schema and in-memory run store."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# State TypedDict (mirrors LangGraph StateGraph state schema)
# ─────────────────────────────────────────────────────────────────────────────


class PipelineState(dict):  # type: ignore[type-arg]
    """Mutable state dict passed between pipeline nodes.

    Keys
    ----
    run_id          Unique run identifier (UUID4).
    dossier_id      Human-readable dossier label (e.g. "DOS-2026-DEMO").
    input_files     List[Path] of uploaded source documents.
    output_dir      Path where linked output files are written.
    current_node    Name of the currently-executing node.
    status          "running" | "done" | "error"
    ingest_records  List[dict] — per-file ingest metadata (sha256, size, …).
    detection_records List[dict] — per-file detection results.
    injection_records List[dict] — per-file injection results.
    linked_files    List[Path] — _linked.docx files produced.
    validation_results dict — existence + anomaly check results.
    links           List[dict] — final LinkRecord dicts for the store.
    anomalies       List[dict] — AnomalyRecord dicts for the store.
    score           float — submission readiness score (0–100).
    grade           str — "A" | "B" | "C" | "F"
    error           str | None — error message if status == "error".
    events          List[dict] — event log (also emitted to event_bus).
    """

    @classmethod
    def new(
        cls,
        input_files: list[Path],
        output_dir: Path,
        dossier_id: str = "",
    ) -> "PipelineState":
        run_id = str(uuid.uuid4())[:8]
        state = cls()
        state.update(
            {
                "run_id": run_id,
                "dossier_id": dossier_id or f"run-{run_id}",
                "input_files": list(input_files),
                "output_dir": output_dir,
                "current_node": "",
                "status": "running",
                "ingest_records": [],
                "detection_records": [],
                "injection_records": [],
                "linked_files": [],
                "validation_results": {},
                "links": [],
                "anomalies": [],
                "score": 0.0,
                "grade": "F",
                "error": None,
                "events": [],
            }
        )
        return state


# ─────────────────────────────────────────────────────────────────────────────
# Run store — keyed by run_id, thread-safe
# ─────────────────────────────────────────────────────────────────────────────


class _RunStore:
    """In-memory store mapping run_id → PipelineState."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, PipelineState] = {}

    def create(self, state: PipelineState) -> PipelineState:
        with self._lock:
            self._runs[state["run_id"]] = state
        return state

    def get(self, run_id: str) -> PipelineState | None:
        with self._lock:
            return self._runs.get(run_id)

    def update(self, state: PipelineState) -> None:
        with self._lock:
            self._runs[state["run_id"]] = state

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "run_id": s["run_id"],
                    "dossier_id": s["dossier_id"],
                    "status": s["status"],
                    "current_node": s["current_node"],
                    "score": s.get("score", 0.0),
                    "files": len(s.get("input_files", [])),
                }
                for s in self._runs.values()
            ]


run_store = _RunStore()
