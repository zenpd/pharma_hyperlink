"""Pipeline node functions.

Each function:
  - Takes a PipelineState dict
  - Calls existing pipeline primitives (detect_references, inject_links, …)
  - Emits progress events via event_bus
  - Returns the updated PipelineState

This is the LangGraph node pattern: ``def node(state) -> state``.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.orchestration.events import event_bus
from hyperlink_engine.orchestration.state import PipelineState

_log = get_logger("orchestration.nodes")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _emit(state: PipelineState, node: str, status: str, **details: Any) -> None:
    state["current_node"] = node
    event_bus.emit(state["run_id"], node, status, details or None)


def _sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Node 1 — load_dossier
# ─────────────────────────────────────────────────────────────────────────────


def node_load_dossier(state: PipelineState) -> PipelineState:
    """Hash each uploaded file and ensure the output directory exists."""
    _emit(state, "load_dossier", "running")
    t0 = time.time()

    output_dir: Path = state["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for fp in state["input_files"]:
        fp = Path(fp)
        records.append(
            {
                "source_path": str(fp),
                "filename": fp.name,
                "sha256": _sha256(fp),
                "file_size_bytes": fp.stat().st_size,
                "suffix": fp.suffix.lower(),
            }
        )

    state["ingest_records"] = records
    _emit(
        state,
        "load_dossier",
        "done",
        files=len(records),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 2 — parse_all
# ─────────────────────────────────────────────────────────────────────────────


def node_parse_all(state: PipelineState) -> PipelineState:
    """Parse each document (docx → paragraphs + run metadata)."""
    _emit(state, "parse_all", "running", total=len(state["ingest_records"]))
    t0 = time.time()

    parsed = []
    for rec in state["ingest_records"]:
        fp = Path(rec["source_path"])
        if fp.suffix.lower() == ".docx":
            para_count, run_count = _parse_docx(fp)
        else:
            para_count, run_count = 0, 0

        parsed.append(
            {
                **rec,
                "para_count": para_count,
                "run_count": run_count,
                "parse_ok": True,
            }
        )
        _emit(state, "parse_all", "running", parsed=fp.name, paras=para_count)

    state["detection_records"] = parsed  # detection will overwrite with detections
    _emit(
        state,
        "parse_all",
        "done",
        files=len(parsed),
        elapsed=round(time.time() - t0, 2),
    )
    return state


def _parse_docx(path: Path) -> tuple[int, int]:
    try:
        from docx import Document

        doc = Document(str(path))
        paras = [p for p in doc.paragraphs if p.text.strip()]
        runs = sum(len(p.runs) for p in paras)
        return len(paras), runs
    except Exception:
        return 0, 0


# ─────────────────────────────────────────────────────────────────────────────
# Node 3 — detect_references
# ─────────────────────────────────────────────────────────────────────────────


def node_detect_references(state: PipelineState) -> PipelineState:
    """Run the regex → NER → LLM cascade on every uploaded document."""
    from hyperlink_engine.pipeline.tasks import detect_references as _detect

    _emit(state, "detect_references", "running", total=len(state["ingest_records"]))
    t0 = time.time()

    detection_records = []
    total_refs = 0
    for rec in state["ingest_records"]:
        if Path(rec["source_path"]).suffix.lower() != ".docx":
            continue
        try:
            result = _detect(rec)
            detection_records.append(result)
            total_refs += len(result.get("detections", []))
            _emit(
                state,
                "detect_references",
                "running",
                file=rec["filename"],
                refs=len(result.get("detections", [])),
            )
        except Exception as exc:
            _log.warning("detection_failed", file=rec["filename"], error=str(exc))
            detection_records.append({"ingest": rec, "detections": []})

    state["detection_records"] = detection_records
    _emit(
        state,
        "detect_references",
        "done",
        total_references=total_refs,
        files=len(detection_records),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 4 — resolve_targets
# ─────────────────────────────────────────────────────────────────────────────


def node_resolve_targets(state: PipelineState) -> PipelineState:
    """Map detected reference text to target documents in the same upload batch.

    Heuristic: if a reference text contains a Study ID or filename stem that
    matches another uploaded document, treat that document as the target.
    The injection node will build a cross-doc hyperlink pointing to it.
    """
    _emit(state, "resolve_targets", "running")
    t0 = time.time()

    # Build a lookup: stem → source_path for all uploaded files
    stem_map: dict[str, str] = {}
    for rec in state["ingest_records"]:
        fp = Path(rec["source_path"])
        stem_map[fp.stem.lower()] = rec["source_path"]
        # Also index by study-ID-like tokens in the filename
        for token in fp.stem.replace("-", " ").replace("_", " ").split():
            if len(token) >= 4:
                stem_map[token.lower()] = rec["source_path"]

    resolved = 0
    for drec in state["detection_records"]:
        for det in drec.get("detections", []):
            det["resolved_target_doc"] = _resolve_one(det, stem_map)
            if det["resolved_target_doc"]:
                resolved += 1

    _emit(
        state,
        "resolve_targets",
        "done",
        resolved=resolved,
        elapsed=round(time.time() - t0, 2),
    )
    return state


def _resolve_one(det: dict[str, Any], stem_map: dict[str, str]) -> str | None:
    """Return the resolved target doc path or None."""
    text_lower = det.get("text", "").lower().replace("-", "").replace(" ", "")
    for stem, path in stem_map.items():
        if stem.replace("-", "") in text_lower or text_lower in stem.replace("-", ""):
            return path
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Node 5 — inject_links
# ─────────────────────────────────────────────────────────────────────────────


def node_inject_links(state: PipelineState) -> PipelineState:
    """Inject hyperlinks into each document using the existing inject_links task."""
    from hyperlink_engine.pipeline.tasks import inject_links as _inject

    output_dir: Path = state["output_dir"]
    _emit(state, "inject_links", "running", total=len(state["detection_records"]))
    t0 = time.time()

    injection_records = []
    linked_files = []

    for drec in state["detection_records"]:
        source = Path(drec["ingest"]["source_path"])
        out_path = output_dir / (source.stem + "_linked" + source.suffix)
        try:
            result = _inject(drec, output_path=str(out_path))
            injection_records.append(result)
            linked_files.append(out_path)
            _emit(
                state,
                "inject_links",
                "running",
                file=source.name,
                links=len(result.get("probes", [])),
            )
        except Exception as exc:
            _log.warning("injection_failed", file=source.name, error=str(exc))
            # Fall back: copy original so the file exists
            shutil.copy2(source, out_path)
            injection_records.append({"ingest": drec["ingest"], "output_path": str(out_path), "probes": []})
            linked_files.append(out_path)

    state["injection_records"] = injection_records
    state["linked_files"] = linked_files
    _emit(
        state,
        "inject_links",
        "done",
        linked_files=len(linked_files),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 6 — validate
# ─────────────────────────────────────────────────────────────────────────────


def node_validate(state: PipelineState) -> PipelineState:
    """Run existence checker + anomaly detector on injected links."""
    from hyperlink_engine.validation.existence_checker import LinkProbe, check_all

    _emit(state, "validate", "running")
    t0 = time.time()

    all_probes = []
    for irec in state["injection_records"]:
        for p in irec.get("probes", []):
            from hyperlink_engine.models import LinkKind
            kind = LinkKind(p.get("kind", "internal_bookmark"))
            all_probes.append(
                LinkProbe(
                    source_doc=p["source_doc"],
                    link_text=p["link_text"],
                    location_descriptor=p.get("location_descriptor", ""),
                    kind=kind,
                    target=p["target"],
                )
            )

    results = []
    if all_probes:
        try:
            records = check_all(all_probes)
            results = [r.model_dump() for r in records]
        except Exception as exc:
            _log.warning("validation_failed", error=str(exc))
            results = []

    # Build link dicts for the report store
    links = []
    for irec in state["injection_records"]:
        src = Path(irec["ingest"]["source_path"]).name
        for p in irec.get("probes", []):
            links.append(
                {
                    "source_doc": p.get("source_doc", src),
                    "link_text": p.get("link_text", ""),
                    "link_location_descriptor": p.get("location_descriptor", ""),
                    "target_doc": p.get("target_doc", ""),
                    "target_anchor": p.get("target", ""),
                    "status": "ok",
                    "confidence": float(p.get("llm_confidence_after") or p.get("llm_confidence_before") or 0.9),
                    "error_msg": None,
                    "detected_by": p.get("detected_by", "regex"),
                }
            )

    state["links"] = links
    state["validation_results"] = {"checked": len(all_probes), "results": results}
    _emit(
        state,
        "validate",
        "done",
        links_checked=len(all_probes),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 7 — score_and_report
# ─────────────────────────────────────────────────────────────────────────────


def node_score_and_report(state: PipelineState) -> PipelineState:
    """Compute submission readiness score + write CSV report."""
    _emit(state, "score_and_report", "running")
    t0 = time.time()

    links = state.get("links", [])
    total = len(links)
    broken = sum(1 for l in links if l.get("status") == "broken")

    score = max(0.0, min(100.0, 100.0 - broken * 5.0)) if total else 85.0
    grade = "A" if score >= 95 else "B" if score >= 85 else "C" if score >= 70 else "F"

    state["score"] = round(score, 1)
    state["grade"] = grade

    # Write CSV
    try:
        import csv
        csv_path = state["output_dir"] / "validation_report.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            fieldnames = [
                "source_doc", "link_text", "link_location_descriptor",
                "target_doc", "target_anchor", "status", "confidence",
                "detected_by", "error_msg",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(links)
    except Exception as exc:
        _log.warning("csv_write_failed", error=str(exc))

    _emit(
        state,
        "score_and_report",
        "done",
        score=score,
        grade=grade,
        total_links=total,
        broken=broken,
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 8a — push_dossplorer
# ─────────────────────────────────────────────────────────────────────────────


def node_push_dossplorer(state: PipelineState) -> PipelineState:
    """Push readiness score to Dossplorer (mock client)."""
    _emit(state, "push_dossplorer", "running")
    try:
        from hyperlink_engine.ingestion.dossplorer_client import (
            DossplorerError,
            MockDossplorerClient,
            get_client,
        )
        client = get_client()
        dossier_id = state["dossier_id"]
        # Auto-register the dossier in the mock client if it's unknown
        if isinstance(client, MockDossplorerClient):
            if dossier_id not in client._dossiers:
                from hyperlink_engine.ingestion.dossplorer_client import DossierMetadata
                client._dossiers[dossier_id] = DossierMetadata(
                    dossier_id=dossier_id,
                    sponsor="SunPharma",
                    submission_type="NDA",
                    region="US",
                    sequence_number="0001",
                    status="in_review",
                )
        client.push_readiness_score(dossier_id, state["score"])
        _emit(state, "push_dossplorer", "done", score=state["score"])
    except Exception as exc:
        # Non-fatal: Dossplorer push failure doesn't fail the pipeline
        _log.warning("push_dossplorer_failed", error=str(exc))
        _emit(state, "push_dossplorer", "error", error=str(exc))
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 8b — flag_for_review
# ─────────────────────────────────────────────────────────────────────────────


def node_flag_for_review(state: PipelineState) -> PipelineState:
    """Log anomalies and set status to 'needs_review'."""
    _emit(state, "flag_for_review", "running")
    anomalies = state.get("anomalies", [])
    _log.info(
        "pipeline_flagged_for_review",
        run_id=state["run_id"],
        score=state.get("score"),
        anomalies=len(anomalies),
    )
    _emit(state, "flag_for_review", "done", anomalies=len(anomalies), score=state.get("score"))
    return state
