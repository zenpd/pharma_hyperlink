"""Layer 3 orchestrator: regex → NER → conflict resolution → LLM refinement.

Each stage can be disabled independently — the W1.5 spike runs regex-only,
W3 enables NER, and the LLM stage runs only on the survivors whose
confidence sits below ``llm_confidence_threshold``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.detection.llm_disambiguator import (
    DisambiguationDecision,
    LlmDisambiguator,
)
from hyperlink_engine.detection.ner_model import SpacyNerExtractor
from hyperlink_engine.detection.regex_patterns import (
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


class EntityExtractor:
    """Run every active detection layer and return a deduplicated list."""

    def __init__(
        self,
        registry: PatternRegistry | None = None,
        ner_extractor: SpacyNerExtractor | None = None,
        llm_disambiguator: LlmDisambiguator | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._ner = ner_extractor
        self._llm = llm_disambiguator
        self._settings = get_settings()

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

        if self._llm is not None and self._llm.should_refine(resolved):
            resolved = self._apply_llm(resolved, text, source_by_match)

        out: list[ExtractedReference] = []
        for m in resolved:
            layer = source_by_match.get(id(m), "merged")
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
    ) -> list[Match]:
        """For each low-confidence match, ask the LLM to refine it.

        We refine **per-span**, not over the full document — the LLM gets a
        windowed context around the span via the disambiguator. The result
        replaces the original match in-place; if the LLM declines (returns
        None), we keep the original.
        """
        if not self._llm:
            return merged
        # Prefer the disambiguator's configured threshold so callers that pass
        # an explicit threshold to LlmDisambiguator see it honored end-to-end.
        # Fall back to the global settings value when the disambiguator hasn't
        # been customized.
        threshold = self._llm.confidence_threshold
        refined: list[Match] = []
        for m in merged:
            if m.confidence >= threshold:
                refined.append(m)
                continue
            decision: DisambiguationDecision | None = self._llm.refine(
                [m], source_text=source_text
            )
            if decision is None:
                refined.append(m)
                continue
            refined.append(decision.chosen)
            source_by_match[id(decision.chosen)] = "llm"
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


def full_cascade(*, prefer_stub: bool = False) -> EntityExtractor:
    """W3.4 configuration — regex + NER + local LLM refinement."""
    from hyperlink_engine.detection.llm_disambiguator import build_disambiguator

    return EntityExtractor(
        ner_extractor=SpacyNerExtractor(),
        llm_disambiguator=build_disambiguator(prefer_stub=prefer_stub),
    )


def source_summary(refs: list[ExtractedReference]) -> dict[str, int]:
    """Quick per-layer histogram for benchmarks and logs."""
    counts: dict[str, int] = defaultdict(int)
    for r in refs:
        counts[r.source_layer] += 1
    return dict(counts)
