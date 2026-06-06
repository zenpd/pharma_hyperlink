"""W7.1 — Pipeline stage tasks.

Each task is a thin wrapper around an existing pure-Python implementation
(from ``detection/``, ``injection/``, ``validation/``…) so that:

  * It can be invoked **synchronously** for tests and the W1.5 spike
    (the underlying function is a normal Python call).
  * It can be invoked **asynchronously** via Celery for the bulk pipeline.

The Celery wiring uses the same factory pattern as Phase 1's Neo4j
adapter — Celery is imported only when ``celery_eager=False`` and a real
worker is running. In eager mode (the default in tests), every Celery
``.delay()`` call returns an ``EagerResult`` containing the synchronous
return value, so callers don't need a branch.

All task inputs and outputs are JSON-serializable (Celery requirement).
Pydantic models flow through ``.model_dump()`` / ``.model_validate()``.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.injection.docx_linker import DocxLinker
from hyperlink_engine.models import (
    LinkKind,
    LinkRecord,
    LinkStatus,
    RunLocation,
)
from hyperlink_engine.pipeline.cache import ExtractorConfig, get_extractor
from hyperlink_engine.pipeline.celery_app import (
    PIPELINE_STAGES,
    get_app,
    stage_task_name,
)
from hyperlink_engine.reporting.csv_exporter import write_link_records
from hyperlink_engine.validation.existence_checker import LinkProbe, check_all

_log = get_logger("pipeline.tasks")


# ─────────────────────────────────────────────────────────────────────────
# Stage 1 — ingestion: hash the source doc so downstream stages know it
# ─────────────────────────────────────────────────────────────────────────


def ingest_document(source_path: str) -> dict[str, Any]:
    """Stage 1 (synchronous primitive).

    Computes a streaming SHA-256 of the source document. The result rides
    along through every downstream stage so the audit log can prove the
    pipeline acted on a specific document version (21 CFR Part 11 trail).
    """
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(source_path)
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            sha.update(chunk)
    size = path.stat().st_size
    return {
        "source_path": str(path),
        "sha256": sha.hexdigest(),
        "file_size_bytes": size,
    }


# ─────────────────────────────────────────────────────────────────────────
# Stage 2 — detection
# ─────────────────────────────────────────────────────────────────────────


def detect_references(
    ingest_record: dict[str, Any],
    *,
    extractor_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage 2 — run the cascade against every paragraph/run.

    Returns a flat list of detection records (one per detected span)
    plus the original ingest record for downstream stages.
    """
    cfg = ExtractorConfig(**(extractor_config or {}))
    extractor = get_extractor(cfg)
    doc = Document(ingest_record["source_path"])
    detections: list[dict[str, Any]] = []
    for p_idx, para in enumerate(doc.paragraphs):
        for r_idx, run in enumerate(para.runs):
            if not run.text or not run.text.strip():
                continue
            for ref in extractor.extract(run.text):
                detections.append(
                    {
                        "paragraph_index": p_idx,
                        "run_index": r_idx,
                        "char_start": ref.start,
                        "char_end": ref.end,
                        "pattern_id": ref.pattern_id,
                        "label": ref.label,
                        "text": ref.text,
                        "confidence": ref.confidence,
                        "source_layer": ref.source_layer,
                        "groups": dict(ref.groups),
                        "llm_consulted": ref.llm_consulted,
                        "llm_confidence_before": ref.llm_confidence_before,
                        "llm_confidence_after": ref.llm_confidence_after,
                        "llm_reasoning": ref.llm_reasoning,
                    }
                )
    return {"ingest": ingest_record, "detections": detections}


# ─────────────────────────────────────────────────────────────────────────
# Stage 3 — injection
# ─────────────────────────────────────────────────────────────────────────


def inject_links(
    detection_record: dict[str, Any],
    *,
    output_path: str,
) -> dict[str, Any]:
    """Stage 3 — turn detected references into actual hyperlinks.

    Mirrors the Phase 1 acceptance script's target-resolution heuristic
    so the gate scoreboard reproduces byte-for-byte from the new pipeline.
    """
    source = Path(detection_record["ingest"]["source_path"])
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    linker = DocxLinker(source, out)
    declared_anchors: set[str] = set()
    probes: list[dict[str, Any]] = []

    for det in detection_record["detections"]:
        location = RunLocation(
            paragraph_index=det["paragraph_index"],
            run_index=det["run_index"],
            char_start=det["char_start"],
            char_end=det["char_end"],
        )
        kind, target = _resolve_target(det)
        if kind == LinkKind.EXTERNAL_URL:
            linker.add_external_link(location, url=target)
        else:
            linker.add_internal_link(location, anchor=target)
            if target not in declared_anchors:
                declared_anchors.add(target)
                linker.add_bookmark(location, target)
        probes.append(
            {
                "source_doc": source.name,
                "link_text": det["text"],
                "location_descriptor": (
                    f"p{det['paragraph_index']}.r{det['run_index']}"
                    f":c{det['char_start']}-{det['char_end']}"
                ),
                "kind": kind.value,
                "target": target,
                "target_doc": str(out),
                "detected_by": det.get("source_layer"),
                "ner_pattern": det.get("pattern_id") if det.get("source_layer") == "ner" else None,
                "llm_called": det.get("llm_consulted", False) or det.get("source_layer") == "llm",
                "llm_confidence_before": det.get("llm_confidence_before"),
                "llm_confidence_after": det.get("llm_confidence_after"),
            }
        )
    linker.save()
    return {
        "ingest": detection_record["ingest"],
        "output_path": str(out),
        "probes": probes,
    }


def _resolve_target(det: dict[str, Any]) -> tuple[LinkKind, str]:
    """Phase-1 heuristic mirrored from scripts/phase1_acceptance.py."""
    label = det["label"]
    groups = det.get("groups", {})
    text = det["text"]
    if label in {"SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"}:
        num = groups.get("num") or text
        slug = num.replace(".", "_").replace("-", "_")
        return LinkKind.INTERNAL_BOOKMARK, f"{label.lower()}_{slug}"
    if label == "STUDY_ID" and det["pattern_id"] == "STUDY_ID_NCT_V1":
        return LinkKind.EXTERNAL_URL, f"https://clinicaltrials.gov/study/{text}"
    if label == "STUDY_ID":
        return LinkKind.INTERNAL_BOOKMARK, f"study_{text.replace('-', '_')}"
    if label == "CTD_LEAF":
        mod = groups.get("mod", "?")
        sub = groups.get("sub", "") or groups.get("subpath", "")
        if sub:
            return (
                LinkKind.INTERNAL_BOOKMARK,
                f"m{mod}_" + sub.replace(".", "_").replace("/", "_"),
            )
        return LinkKind.INTERNAL_BOOKMARK, f"m{mod}"
    return LinkKind.INTERNAL_BOOKMARK, text


# ─────────────────────────────────────────────────────────────────────────
# Stage 4 — validation
# ─────────────────────────────────────────────────────────────────────────


def validate_links(injection_record: dict[str, Any]) -> dict[str, Any]:
    """Stage 4 — run existence checks against the linked output."""
    probes: list[LinkProbe] = []
    for p in injection_record["probes"]:
        probes.append(
            LinkProbe(
                source_doc=p["source_doc"],
                link_text=p["link_text"],
                location_descriptor=p["location_descriptor"],
                kind=LinkKind(p["kind"]),
                target=p["target"],
                target_doc=Path(p["target_doc"]) if p.get("target_doc") else None,
                detected_by=p.get("detected_by"),
                ner_pattern=p.get("ner_pattern"),
                llm_called=p.get("llm_called", False),
                llm_confidence_before=p.get("llm_confidence_before"),
                llm_confidence_after=p.get("llm_confidence_after"),
            )
        )
    records = check_all(probes)
    return {
        "ingest": injection_record["ingest"],
        "output_path": injection_record["output_path"],
        "link_records": [r.model_dump(mode="json") for r in records],
    }


# ─────────────────────────────────────────────────────────────────────────
# Stage 5 — reporting (per-document CSV; the batch runner aggregates)
# ─────────────────────────────────────────────────────────────────────────


def write_per_doc_report(
    validation_record: dict[str, Any],
    *,
    output_path: str,
) -> dict[str, Any]:
    """Stage 5 — write a per-document CSV report and return its path."""
    records = [LinkRecord.model_validate(r) for r in validation_record["link_records"]]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_link_records(records, out)
    return {
        "ingest": validation_record["ingest"],
        "output_path": validation_record["output_path"],
        "report_path": str(out),
        "link_records": validation_record["link_records"],
    }


# ─────────────────────────────────────────────────────────────────────────
# Single-doc orchestration (sync) — convenient for unit tests + the W1.5
# spike. The batch runner uses this in a thread pool for parallelism in
# eager mode, and switches to Celery .apply_async() in production.
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class DocPipelineResult:
    source_path: Path
    output_path: Path
    report_path: Path
    detection_count: int = 0
    link_records: list[LinkRecord] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.link_records if r.status == LinkStatus.OK)

    @property
    def broken_count(self) -> int:
        return sum(1 for r in self.link_records if r.status == LinkStatus.BROKEN)

    @property
    def total_links(self) -> int:
        return len(self.link_records)


def process_document(
    source_path: Path,
    *,
    output_path: Path,
    report_path: Path,
    extractor_config: ExtractorConfig | None = None,
) -> DocPipelineResult:
    """Run all five stages synchronously for one document. Always idempotent."""
    started = time.perf_counter()
    ingest = ingest_document(str(source_path))
    detection = detect_references(
        ingest,
        extractor_config=(extractor_config or ExtractorConfig()).__dict__,
    )
    injection = inject_links(detection, output_path=str(output_path))
    validation = validate_links(injection)
    report = write_per_doc_report(validation, output_path=str(report_path))
    elapsed = time.perf_counter() - started
    link_records = [LinkRecord.model_validate(r) for r in report["link_records"]]
    _log.info(
        "process_document_complete",
        source=str(source_path),
        detections=len(detection["detections"]),
        links=len(link_records),
        duration_s=round(elapsed, 3),
    )
    return DocPipelineResult(
        source_path=source_path,
        output_path=output_path,
        report_path=report_path,
        detection_count=len(detection["detections"]),
        link_records=link_records,
        duration_seconds=elapsed,
    )


# ─────────────────────────────────────────────────────────────────────────
# Celery task registration
# ─────────────────────────────────────────────────────────────────────────


_registered_tasks: dict[str, Callable[..., Any]] = {}


def register_celery_tasks() -> dict[str, Any]:
    """Decorate the stage functions as Celery tasks and return them.

    Called once at import time when Celery is available; safe to call
    multiple times — the second call returns the same handles.
    """
    if _registered_tasks:
        return dict(_registered_tasks)
    settings = get_settings()
    app = get_app()

    stage_action_pairs: list[tuple[str, str, Callable[..., Any]]] = [
        (PIPELINE_STAGES[0], "ingest_document", ingest_document),
        (PIPELINE_STAGES[1], "detect_references", detect_references),
        (PIPELINE_STAGES[2], "inject_links", inject_links),
        (PIPELINE_STAGES[3], "validate_links", validate_links),
        (PIPELINE_STAGES[4], "write_per_doc_report", write_per_doc_report),
    ]
    for stage, action, fn in stage_action_pairs:
        task_name = stage_task_name(stage, action)
        task = app.task(
            name=task_name,
            bind=False,
            autoretry_for=(Exception,),
            retry_backoff=settings.pipeline_retry_backoff_seconds,
            retry_kwargs={"max_retries": settings.pipeline_max_retries},
            acks_late=True,
        )(fn)
        _registered_tasks[task_name] = task
    _log.info("celery_tasks_registered", count=len(_registered_tasks))
    return dict(_registered_tasks)


def get_task(stage: str, action: str) -> Callable[..., Any]:
    """Look up a registered task by stage + action. Auto-registers if needed."""
    if not _registered_tasks:
        register_celery_tasks()
    name = stage_task_name(stage, action)
    if name not in _registered_tasks:
        raise KeyError(f"task {name!r} not registered")
    return _registered_tasks[name]
