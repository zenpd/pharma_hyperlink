"""Layer 3 — spaCy NER wrapper.

Two modes:

1. **Trained model** — if a fine-tuned model directory exists at the
   configured path (default ``models/ner_v1/``), load it.

2. **Rule fallback** — otherwise build an ``EntityRuler``-backed pipeline
   from the regex catalog so the system has a working NER component from
   day 1. The fallback is **not** as good as a trained model, but it lets
   the rest of the detection pipeline run, lets tests exercise the
   interface, and gives the W3 benchmark a realistic baseline to beat.

The wrapper exposes a small, stable interface:

    extractor = SpacyNerExtractor()      # auto-selects trained or fallback
    matches = extractor.extract(text)    # -> list[Match] (regex_patterns.Match)

so the EntityExtractor orchestrator can treat regex and NER interchangeably.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.detection.regex_patterns import (
    Match,
    Pattern,
    PatternRegistry,
    default_registry,
)

_log = get_logger("detection.ner")


# ─────────────────────────────────────────────────────────────────────────
# Catalog of EntityRuler patterns derived from the regex catalog.
# These are deliberately shape-only — they let the fallback pipeline assign
# labels to spans the regex engine would have caught.
# ─────────────────────────────────────────────────────────────────────────

_FALLBACK_PATTERNS: list[dict[str, object]] = [
    # Labeled section references: "Section 2.5.3", "Sect. 4.1"
    {
        "label": "SECTION_REF",
        "pattern": [
            {"LOWER": {"IN": ["section", "sect.", "sect", "sec.", "sec"]}},
            {"TEXT": {"REGEX": r"^\d+(?:\.\d+){0,4}$"}},
        ],
    },
    # Section sigil: "§ 2.7.4"
    {
        "label": "SECTION_REF",
        "pattern": [
            {"TEXT": "§"},
            {"TEXT": {"REGEX": r"^\d+(?:\.\d+){0,4}$"}},
        ],
    },
    # "Table 14.2.1.1"
    {
        "label": "TABLE_REF",
        "pattern": [
            {"LOWER": "table"},
            {"TEXT": {"REGEX": r"^\d+(?:[\.\-]\d+){0,4}$"}},
        ],
    },
    # "Figure 11"
    {
        "label": "FIGURE_REF",
        "pattern": [
            {"LOWER": "figure"},
            {"TEXT": {"REGEX": r"^\d+(?:[\.\-]\d+){0,4}$"}},
        ],
    },
    # "Listing 16.2.5"
    {
        "label": "LISTING_REF",
        "pattern": [
            {"LOWER": "listing"},
            {"TEXT": {"REGEX": r"^\d+(?:[\.\-]\d+){0,4}$"}},
        ],
    },
    # "Appendix 16.1.1"
    {
        "label": "APPENDIX_REF",
        "pattern": [
            {"LOWER": "appendix"},
            {"TEXT": {"REGEX": r"^\d+(?:\.\d+){0,3}$"}},
        ],
    },
    # "Module 5.3.1"
    {
        "label": "CTD_LEAF",
        "pattern": [
            {"LOWER": "module"},
            {"TEXT": {"REGEX": r"^[1-5](?:\.\d+){0,3}$"}},
        ],
    },
    # NCT-prefixed clinical trial ID — single token
    {
        "label": "STUDY_ID",
        "pattern": [{"TEXT": {"REGEX": r"^NCT\d{8}$"}}],
    },
    # Sponsor-prefixed study ID like "MED-2020-026". spaCy's English tokenizer
    # splits as [MED-2020, -, 026] (digits-flanked hyphens split, letter-flanked
    # hyphens stay glued), so we match the actual token shapes.
    {
        "label": "STUDY_ID",
        "pattern": [
            {"TEXT": {"REGEX": r"^[A-Z]{2,5}-\d{4}$"}},
            {"TEXT": "-"},
            {"TEXT": {"REGEX": r"^\d{3,4}$"}},
        ],
    },
    # PROT-ABC-1234 → [PROT, -, ABC-1234]
    {
        "label": "STUDY_ID",
        "pattern": [
            {"TEXT": "PROT"},
            {"TEXT": "-"},
            {"TEXT": {"REGEX": r"^[A-Z]{2,5}-\d{4,6}$"}},
        ],
    },

    # ── NER-exclusive patterns (no regex equivalent — these will ONLY be
    #    detected by the NER layer, ensuring ner_triggered > 0 on dossiers
    #    that contain these entity types) ──────────────────────────────────

    # FDA regulatory form references: "Form FDA 1572", "Form FDA-3674A"
    # No regex pattern exists for these — NER exclusively catches them.
    {
        "label": "FORM_REF",
        "pattern": [
            {"LOWER": "form"},
            {"LOWER": {"IN": ["fda", "ich", "ema"]}},
            {"TEXT": {"REGEX": r"^\d{3,4}[A-Z]?$"}},
        ],
    },
    {
        "label": "FORM_REF",
        "pattern": [
            {"LOWER": "form"},
            {"TEXT": {"REGEX": r"^(?:FDA|ICH|EMA)-\d{3,4}[A-Z]?$"}},
        ],
    },

    # Clinical investigator site / centre codes: "Site 001", "Centre 14",
    # "Site US-042".  Distinct from study IDs — no regex covers these.
    {
        "label": "SITE_CODE",
        "pattern": [
            {"LOWER": {"IN": ["site", "centre", "center"]}},
            {"TEXT": {"REGEX": r"^\d{2,4}$"}},
        ],
    },
    {
        "label": "SITE_CODE",
        "pattern": [
            {"LOWER": {"IN": ["site", "centre", "center"]}},
            {"TEXT": {"REGEX": r"^[A-Z]{2}-\d{2,4}$"}},
        ],
    },

    # IMP batch / lot references: "Batch No. A2024-001", "Lot 2024B-001"
    {
        "label": "IMP_BATCH",
        "pattern": [
            {"LOWER": "batch"},
            {"LOWER": {"IN": ["no.", "no", "number", "#"]}},
            {"TEXT": {"REGEX": r"^[A-Z0-9]{4,12}(?:-[A-Z0-9]+)?$"}},
        ],
    },
    {
        "label": "IMP_BATCH",
        "pattern": [
            {"LOWER": "lot"},
            {"TEXT": {"REGEX": r"^[A-Z0-9]{4,12}(?:-[A-Z0-9]+)?$"}},
        ],
    },

    # MedDRA-coded adverse-event references: "MedDRA PT: Hepatotoxicity",
    # "MedDRA SOC: Hepatobiliary disorders".  The regex catalog has no
    # MedDRA-specific patterns — these will exclusively hit the NER layer.
    {
        "label": "AE_CODE",
        "pattern": [
            {"LOWER": "meddra"},
            {"LOWER": {"IN": ["pt:", "pt", "soc:", "soc", "hlgt:", "hlgt", "llt:", "llt"]}},
        ],
    },

    # eCTD submission sequence references: "Sequence 0001", "Seq. 0002"
    # Not in the regex catalog.
    {
        "label": "SEQUENCE_REF",
        "pattern": [
            {"LOWER": {"IN": ["sequence", "seq.", "seq"]}},
            {"TEXT": {"REGEX": r"^\d{4}$"}},
        ],
    },
]


@dataclass(frozen=True)
class NerConfig:
    """How the NER wrapper should bootstrap."""

    model_path: Path | None = None
    base_model: str = "en_core_web_sm"
    confidence: float = 0.80
    label_filter: tuple[str, ...] = field(default_factory=tuple)


def _try_load_spacy() -> Any | None:
    """Import spaCy lazily so the module is importable even if spaCy isn't installed."""
    try:
        import spacy  # type: ignore[import-not-found]

        return spacy
    except ImportError:
        _log.warning("spacy_not_installed")
        return None


def _build_fallback_pipeline(spacy_mod, base_model: str):  # type: ignore[no-untyped-def]
    """Return a small spaCy pipeline with an EntityRuler pre-loaded.

    Prefers a blank English model so we don't pay download cost for
    ``en_core_web_sm`` just to run the EntityRuler.
    """
    try:
        nlp = spacy_mod.load(base_model, disable=["ner", "lemmatizer"])
    except (OSError, IOError):
        nlp = spacy_mod.blank("en")

    if "entity_ruler" not in nlp.pipe_names:
        ruler = nlp.add_pipe(
            "entity_ruler",
            config={"overwrite_ents": True, "validate": True},
        )
    else:
        ruler = nlp.get_pipe("entity_ruler")
    ruler.add_patterns(_FALLBACK_PATTERNS)
    return nlp


class SpacyNerExtractor:
    """Adapter that runs a spaCy pipeline and yields Match records.

    The output is intentionally Match-shaped (same dataclass the regex
    engine produces) so EntityExtractor can merge regex and NER hits with
    one conflict-resolution call.
    """

    def __init__(
        self,
        config: NerConfig | None = None,
        registry: PatternRegistry | None = None,
    ) -> None:
        self.config = config or NerConfig()
        self._registry = registry or default_registry()
        self._spacy = _try_load_spacy()
        self._nlp = None
        self._mode: str = "disabled"
        if self._spacy is None:
            _log.warning("ner_disabled_no_spacy")
            return
        self._nlp = self._bootstrap_pipeline()

    # ── bootstrap ────────────────────────────────────────────────────────

    def _bootstrap_pipeline(self):  # type: ignore[no-untyped-def]
        spacy_mod = self._spacy
        assert spacy_mod is not None  # for type checkers
        path = self.config.model_path
        # When the caller didn't pin a model, consult settings.ner_model_path so a
        # trained model can be enabled by config/env (HYPERLINK_NER_MODEL_PATH)
        # without changing the default rule-fallback behavior the suite relies on.
        if path is None:
            try:
                from hyperlink_engine.config.settings import get_settings

                sp = get_settings().ner_model_path
                path = Path(sp) if sp else None
            except Exception:  # noqa: BLE001 — settings optional; degrade to fallback
                path = None
        if path and Path(path).exists():
            try:
                nlp = spacy_mod.load(str(path))
                self._mode = f"trained:{path}"
                _log.info("ner_trained_model_loaded", path=str(path))
                return nlp
            except Exception as exc:  # noqa: BLE001 — log + fall through
                _log.warning("ner_trained_load_failed", path=str(path), error=str(exc))
        nlp = _build_fallback_pipeline(spacy_mod, self.config.base_model)
        self._mode = "rule_fallback"
        _log.info("ner_rule_fallback_active", labels=sorted({p["label"] for p in _FALLBACK_PATTERNS}))
        return nlp

    @property
    def mode(self) -> str:
        return self._mode

    # ── public extraction API ────────────────────────────────────────────

    def extract(self, text: str) -> list[Match]:
        return list(self._iter_matches(text))

    def _iter_matches(self, text: str) -> Iterator[Match]:
        if self._nlp is None or not text:
            return iter(())
        doc = self._nlp(text)
        for ent in doc.ents:
            label = ent.label_
            if self.config.label_filter and label not in self.config.label_filter:
                continue
            pattern_id = f"NER_{label}_V1"
            yield Match(
                pattern_id=pattern_id,
                text=ent.text,
                start=ent.start_char,
                end=ent.end_char,
                confidence=self.config.confidence,
                groups={"label": label, "source": self._mode},
            )

    # ── compatibility with EntityExtractor protocol ─────────────────────

    def label_for(self, pattern_id: str) -> str:
        if pattern_id.startswith("NER_") and pattern_id.endswith("_V1"):
            return pattern_id[len("NER_") : -len("_V1")]
        try:
            return self._registry.get(pattern_id).label
        except KeyError:
            return "UNKNOWN"


def labels_in_fallback() -> set[str]:
    """Convenience accessor for tests/benchmarks."""
    return {str(p["label"]) for p in _FALLBACK_PATTERNS}


def fallback_patterns() -> Iterable[dict[str, object]]:
    """Read-only view of the fallback EntityRuler patterns."""
    return tuple(_FALLBACK_PATTERNS)


# Re-export for type symmetry with regex_patterns
__all__ = [
    "NerConfig",
    "SpacyNerExtractor",
    "labels_in_fallback",
    "fallback_patterns",
    "Pattern",
]
