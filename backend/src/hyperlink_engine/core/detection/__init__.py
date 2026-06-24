"""hyperlink_engine.core.detection — Layer 3 reference detection.

Public API:
  * ``EntityExtractor``    — unified regex + NER + LLM cascade
  * ``regex_only``         — build a regex-only extractor
  * ``regex_plus_ner``     — regex + spaCy NER extractor
  * ``full_cascade``       — regex + NER + local LLM extractor
"""

from hyperlink_engine.core.detection.entity_extractor import (  # noqa: F401
    EntityExtractor,
    full_cascade,
    regex_only,
    regex_plus_ner,
)
