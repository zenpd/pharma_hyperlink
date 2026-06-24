# Resolution and anchoring

Decide which document, and which exact spot, each detected reference points to.

## How it works
- Cross-doc target routing: `node_resolve_targets` / `_resolve_one` / `_pick_sibling` in `orchestration/nodes.py` (study-key match → doc-type → source format/folder preference).
- Definition anchoring (land on the heading/caption, not the first citation): `core/injection/anchor_index.py`.
- Literature citation → reference-list entry: `core/injection/ref_index.py`.
- LLM tie-breaker `resolve_v1` for ambiguous ≥2-candidate ties, gated `llm_resolve_ambiguous` (default off): `resolve_target()` in `core/detection/llm_disambiguator.py`.
- eCTD leaf resolution (built, not wired live): `core/graph/leaf_resolver.py`.

## Gotchas
- `resolve_v1` only fires on same-format sibling ambiguity + Ollama up + a confident pick; the deterministic format/folder rule already resolves most cases.

## Related
[[Detection cascade]] · [[Injection layer]] · [[eCTD backbone and graph]] · [[_Home]]
