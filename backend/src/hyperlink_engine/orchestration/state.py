"""Pipeline run state schema and in-memory run store."""

from __future__ import annotations

import threading
import uuid
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
    classification  "classified" | "unclassified" — document access tier (PLAN SEVEN).
    owner           str — user_id of the uploader (audit trail).
    """

    @classmethod
    def new(
        cls,
        input_files: list[Path],
        output_dir: Path,
        dossier_id: str = "",
        agent_profile: dict[str, str] | None = None,
        classification: str = "",
        owner: str = "",
    ) -> "PipelineState":
        if not classification:
            # PLAN SEVEN Feature B: deny-by-default posture — new runs take the
            # configured default ("classified" unless overridden). Inert while
            # the auth gate is off: the open SYSTEM principal reads everything.
            try:
                from hyperlink_engine.config.settings import get_settings

                classification = get_settings().default_classification
            except Exception:  # pragma: no cover - settings must never break runs
                classification = "unclassified"
        run_id = str(uuid.uuid4())[:8]
        state = cls()
        state.update(
            {
                "run_id": run_id,
                "dossier_id": dossier_id or f"run-{run_id}",
                "input_files": list(input_files),
                "output_dir": output_dir,
                # None → runner uses the legacy fixed node sequence (unchanged
                # behavior). A {layer: agent_id} dict selects per-layer agents.
                "agent_profile": agent_profile,
                "classification": classification,
                "owner": owner or "system:hyperlink-engine",
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
        self._hydrated = False

    def _ensure_hydrated(self) -> None:
        """Load persisted runs from Neo4j on first access (best-effort, once).

        Past runs reconstructed from the graph are added only if not already
        present in memory — a live run always wins over its persisted copy.
        Degrades to a no-op when Neo4j is unavailable.
        """
        if self._hydrated:
            return
        self._hydrated = True
        try:
            from hyperlink_engine.core.graph.dossier_schema import get_dossier_store

            store = get_dossier_store()
            if store is None:
                return
            states = store.fetch_runs()
        except Exception:  # noqa: BLE001 — hydration must never break the store
            return

        for st in states:
            ps = PipelineState()
            ps.update(st)
            ps["input_files"] = [Path(p) for p in st.get("input_files", [])]
            ps["linked_files"] = [Path(p) for p in st.get("linked_files", [])]
            with self._lock:
                self._runs.setdefault(st["run_id"], ps)

    def create(self, state: PipelineState) -> PipelineState:
        with self._lock:
            self._runs[state["run_id"]] = state
        return state

    def get(self, run_id: str) -> PipelineState | None:
        self._ensure_hydrated()
        with self._lock:
            return self._runs.get(run_id)

    def update(self, state: PipelineState) -> None:
        with self._lock:
            self._runs[state["run_id"]] = state

    def list_runs(self) -> list[dict[str, Any]]:
        self._ensure_hydrated()
        with self._lock:
            # Return the full RunSummary shape the frontend expects. The
            # Run Compare screen relies on `linked_files` to populate its
            # document dropdown, and on `total_links` for the run label —
            # omitting them left the dropdown permanently empty.
            return [
                {
                    "run_id": s["run_id"],
                    "dossier_id": s["dossier_id"],
                    "status": s["status"],
                    "current_node": s.get("current_node"),
                    "score": s.get("score", 0.0),
                    "grade": s.get("grade"),
                    "files": len(s.get("input_files", [])),
                    "total_links": len(s.get("links", [])),
                    "linked_files": [Path(p).name for p in s.get("linked_files", [])],
                    "classification": s.get("classification") or "unclassified",
                    "owner": s.get("owner") or "",
                    "error": s.get("error"),
                }
                for s in self._runs.values()
            ]


run_store = _RunStore()
