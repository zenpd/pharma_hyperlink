"""Detection-layer agents — regex / regex+NER / full hybrid cascade.

Each agent re-implements the per-document loop of ``node_detect_references``
but passes a specific ``ExtractorConfig`` so the caller can trade speed for
accuracy. The existing ``node_detect_references`` is left untouched.

  * ``detect_regex``  → regex only            (fastest)
  * ``detect_ner``    → regex + spaCy NER      (default / current behavior)
  * ``detect_hybrid`` → regex + NER + local LLM (max accuracy)
"""

from __future__ import annotations

import time
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.orchestration.agents.base import AgentSpec, Layer
from hyperlink_engine.orchestration.nodes import _emit
from hyperlink_engine.orchestration.state import PipelineState
from hyperlink_engine.workers.cache import ExtractorConfig

_log = get_logger("orchestration.agents.detect")


def _run_detect(state: PipelineState, cfg: ExtractorConfig, agent_id: str) -> PipelineState:
    """Shared detection loop, parametrized by extractor configuration."""
    from hyperlink_engine.workers.tasks import detect_references as _detect

    _emit(state, "detect_references", "running",
          total=len(state["ingest_records"]), agent=agent_id)
    t0 = time.time()

    detection_records = []
    total_refs = 0
    for rec in state["ingest_records"]:
        if Path(rec["source_path"]).suffix.lower() not in (".docx", ".pdf"):
            continue
        try:
            result = _detect(rec, extractor_config=cfg.__dict__)
            detection_records.append(result)
            total_refs += len(result.get("detections", []))
            _emit(state, "detect_references", "running",
                  file=rec["filename"], refs=len(result.get("detections", [])))
        except Exception as exc:  # noqa: BLE001 — match node_detect_references resilience
            _log.warning("detection_failed", file=rec["filename"], error=str(exc))
            detection_records.append({"ingest": rec, "detections": []})

    state["detection_records"] = detection_records
    _emit(state, "detect_references", "done",
          total_references=total_refs, files=len(detection_records),
          agent=agent_id, elapsed=round(time.time() - t0, 2))
    return state


DETECT_REGEX = AgentSpec(
    id="detect_regex",
    layer=Layer.detect,
    label="Regex only",
    description="Deterministic regex pattern catalog. Fastest; no ML. Best for clean, well-formatted dossiers.",
    run=lambda s: _run_detect(s, ExtractorConfig.regex_only(), "detect_regex"),
)

DETECT_NER = AgentSpec(
    id="detect_ner",
    layer=Layer.detect,
    label="Regex + NER",
    description="Regex plus spaCy NER for fuzzy / contextual references. Balanced default.",
    run=lambda s: _run_detect(s, ExtractorConfig.regex_plus_ner(), "detect_ner"),
    is_default=True,
)

DETECT_HYBRID = AgentSpec(
    id="detect_hybrid",
    layer=Layer.detect,
    label="Regex + NER + LLM",
    description="Full cascade: every span is disambiguated by the local Ollama LLM. Highest accuracy, slowest.",
    # prefer_stub=False → this agent tries the real local Ollama daemon first
    # and only falls back to the deterministic stub if Ollama is unreachable.
    # force_refine=True → the LLM is consulted for EVERY span, not just the
    # low-confidence ones. The regex catalog emits 0.92–0.99 confidence, so
    # without this the LLM would be skipped on essentially every reference and
    # detected_by would always read "regex" (which is exactly what we observed
    # in Neo4j). This makes "Max accuracy" genuinely reach Ollama.
    run=lambda s: _run_detect(
        s,
        ExtractorConfig.full_cascade(prefer_stub=False, force_refine=True),
        "detect_hybrid",
    ),
)

DETECT_AGENTS = [DETECT_REGEX, DETECT_NER, DETECT_HYBRID]
