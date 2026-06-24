# Validation layer

Layer 5 — check links resolve, point to the right target, and flag anomalies.

## How it works
- Existence checks: `core/validation/existence_checker.py`; target-correctness (token-Jaccard / sentence-transformers): `core/validation/target_validator.py`.
- Anomaly detection — blue-text-without-link, orphans, circular refs, deprecated IDs: `core/validation/anomaly_detector.py`.
- Viewer-compatibility list: `core/validation/viewer_compat.py`; HA region rules: `core/validation/ha_rule_engine.py`; cross-module integrity: `core/validation/cross_module_integrity.py`.
- `node_validate` (`orchestration/nodes.py`) writes each link's authoritative `link_kind` (`external_url` / `cross_doc` / `internal_bookmark` / `cross_module`).

## Gotchas
- Target-correctness is heuristic (regex/embeddings), not proof — pair with a human sign-off ([[Reports and review screens]]).

## Related
[[Injection layer]] · [[Reporting and scoring]] · [[Reports and review screens]] · [[_Home]]
