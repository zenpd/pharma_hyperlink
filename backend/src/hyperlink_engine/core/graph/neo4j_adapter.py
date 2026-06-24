"""Phase 2 W5.2b — Neo4j persistence for the eCTD backbone graph.

The ``neo4j`` driver is an *optional* dep (declared under the ``graph``
poetry extras group) — importing this module without it installed must
raise a clear error, not crash at import time. We therefore defer the
import until the adapter is actually instantiated.

For Phase 2 we keep the schema minimal:

  Nodes
    (:Leaf {leaf_id, module, title, relative_path, operation})
    (:Module {label})

  Relationships
    (:Module)-[:CONTAINS]->(:Module)        # hierarchy
    (:Module)-[:CONTAINS]->(:Leaf)          # leaf membership
    (:Leaf)  -[:REFERENCES {confidence}]->(:Leaf)
    (:Leaf)  -[:NEXT_SEQUENCE]->(:Leaf)

Connection settings come from environment variables (Pydantic settings):
  HYPERLINK_NEO4J_URI       (default: bolt://localhost:7687)
  HYPERLINK_NEO4J_USER      (default: neo4j)
  HYPERLINK_NEO4J_PASSWORD  (required to persist)
  HYPERLINK_NEO4J_DATABASE  (default: neo4j)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.graph.backbone_graph import (
    EDGE_KIND_REF,
    EDGE_KIND_SEQUENCE,
    EDGE_KIND_STRUCTURAL,
    NODE_KIND_LEAF,
    NODE_KIND_MODULE,
    BackboneGraph,
)

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from neo4j import Driver, Session

_log = get_logger("graph.neo4j")


class Neo4jUnavailable(RuntimeError):
    """Raised when the optional neo4j driver isn't installed or isn't reachable."""


def _import_driver() -> Any:
    try:
        import neo4j  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised via test
        raise Neo4jUnavailable(
            "neo4j driver not installed — install with `poetry install --extras graph`"
        ) from exc
    return neo4j


class Neo4jBackboneStore:
    """Persist (and query) a ``BackboneGraph`` against a Neo4j instance.

    Usage::

        store = Neo4jBackboneStore(uri="bolt://localhost:7687",
                                   user="neo4j", password="secret")
        try:
            store.persist(graph)
        finally:
            store.close()
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        database: str = "neo4j",
        driver: "Driver | None" = None,
    ) -> None:
        self._uri = uri
        self._user = user
        self._database = database
        if driver is not None:
            self._driver = driver
        else:
            neo4j_mod = _import_driver()
            self._driver = neo4j_mod.GraphDatabase.driver(uri, auth=(user, password))

    # ── Lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jBackboneStore":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # ── Public API ──────────────────────────────────────────────────────

    def clear(self) -> None:
        """Wipe every node and relationship from the configured database."""
        with self._session() as session:
            session.run("MATCH (n) DETACH DELETE n")

    def persist(self, graph: BackboneGraph) -> dict[str, int]:
        """Write the entire graph to Neo4j idempotently (MERGE semantics).

        Returns a counts dict: ``{"leaves", "modules", "ref_edges", "seq_edges", "struct_edges"}``.
        """
        counts = {"leaves": 0, "modules": 0, "ref_edges": 0, "seq_edges": 0, "struct_edges": 0}
        with self._session() as session:
            for node, data in graph.raw.nodes(data=True):
                kind = data.get("kind")
                if kind == NODE_KIND_LEAF:
                    session.run(
                        """
                        MERGE (l:Leaf {leaf_id: $leaf_id})
                        SET l.module = $module,
                            l.title = $title,
                            l.relative_path = $relative_path,
                            l.operation = $operation
                        """,
                        leaf_id=data["leaf_id"],
                        module=data.get("module"),
                        title=data.get("title"),
                        relative_path=data.get("relative_path"),
                        operation=data.get("operation"),
                    )
                    counts["leaves"] += 1
                elif kind == NODE_KIND_MODULE:
                    session.run(
                        "MERGE (m:Module {label: $label})",
                        label=data["module"],
                    )
                    counts["modules"] += 1
            for src, dst, edge_data in graph.raw.edges(data=True):
                kind = edge_data.get("kind")
                if kind == EDGE_KIND_STRUCTURAL:
                    session.run(
                        self._structural_cypher(graph, src, dst),
                        src_key=_key_for(graph, src),
                        dst_key=_key_for(graph, dst),
                    )
                    counts["struct_edges"] += 1
                elif kind == EDGE_KIND_REF:
                    session.run(
                        """
                        MATCH (s:Leaf {leaf_id: $src}),
                              (d:Leaf {leaf_id: $dst})
                        MERGE (s)-[r:REFERENCES]->(d)
                        SET r.confidence = $confidence
                        """,
                        src=graph.raw.nodes[src]["leaf_id"],
                        dst=graph.raw.nodes[dst]["leaf_id"],
                        confidence=edge_data.get("confidence", 1.0),
                    )
                    counts["ref_edges"] += 1
                elif kind == EDGE_KIND_SEQUENCE:
                    session.run(
                        """
                        MATCH (s:Leaf {leaf_id: $src}),
                              (d:Leaf {leaf_id: $dst})
                        MERGE (s)-[:NEXT_SEQUENCE]->(d)
                        """,
                        src=graph.raw.nodes[src]["leaf_id"],
                        dst=graph.raw.nodes[dst]["leaf_id"],
                    )
                    counts["seq_edges"] += 1
        _log.info("neo4j_persist_complete", **counts)
        return counts

    def leaves_referencing(self, target_leaf_id: str) -> list[str]:
        with self._session() as session:
            result = session.run(
                "MATCH (s:Leaf)-[:REFERENCES]->(t:Leaf {leaf_id: $id}) RETURN s.leaf_id AS id",
                id=target_leaf_id,
            )
            return sorted(record["id"] for record in result)

    def leaves_under(self, module_label: str) -> list[str]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (m:Module {label: $label})
                MATCH (m)-[:CONTAINS*]->(l:Leaf)
                RETURN DISTINCT l.leaf_id AS id
                """,
                label=module_label,
            )
            return sorted(record["id"] for record in result)

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Escape-hatch for arbitrary Cypher — returns each record as a dict."""
        with self._session() as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    # ── Internals ───────────────────────────────────────────────────────

    def _session(self) -> "Session":
        return self._driver.session(database=self._database)

    @staticmethod
    def _structural_cypher(graph: BackboneGraph, src: str, dst: str) -> str:
        """Pick the correct Cypher MERGE based on src/dst node labels."""
        src_kind = graph.raw.nodes[src].get("kind")
        dst_kind = graph.raw.nodes[dst].get("kind")
        src_label = "Module" if src_kind == NODE_KIND_MODULE else "Leaf"
        dst_label = "Module" if dst_kind == NODE_KIND_MODULE else "Leaf"
        src_field = "label" if src_label == "Module" else "leaf_id"
        dst_field = "label" if dst_label == "Module" else "leaf_id"
        return (
            f"MATCH (s:{src_label} {{{src_field}: $src_key}}), "
            f"(d:{dst_label} {{{dst_field}: $dst_key}}) "
            f"MERGE (s)-[:CONTAINS]->(d)"
        )


def _key_for(graph: BackboneGraph, node: str) -> str:
    data = graph.raw.nodes[node]
    if data.get("kind") == NODE_KIND_LEAF:
        return data["leaf_id"]
    return data["module"]
