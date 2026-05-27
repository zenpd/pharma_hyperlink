"""Unit tests for graph/backbone_graph.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from hyperlink_engine.graph.backbone_graph import (
    EDGE_KIND_REF,
    EDGE_KIND_SEQUENCE,
    EDGE_KIND_STRUCTURAL,
    NODE_KIND_LEAF,
    NODE_KIND_MODULE,
    BackboneGraph,
    _module_ancestor_chain,
)
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    LeafOperation,
)


def _provenance() -> DocumentProvenance:
    return DocumentProvenance(
        source_path=Path("index.xml"),
        sha256="0" * 64,
        file_size_bytes=10,
    )


def _snapshot(*leaves: BackboneLeaf) -> BackboneSnapshot:
    return BackboneSnapshot(
        provenance=_provenance(),
        schema_version="v3.2",
        region="us",
        sequence_number="0001",
        leaves=list(leaves),
    )


def _leaf(leaf_id: str, module: str, title: str | None = None) -> BackboneLeaf:
    return BackboneLeaf(
        leaf_id=leaf_id,
        relative_path=Path(f"{module.replace('.', '/')}/{leaf_id}.docx"),
        module=module,
        operation=LeafOperation.NEW,
        title=title,
    )


# ── Module-ancestor chain helper ────────────────────────────────────────


def test_module_chain_simple() -> None:
    assert list(_module_ancestor_chain("m2.5.3")) == ["m2", "m2.5", "m2.5.3"]


def test_module_chain_top_level() -> None:
    assert list(_module_ancestor_chain("m1")) == ["m1"]


def test_module_chain_unknown() -> None:
    assert list(_module_ancestor_chain("unknown")) == []
    assert list(_module_ancestor_chain("")) == []
    assert list(_module_ancestor_chain("garbage")) == []
    assert list(_module_ancestor_chain("mX")) == []


# ── Graph construction ─────────────────────────────────────────────────


def test_from_snapshot_creates_leaf_nodes() -> None:
    snap = _snapshot(_leaf("L1", "m2.5"), _leaf("L2", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    assert graph.has_leaf("L1")
    assert graph.has_leaf("L2")
    assert graph.has_module("m2")
    assert graph.has_module("m2.5")
    assert graph.has_module("m5")
    assert graph.has_module("m5.3")
    assert graph.has_module("m5.3.1")


def test_module_hierarchy_edges_are_structural() -> None:
    snap = _snapshot(_leaf("L1", "m2.5.3"))
    graph = BackboneGraph.from_snapshot(snap)
    g = graph.raw
    edge_kinds = [data.get("kind") for _, _, data in g.edges(data=True)]
    assert all(k == EDGE_KIND_STRUCTURAL for k in edge_kinds)
    # Hierarchical chain length: m2 → m2.5 → m2.5.3 → leaf = 3 edges
    assert sum(1 for k in edge_kinds if k == EDGE_KIND_STRUCTURAL) == 3


def test_leaves_under_returns_descendants() -> None:
    snap = _snapshot(
        _leaf("L1", "m2.5"),
        _leaf("L2", "m2.5.3"),
        _leaf("L3", "m5.3.1"),
    )
    graph = BackboneGraph.from_snapshot(snap)
    assert sorted(graph.leaves_under("m2")) == ["L1", "L2"]
    assert graph.leaves_under("m5.3") == ["L3"]
    assert graph.leaves_under("m9") == []


def test_unknown_module_leaf_still_added_without_hierarchy() -> None:
    leaf = BackboneLeaf(
        leaf_id="O1",
        relative_path=Path("orphan.docx"),
        module="unknown",
    )
    graph = BackboneGraph.from_snapshot(_snapshot(leaf))
    assert graph.has_leaf("O1")
    assert not graph.has_module("unknown")


# ── Reference edges ─────────────────────────────────────────────────────


def test_add_reference_creates_ref_edge() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    graph.add_reference("A", "B", confidence=0.9)
    assert graph.references_from("A") == ["B"]
    assert graph.leaves_referencing("B") == ["A"]


def test_add_reference_unknown_leaf_raises() -> None:
    snap = _snapshot(_leaf("A", "m2.5"))
    graph = BackboneGraph.from_snapshot(snap)
    with pytest.raises(KeyError):
        graph.add_reference("A", "Z")


def test_references_from_unknown_leaf_returns_empty() -> None:
    snap = _snapshot(_leaf("A", "m2.5"))
    graph = BackboneGraph.from_snapshot(snap)
    assert graph.references_from("Z") == []
    assert graph.leaves_referencing("Z") == []


# ── Cycle detection ─────────────────────────────────────────────────────


def test_has_cycle_true_when_ref_cycle_present() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    graph.add_reference("A", "B")
    graph.add_reference("B", "A")
    assert graph.has_cycle() is True
    cycle = graph.find_cycle()
    assert cycle is not None and len(cycle) == 2


def test_has_cycle_false_when_only_structural() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m2.5.3"))
    graph = BackboneGraph.from_snapshot(snap)
    assert graph.has_cycle() is False
    assert graph.find_cycle() is None


# ── Sequence edges ──────────────────────────────────────────────────────


def test_latest_in_sequence_walks_forward() -> None:
    snap = _snapshot(
        _leaf("L-v1", "m2.5"),
        _leaf("L-v2", "m2.5"),
        _leaf("L-v3", "m2.5"),
    )
    graph = BackboneGraph.from_snapshot(snap)
    graph.link_sequence("L-v1", "L-v2")
    graph.link_sequence("L-v2", "L-v3")
    assert graph.latest_in_sequence("L-v1") == "L-v3"
    # Latest of a tip is itself.
    assert graph.latest_in_sequence("L-v3") == "L-v3"


def test_latest_in_sequence_unknown_raises() -> None:
    snap = _snapshot(_leaf("A", "m2.5"))
    graph = BackboneGraph.from_snapshot(snap)
    with pytest.raises(KeyError):
        graph.latest_in_sequence("MISSING")


def test_link_sequence_unknown_raises() -> None:
    snap = _snapshot(_leaf("A", "m2.5"))
    graph = BackboneGraph.from_snapshot(snap)
    with pytest.raises(KeyError):
        graph.link_sequence("A", "Z")


# ── Shortest path / orphans ─────────────────────────────────────────────


def test_shortest_ref_path_returns_intermediate_nodes() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m2.7"), _leaf("C", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    graph.add_reference("A", "B")
    graph.add_reference("B", "C")
    path = graph.shortest_ref_path("A", "C")
    assert path == ["A", "B", "C"]


def test_shortest_ref_path_none_when_disconnected() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    assert graph.shortest_ref_path("A", "B") is None


def test_orphans_lists_leaves_with_no_refs() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"), _leaf("C", "m2.7"))
    graph = BackboneGraph.from_snapshot(snap)
    graph.add_reference("A", "B")
    assert graph.orphans() == ["C"]


# ── Stats ───────────────────────────────────────────────────────────────


def test_stats_counts_each_edge_kind() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"), _leaf("C", "m2.5"))
    graph = BackboneGraph.from_snapshot(snap)
    graph.add_reference("A", "B")
    graph.link_sequence("A", "C")
    stats = graph.stats()
    assert stats.leaf_count == 3
    assert stats.module_count > 0
    assert stats.ref_edges == 1
    assert stats.sequence_edges == 1
    assert stats.structural_edges >= 3
    assert stats.total_nodes == stats.leaf_count + stats.module_count
    assert stats.total_edges == stats.structural_edges + stats.ref_edges + stats.sequence_edges


def test_iter_leaves_yields_all_leaf_ids() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    assert sorted(graph.iter_leaves()) == ["A", "B"]


def test_node_kind_metadata_recorded() -> None:
    snap = _snapshot(_leaf("A", "m2.5"))
    graph = BackboneGraph.from_snapshot(snap)
    leaf_node = graph.leaf_node("A")
    module_node = graph.module_node("m2.5")
    assert graph.raw.nodes[leaf_node]["kind"] == NODE_KIND_LEAF
    assert graph.raw.nodes[module_node]["kind"] == NODE_KIND_MODULE
    # Edge between the deepest module and the leaf has kind == structural.
    edge_data = list(graph.raw.get_edge_data(module_node, leaf_node).values())[0]
    assert edge_data["kind"] == EDGE_KIND_STRUCTURAL


def test_ref_edge_carries_confidence() -> None:
    snap = _snapshot(_leaf("A", "m2.5"), _leaf("B", "m5.3.1"))
    graph = BackboneGraph.from_snapshot(snap)
    graph.add_reference("A", "B", confidence=0.72)
    edges = graph.raw.get_edge_data(graph.leaf_node("A"), graph.leaf_node("B"))
    assert any(e["kind"] == EDGE_KIND_REF and e["confidence"] == 0.72 for e in edges.values())
