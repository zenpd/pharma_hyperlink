# Detection cascade

Layer 3 — find reference spans via regex → NER → an optional local LLM.

## How it works
- Regex is the dominant layer: the pattern catalog in `core/detection/regex_patterns.py` (Study-ID, Section, Table, Figure, Appendix, Listing, CTD-leaf, Visit, `DOC_REF`/`DOC_ID` cross-references, external refs).
- spaCy NER (rule fallback / opt-in trained model) `core/detection/ner_model.py`, orchestrated with overlap-resolution by `core/detection/entity_extractor.py`.
- GLiNER author-name citation detector, gated by `HYPERLINK_REFERENCE_DETECTOR=hybrid`: `core/detection/gliner_refs.py`.
- Local-only LLM type-disambiguator (Ollama / deterministic stub), idle by default: `core/detection/llm_disambiguator.py`.

## Gotchas
- On real docs regex catches ~all linkable cross-refs; NER/GLiNER/LLM are top-ups. The LLM is off unless Max-Accuracy / `force_refine`.

## Related
[[Resolution and anchoring]] · [[Parsing layer]] · [[Orchestration and agents]] · [[_Home]]
