# eCTD backbone and graph

Parse the eCTD `index.xml` backbone and persist the dossier as a graph.

## How it works
- Backbone loader (detects v3.2 / v4.0, merges regional XML, verifies MD5, diffs sequences): `core/ingestion/ectd_loader.py` → `BackboneSnapshot`.
- Leaf-to-leaf resolution + graph + lifecycle: `core/graph/leaf_resolver.py`, `core/graph/backbone_graph.py`, `core/graph/sequence_history.py`.
- Neo4j persistence + hydrate-on-startup so runs survive a restart: `core/graph/neo4j_adapter.py`, `core/graph/dossier_schema.py`.

## Gotchas
- This subsystem is BUILT + unit-tested but NOT wired into the live pipeline and has never run on a real `index.xml`. Neo4j is optional — without it the in-memory run store stays the source of truth.

## Related
[[Ingestion layer]] · [[Resolution and anchoring]] · [[Reporting and scoring]] · [[_Home]]
