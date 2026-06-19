"""Layer 3 orchestrator: regex → NER → conflict resolution → LLM refinement.

Each stage can be disabled independently — the W1.5 spike runs regex-only,
W3 enables NER, and the LLM stage runs only on the survivors whose
confidence sits below ``llm_confidence_threshold``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.core.detection.llm_disambiguator import (
    DisambiguationDecision,
    LlmDisambiguator,
)
from hyperlink_engine.core.detection.ner_model import SpacyNerExtractor
from hyperlink_engine.core.detection.regex_patterns import (
    Match,
    PatternRegistry,
    default_registry,
    resolve_overlaps,
)

_log = get_logger("detection.extractor")


@dataclass(frozen=True)
class ExtractedReference:
    """The post-resolution shape consumed by the injection layer."""

    pattern_id: str
    label: str  # mirrors the NER label / regex catalog label
    text: str
    start: int
    end: int
    confidence: float
    source_layer: str  # "regex" | "ner" | "llm" | "merged"
    groups: dict[str, str]
    # Traceability fields (optional, populated if verbose mode enabled)
    llm_consulted: bool = False
    llm_confidence_before: float = 0.0
    llm_confidence_after: float = 0.0
    llm_reasoning: str = ""


class EntityExtractor:
    """Run every active detection layer and return a deduplicated list."""

    def __init__(
        self,
        registry: PatternRegistry | None = None,
        ner_extractor: SpacyNerExtractor | None = None,
        llm_disambiguator: LlmDisambiguator | None = None,
        verbose: bool = False,
    ) -> None:
        self._registry = registry or default_registry()
        self._ner = ner_extractor
        self._llm = llm_disambiguator
        self._settings = get_settings()
        self._verbose = verbose

    # ── Public extraction API ────────────────────────────────────────────

    def extract(self, text: str) -> list[ExtractedReference]:
        if not text:
            return []

        regex_matches = self._registry.find_all(text)
        ner_matches = list(self._ner.extract(text)) if self._ner is not None else []

        # Track source layer for every Match so we can report it after merge.
        source_by_match: dict[int, str] = {}
        for m in regex_matches:
            source_by_match[id(m)] = "regex"
        for m in ner_matches:
            source_by_match[id(m)] = "ner"

        resolved = resolve_overlaps(regex_matches + ner_matches)

        llm_metadata: dict[int, dict[str, Any]] = {}
        if self._llm is not None and self._llm.should_refine(resolved):
            resolved = self._apply_llm(resolved, text, source_by_match, llm_metadata)

        out: list[ExtractedReference] = []
        for m in resolved:
            layer = source_by_match.get(id(m), "merged")
            meta = llm_metadata.get(id(m), {})
            out.append(
                ExtractedReference(
                    pattern_id=m.pattern_id,
                    label=self._label_for(m),
                    text=m.text,
                    start=m.start,
                    end=m.end,
                    confidence=m.confidence,
                    source_layer=layer,
                    groups=dict(m.groups),
                    llm_consulted=meta.get("llm_consulted", False),
                    llm_confidence_before=meta.get("llm_confidence_before", 0.0),
                    llm_confidence_after=meta.get("llm_confidence_after", 0.0),
                    llm_reasoning=meta.get("llm_reasoning", ""),
                )
            )
        _log.info(
            "detection_extract",
            regex_hits=len(regex_matches),
            ner_hits=len(ner_matches),
            after_merge=len(resolved),
            chars=len(text),
        )
        return out

    # ── internal ─────────────────────────────────────────────────────────

    def _apply_llm(
        self,
        merged: list[Match],
        source_text: str,
        source_by_match: dict[int, str],
        llm_metadata: dict[int, dict[str, Any]],
    ) -> list[Match]:
        """For each low-confidence match, ask the LLM to refine it.

        We refine **per-span**, not over the full document — the LLM gets a
        windowed context around the span via the disambiguator. The result
        replaces the original match in-place; if the LLM declines (returns
        None), we keep the original.

        If verbose, logs all LLM calls with before/after confidence.
        """
        if not self._llm:
            return merged
        # Prefer the disambiguator's configured threshold so callers that pass
        # an explicit threshold to LlmDisambiguator see it honored end-to-end.
        # Fall back to the global settings value when the disambiguator hasn't
        # been customized.
        threshold = self._llm.confidence_threshold
        # When force_refine is on, every span goes to the LLM regardless of
        # how confident regex/NER were — this de-prioritises the fast layers
        # so the LLM is always exercised.
        force = self._llm.force_refine
        refined: list[Match] = []
        for m in merged:
            if not force and m.confidence >= threshold:
                refined.append(m)
                continue
            decision: DisambiguationDecision | None = self._llm.refine(
                [m], source_text=source_text
            )
            if decision is None:
                refined.append(m)
                continue

            if self._verbose:
                _log.info(
                    "llm_refinement",
                    text=m.text,
                    confidence_before=m.confidence,
                    confidence_after=decision.chosen.confidence,
                    pattern_before=m.pattern_id,
                    pattern_after=decision.chosen.pattern_id,
                    rationale=decision.rationale,
                    model=decision.model,
                )

            refined.append(decision.chosen)
            source_by_match[id(decision.chosen)] = "llm"
            llm_metadata[id(decision.chosen)] = {
                "llm_consulted": True,
                "llm_confidence_before": m.confidence,
                "llm_confidence_after": decision.chosen.confidence,
                "llm_reasoning": decision.rationale or "",
            }
        return refined

    def _label_for(self, match: Match) -> str:
        # NER matches carry the label in their groups dict; regex matches look
        # the label up in the registry. Either path gives the same result.
        if "label" in match.groups:
            return match.groups["label"]
        try:
            return self._registry.get(match.pattern_id).label
        except KeyError:
            return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────
# Builder helpers — wire commonly-used configurations.
# ─────────────────────────────────────────────────────────────────────────


def regex_only() -> EntityExtractor:
    """Phase 1 W1.5 / fast-path configuration."""
    return EntityExtractor()


def regex_plus_ner() -> EntityExtractor:
    """W3.2 configuration — adds the spaCy NER layer with a rule fallback."""
    return EntityExtractor(ner_extractor=SpacyNerExtractor())


def full_cascade(
    *, prefer_stub: bool = False, force_refine: bool | None = None
) -> EntityExtractor:
    """W3.4 configuration — regex + NER + local LLM refinement.

    ``force_refine`` (when not None) overrides the global ``llm_force_refine``
    setting: pass True to send every span to the LLM regardless of regex/NER
    confidence. The "Max accuracy" detect agent uses this so the local Ollama
    model is genuinely consulted (the regex catalog's 0.92–0.99 confidence would
    otherwise keep every span above the threshold and skip the LLM).
    """
    from hyperlink_engine.core.detection.llm_disambiguator import build_disambiguator

    return EntityExtractor(
        ner_extractor=SpacyNerExtractor(),
        llm_disambiguator=build_disambiguator(
            prefer_stub=prefer_stub, force_refine=force_refine
        ),
    )


def source_summary(refs: list[ExtractedReference]) -> dict[str, int]:
    """Quick per-layer histogram for benchmarks and logs."""
    counts: dict[str, int] = defaultdict(int)
    for r in refs:
        counts[r.source_layer] += 1
    return dict(counts)
