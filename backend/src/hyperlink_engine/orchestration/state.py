"""Pipeline run state schema and in-memory run store."""

from __future__ import annotations

import csv
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
                # Cooperative cancel flag — set by POST /run/{id}/cancel; the
                # runner honors it at the next node boundary (status -> "cancelled").
                "cancel_requested": False,
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
        self._hydrate_lock = threading.Lock()
        self._runs: dict[str, PipelineState] = {}
        self._hydrated = False

    def _hydrate_from_disk(self, run_id: str) -> "PipelineState | None":
        """Reconstruct a completed run's state from its output directory.

        Called as a fallback when Neo4j is unavailable or after a server
        restart wiped the in-memory store. Produces enough state for the
        Run Compare screen (linked_files, links, input_files) to function
        without requiring a full re-run.
        """
        runs_root = Path("output") / "runs"
        run_dir = runs_root / run_id
        if not run_dir.is_dir():
            return None

        # Input files (prefer input/ subdir, fall back to ocr/)
        input_files: list[Path] = []
        for sub in ("input", "ocr"):
            candidate_dir = run_dir / sub
            if candidate_dir.exists():
                for f in candidate_dir.rglob("*"):
                    if f.is_file() and f.suffix.lower() in (".pdf", ".docx", ".doc"):
                        input_files.append(f)
                if input_files:
                    break

        # Dossier ID: name of the first subdirectory inside input/, otherwise run_id
        dossier_id = f"run-{run_id}"
        input_dir = run_dir / "input"
        if input_dir.exists():
            subdirs = sorted(d for d in input_dir.iterdir() if d.is_dir())
            if subdirs:
                dossier_id = subdirs[0].name

        # Output files: _linked.pdf / _linked.docx files
        output_dir = run_dir / "output"
        linked_files: list[Path] = []
        if output_dir.exists():
            for f in output_dir.iterdir():
                if f.is_file() and "_linked." in f.name and f.suffix.lower() in (".pdf", ".docx"):
                    linked_files.append(f)

        # Links: parse validation_report.csv produced by the pipeline
        links: list[dict] = []
        validation_csv = output_dir / "validation_report.csv" if output_dir.exists() else Path("")
        if validation_csv.exists():
            try:
                with open(validation_csv, newline="", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        src = row.get("source_doc", "")
                        tgt = row.get("target_doc", "")
                        # Infer link_kind from source/target docs — cross_doc when the
                        # target is a different file, otherwise treat as internal.
                        inferred_kind = "cross_doc" if tgt and tgt != src else "internal"
                        links.append({
                            "source_doc": src,
                            "link_text": row.get("link_text", ""),
                            "link_location_descriptor": row.get("link_location_descriptor", ""),
                            "target_doc": tgt,
                            "target_anchor": row.get("target_anchor", ""),
                            "status": row.get("status", "unverified"),
                            "confidence": float(row.get("confidence") or 0.9),
                            "detected_by": row.get("detected_by", ""),
                            "error_msg": row.get("error_msg") or None,
                            "link_kind": inferred_kind,
                        })
            except Exception:  # noqa: BLE001
                pass

        ps = PipelineState()
        ps.update({
            "run_id": run_id,
            "dossier_id": dossier_id,
            "status": "done" if linked_files else "error",
            "current_node": "",
            "input_files": input_files,
            "output_dir": output_dir,
            "linked_files": linked_files,
            "links": links,
            "anomalies": [],
            "score": 0.0,
            "grade": "F",
            "error": None,
            "events": [],
            "classification": "unclassified",
            "owner": "system:restored",
            "cancel_requested": False,
        })
        return ps

    def _ensure_hydrated(self) -> None:
        """Load persisted runs from Neo4j, then from disk, on first access.

        Past runs are added only when not already in memory — a live run
        always wins. Both Neo4j and disk hydration degrade gracefully.
        """
        if self._hydrated:
            return
        with self._hydrate_lock:
            if self._hydrated:
                return
            self._hydrated = True

            # Primary: Neo4j graph store
            try:
                from hyperlink_engine.core.graph.dossier_schema import get_dossier_store

                store = get_dossier_store()
                if store is not None:
                    for st in (store.fetch_runs() or []):
                        ps = PipelineState()
                        ps.update(st)
                        ps["input_files"] = [Path(p) for p in st.get("input_files", [])]
                        ps["linked_files"] = [Path(p) for p in st.get("linked_files", [])]
                        with self._lock:
                            self._runs.setdefault(st["run_id"], ps)
            except Exception:  # noqa: BLE001
                pass

            # Fallback: scan output/runs/ on disk for completed runs not in Neo4j
            try:
                runs_root = Path("output") / "runs"
                if runs_root.is_dir():
                    for run_dir in sorted(runs_root.iterdir(), reverse=True):
                        if not run_dir.is_dir():
                            continue
                        rid = run_dir.name
                        with self._lock:
                            if rid in self._runs:
                                continue
                        ps = self._hydrate_from_disk(rid)
                        if ps is not None:
                            with self._lock:
                                self._runs.setdefault(rid, ps)
            except Exception:  # noqa: BLE001
                pass

    def create(self, state: PipelineState) -> PipelineState:
        with self._lock:
            self._runs[state["run_id"]] = state
        return state

    def get(self, run_id: str) -> PipelineState | None:
        self._ensure_hydrated()
        with self._lock:
            state = self._runs.get(run_id)
        if state is not None:
            return state
        # Per-ID fallback: reconstruct from disk without waiting for a full scan
        ps = self._hydrate_from_disk(run_id)
        if ps is not None:
            with self._lock:
                self._runs.setdefault(run_id, ps)
            return ps
        return None

    def update(self, state: PipelineState) -> None:
        with self._lock:
            self._runs[state["run_id"]] = state

    def delete(self, run_id: str, *, remove_disk: bool = False) -> bool:
        """Remove a run from memory and optionally delete its output directory.

        Returns True if the run existed and was deleted, False if not found.
        """
        with self._lock:
            existed = run_id in self._runs
            self._runs.pop(run_id, None)
        if remove_disk:
            try:
                import shutil
                run_dir = Path("output") / "runs" / run_id
                if run_dir.is_dir():
                    shutil.rmtree(run_dir)
            except Exception:  # noqa: BLE001
                pass
        return existed

    def delete_all(self, *, remove_disk: bool = False) -> int:
        """Remove every run from memory and optionally all output directories.

        Returns the number of runs deleted.
        """
        with self._lock:
            run_ids = list(self._runs.keys())
            self._runs.clear()
        if remove_disk:
            try:
                import shutil
                runs_root = Path("output") / "runs"
                if runs_root.is_dir():
                    shutil.rmtree(runs_root)
                    runs_root.mkdir(parents=True, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
        return len(run_ids)

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
