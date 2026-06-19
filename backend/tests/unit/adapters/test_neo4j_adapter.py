"""Unit tests for graph/neo4j_adapter.py.

We avoid requiring an actual Neo4j instance (or even the ``neo4j`` driver
package) by injecting a fake driver that captures the Cypher statements
executed. The test then asserts the *shape* of what would be sent — which
is the actual contract the adapter promises to its callers.

A separate marked-integration test could later run against a live Neo4j;
that's out of scope for the Phase 2 unit gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from hyperlink_engine.core.graph.backbone_graph import BackboneGraph
from hyperlink_engine.core.graph.neo4j_adapter import (
    Neo4jBackboneStore,
    Neo4jUnavailable,
    _import_driver,
)
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    LeafOperation,
)

# ── Fake neo4j driver scaffolding ───────────────────────────────────────


class _FakeRecord:
    def __init__(self, mapping: dict[str, Any]) -> None:
        self._mapping = mapping

    def __getitem__(self, key: str) -> Any:
        return self._mapping[key]

    def data(self) -> dict[str, Any]:
        return dict(self._mapping)


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records = [_FakeRecord(r) for r in (records or [])]

    def __iter__(self):
        return iter(self._records)


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._scripted: dict[str, list[dict[str, Any]]] = {}

    def script(self, fragment: str, records: list[dict[str, Any]]) -> None:
        self._scripted[fragment] = records

    def run(self, cypher: str, **params: Any) -> _FakeResult:
        self.calls.append((cypher, params))
        # Find any scripted records for this query.
        for fragment, records in self._scripted.items():
            if fragment in cypher:
                return _FakeResult(records)
        return _FakeResult()

    def close(self) -> None:
        pass

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


class _FakeDriver:
    def __init__(self) -> None:
        self.session_instance = _FakeSession()

    def session(self, database: str = "neo4j") -> _FakeSession:
        return self.session_instance

    def close(self) -> None:
        pass


# ── Fixtures ────────────────────────────────────────────────────────────


def _provenance() -> DocumentProvenance:
    return DocumentProvenance(
        source_path=Path("index.xml"), sha256="0" * 64, file_size_bytes=10
    )


def _snapshot() -> BackboneSnapshot:
    return BackboneSnapshot(
        provenance=_provenance(),
        schema_version="v3.2",
        region="us",
        sequence_number="0001",
        leaves=[
            BackboneLeaf(
                leaf_id="L1",
                relative_path=Path("m2/2-5-clin-overview/x.docx"),
                module="m2.5",
                operation=LeafOperation.NEW,
                title="Overview",
            ),
            BackboneLeaf(
                leaf_id="L2",
                relative_path=Path("m5/5-3-1-bio-stud-rep/y.docx"),
                module="m5.3.1",
                operation=LeafOperation.NEW,
                title="CSR",
            ),
        ],
    )


@pytest.fixture
def adapter() -> Neo4jBackboneStore:
    driver = _FakeDriver()
    return Neo4jBackboneStore(
        uri="bolt://test", user="u", password="p", driver=driver
    )


# ── Driver injection ────────────────────────────────────────────────────


def test_adapter_uses_injected_driver(adapter: Neo4jBackboneStore) -> None:
    # If construction worked without the real `neo4j` package being installed,
    # the injected driver path is what the adapter is using.
    assert isinstance(adapter._driver, _FakeDriver)  # type: ignore[attr-defined]


def test_import_driver_raises_neo4j_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """When neo4j isn't importable, _import_driver must wrap the ImportError."""
    import builtins

    original_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "neo4j":
            raise ImportError("no neo4j installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(Neo4jUnavailable):
        _import_driver()


# ── persist() shape ────────────────────────────────────────────────────


def test_persist_writes_one_merge_per_leaf(adapter: Neo4jBackboneStore) -> None:
    graph = BackboneGraph.from_snapshot(_snapshot())
    counts = adapter.persist(graph)
    assert counts["leaves"] == 2
    assert counts["modules"] >= 2
    # ref/seq counts should be zero since we didn't add any.
    assert counts["ref_edges"] == 0
    assert counts["seq_edges"] == 0
    assert counts["struct_edges"] >= 2


def test_persist_writes_ref_and_seq_edges(adapter: Neo4jBackboneStore) -> None:
    graph = BackboneGraph.from_snapshot(_snapshot())
    graph.add_reference("L1", "L2", confidence=0.85)
    graph.link_sequence("L1", "L2")
    counts = adapter.persist(graph)
    assert counts["ref_edges"] == 1
    assert counts["seq_edges"] == 1
    # The fake session captured each cypher call; sanity-check by keyword.
    session = adapter._driver.session_instance  # type: ignore[attr-defined]
    cyphers = [c for c, _ in session.calls]
    assert any("REFERENCES" in c for c in cyphers)
    assert any("NEXT_SEQUENCE" in c for c in cyphers)
    assert any("Leaf" in c for c in cyphers)
    assert any("Module" in c for c in cyphers)


def test_persist_passes_confidence_param(adapter: Neo4jBackboneStore) -> None:
    graph = BackboneGraph.from_snapshot(_snapshot())
    graph.add_reference("L1", "L2", confidence=0.42)
    adapter.persist(graph)
    session = adapter._driver.session_instance  # type: ignore[attr-defined]
    ref_calls = [params for cypher, params in session.calls if "REFERENCES" in cypher]
    assert ref_calls
    assert ref_calls[0]["confidence"] == 0.42


# ── clear() / leaves_under / leaves_referencing ─────────────────────────


def test_clear_issues_detach_delete(adapter: Neo4jBackboneStore) -> None:
    adapter.clear()
    session = adapter._driver.session_instance  # type: ignore[attr-defined]
    cyphers = [c for c, _ in session.calls]
    assert any("DETACH DELETE" in c for c in cyphers)


def test_leaves_under_calls_module_traversal(adapter: Neo4jBackboneStore) -> None:
    session = adapter._driver.session_instance  # type: ignore[attr-defined]
    session.script("CONTAINS*", [{"id": "L1"}, {"id": "L2"}])
    result = adapter.leaves_under("m2.5")
    assert result == ["L1", "L2"]


def test_leaves_referencing_returns_sorted_ids(adapter: Neo4jBackboneStore) -> None:
    session = adapter._driver.session_instance  # type: ignore[attr-defined]
    session.script("REFERENCES", [{"id": "Z"}, {"id": "A"}])
    result = adapter.leaves_referencing("X")
    assert result == ["A", "Z"]


def test_run_returns_record_dicts(adapter: Neo4jBackboneStore) -> None:
    session = adapter._driver.session_instance  # type: ignore[attr-defined]
    session.script("custom-marker", [{"count": 42}])
    rows = adapter.run("MATCH (n) /* custom-marker */ RETURN count(n) AS count")
    assert rows == [{"count": 42}]


# ── Context manager ─────────────────────────────────────────────────────


def test_context_manager_closes_driver() -> None:
    driver = _FakeDriver()
    driver.close = MagicMock()  # type: ignore[method-assign]
    with Neo4jBackboneStore(uri="bolt://x", user="u", password="p", driver=driver):
        pass
    driver.close.assert_called_once()
