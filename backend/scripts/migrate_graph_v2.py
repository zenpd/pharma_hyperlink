"""Backfill the v2 enterprise graph layer onto runs already stored in Neo4j.

The v2 schema (Sponsor / Study / DocumentVersion / DetectionMethod / RefType +
clear provenance edges) is written automatically for every *new* run, but runs
persisted before the upgrade only have the core nodes. This one-shot script
upgrades those existing runs in place.

It is **idempotent and additive**: it only MERGEs the new enterprise nodes/edges
onto the existing core nodes (reading each node's own stored properties), and it
never touches the counted ``CROSS_LINKS`` edge — so running it repeatedly is
safe and can't inflate any counts.

Run::

    poetry run python -m scripts.migrate_graph_v2
    # or:  python scripts/migrate_graph_v2.py

Requires Neo4j to be running and reachable (HYPERLINK_NEO4J_URI / USER /
PASSWORD) with HYPERLINK_GRAPH_BACKEND=neo4j.
"""

from __future__ import annotations

import sys


def main() -> int:
    from hyperlink_engine.config.settings import get_settings
    from hyperlink_engine.core.graph.dossier_schema import get_dossier_store

    settings = get_settings()
    if getattr(settings, "graph_backend", "networkx") != "neo4j":
        print("HYPERLINK_GRAPH_BACKEND is not 'neo4j' — nothing to migrate.")
        return 1

    store = get_dossier_store()
    if store is None:
        print(
            "Could not connect to Neo4j. Check that the container is running and "
            "HYPERLINK_NEO4J_URI / USER / PASSWORD are correct."
        )
        return 1

    print("Migrating existing runs to the v2 enterprise schema...")
    counts = store.migrate_existing_to_v2()
    print("Done. Backfilled enterprise layer over:")
    print(f"  dossiers : {counts.get('dossiers', 0)}")
    print(f"  documents: {counts.get('documents', 0)}")
    print(f"  references: {counts.get('references', 0)}")
    print(
        "\nVerify in Neo4j Browser, e.g.:\n"
        "  MATCH (x:Reference)-[:DETECTED_BY]->(m:DetectionMethod) "
        "RETURN m.method, count(x) ORDER BY count(x) DESC;"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
