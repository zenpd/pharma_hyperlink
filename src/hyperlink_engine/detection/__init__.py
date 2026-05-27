"""Layer 3: AI/NLP reference detection - regex + spaCy NER + local LLM."""

from hyperlink_engine.detection.regex_patterns import (
    Match,
    PatternRegistry,
    default_registry,
)

__all__ = ["Match", "PatternRegistry", "default_registry"]
