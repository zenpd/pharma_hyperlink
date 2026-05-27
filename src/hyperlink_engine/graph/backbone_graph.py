"""Layer 4.5 — in-memory eCTD backbone graph (NetworkX).

Phase 2 W5.2: A directed graph view over a ``BackboneSnapshot``.

Two node classes:
  * **leaf** — one node per ``BackboneLeaf``; the leaf_id is the node key
  * **module** — synthetic hierarchical nodes (``m2``, ``m2.5``, ``m2.5.3``)
    inserted as ancestors so callers can answer "which leaves live under
    module 5.3?" without re-scanning the leaf list

Three edge classes:
  * ``structural`` — module → child module/leaf (the CTD hierarchy)
  * ``ref`` — leaf → leaf, derived from explicit ``ExtractedReference`` /
    ``ResolvedXref`` records (added post-construction via ``add_reference``)
  * ``sequence`` — leaf → leaf, linking a replaced/appended leaf back to
    its predecessor in the prior sequence (added via ``link_sequence``)

The graph is the engine's source of truth for:
  * cross-module link resolution (W6.x)
  * cycle / orphan detection (W8.1)
  * "find latest valid leaf" sequence walks (W6.2)
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import BackboneLeaf, BackboneSnapshot

if TYPE_CHECKING:
    from hyperlink_engine.detection.entity_extractor import ExtractedReference

_log = get_logger("graph.backbone")


NODE_KIND_LEAF = "leaf"
NODE_KIND_MODULE = "module"

EDGE_KIND_STRUCTURAL = "structural"
EDGE_KIND_REF = "ref"
EDGE_KIND_SEQUENCE = "sequence"


@dataclass(frozen=True)
class GraphStats:
    """Quick-look counts for logs and dashboards."""

    leaf_count: int
    module_count: int
    structural_edges: int
    ref_edges: int
    sequence_edges: int

    @property
    def total_nodes(self) -> int:
        return self.leaf_count + self.module_count

    @property
    def total_edges(self) -> int:
        return self.structural_edges + self.ref_edges + self.sequence_edges


class BackboneGraph:
    """Directed multi-graph over a ``BackboneSnapshot``.

    Construction is from a snapshot only; callers add ``ref`` and
    ``sequence`` edges incrementally as the pipeline produces them.
    """

    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()

    # ── Constructors ────────────────────────────────────────────────────

    @classmethod
    def from_snapshot(cls, snapshot: BackboneSnapshot) -> "BackboneGraph":
        graph = cls()
        for leaf in snapshot.leaves:
            graph._add_leaf(leaf)
        _log.info(
            "backbone_graph_built",
            leaves=snapshot.leaf_count,
            nodes=graph._g.number_of_nodes(),
            edges=graph._g.number_of_edges(),
        )
        return graph

    # ── Construction helpers ────────────────────────────────────────────

    def _add_leaf(self, leaf: BackboneLeaf) -> None:
        node = self.leaf_node(leaf.leaf_id)
        self._g.add_node(
            node,
            kind=NODE_KIND_LEAF,
            leaf_id=leaf.leaf_id,
            module=leaf.module,
            title=leaf.title,
            relative_path=str(leaf.relative_path),
            operation=leaf.operation.value,
        )
        # Wire up the hierarchical module chain: m2 → m2.5 → m2.5.3 → leaf
        ancestor_chain = _module_ancestor_chain(leaf.module)
        prev: str | None = None
        for module_label in ancestor_chain:
            module_node = self.module_node(module_label)
            if module_node not in self._g:
                self._g.add_node(module_node, kind=NODE_KIND_MODULE, module=module_label)
            if prev is not None and not self._g.has_edge(prev, module_node, key=EDGE_KIND_STRUCTURAL):
                self._g.add_edge(prev, module_node, key=EDGE_KIND_STRUCTURAL, kind=EDGE_KIND_STRUCTURAL)
            prev = module_node
        if prev is not None and not self._g.has_edge(prev, node, key=EDGE_KIND_STRUCTURAL):
            self._g.add_edge(prev, node, key=EDGE_KIND_STRUCTURAL, kind=EDGE_KIND_STRUCTURAL)

    def add_reference(
        self,
        source_leaf_id: str,
        target_leaf_id: str,
        *,
        confidence: float = 1.0,
        reference: "ExtractedReference | None" = None,
    ) -> None:
        """Record an explicit leaf-to-leaf reference (ref edge)."""
        src = self.leaf_node(source_leaf_id)
        dst = self.leaf_node(target_leaf_id)
        if src not in self._g or dst not in self._g:
            raise KeyError(f"unknown leaf in reference: {source_leaf_id} → {target_leaf_id}")
        meta: dict[str, object] = {
            "kind": EDGE_KIND_REF,
            "confidence": float(confidence),
        }
        if reference is not None:
            meta["pattern_id"] = reference.pattern_id
            meta["text"] = reference.text
        self._g.add_edge(src, dst, key=f"ref::{source_leaf_id}->{target_leaf_id}", **meta)

    def link_sequence(self, predecessor_leaf_id: str, successor_leaf_id: str) -> None:
        """Mark ``successor`` as the next-sequence version of ``predecessor``."""
        pred = self.leaf_node(predecessor_leaf_id)
        succ = self.leaf_node(successor_leaf_id)
        if pred not in self._g or succ not in self._g:
            raise KeyError(
                f"sequence link references unknown leaf: {predecessor_leaf_id} → {successor_leaf_id}"
            )
        self._g.add_edge(
            pred,
            succ,
            key=f"seq::{predecessor_leaf_id}->{successor_leaf_id}",
            kind=EDGE_KIND_SEQUENCE,
        )

    # ── Query API ───────────────────────────────────────────────────────

    @staticmethod
    def leaf_node(leaf_id: str) -> str:
        return f"leaf::{leaf_id}"

    @staticmethod
    def module_node(module_label: str) -> str:
        return f"mod::{module_label}"

    def has_leaf(self, leaf_id: str) -> bool:
        return self.leaf_node(leaf_id) in self._g

    def has_module(self, module_label: str) -> bool:
        return self.module_node(module_label) in self._g

    def leaves_under(self, module_label: str) -> list[str]:
        """All leaf_ids structurally beneath the given module label."""
        node = self.module_node(module_label)
        if node not in self._g:
            return []
        out: list[str] = []
        for descendant in nx.descendants(self._g, node):
            data = self._g.nodes[descendant]
            if data.get("kind") == NODE_KIND_LEAF:
                out.append(data["leaf_id"])
        return sorted(out)

    def leaves_referencing(self, target_leaf_id: str) -> list[str]:
        """Leaf_ids that have a ``ref`` edge pointing AT the given target."""
        target = self.leaf_node(target_leaf_id)
        if target not in self._g:
            return []
        out: list[str] = []
        for src, _, edge_data in self._g.in_edges(target, data=True):
            if edge_data.get("kind") != EDGE_KIND_REF:
                continue
            src_data = self._g.nodes[src]
            if src_data.get("kind") == NODE_KIND_LEAF:
                out.append(src_data["leaf_id"])
        return sorted(out)

    def references_from(self, source_leaf_id: str) -> list[str]:
        """Leaf_ids the given leaf points AT via ``ref`` edges."""
        src = self.leaf_node(source_leaf_id)
        if src not in self._g:
            return []
        out: list[str] = []
        for _, dst, edge_data in self._g.out_edges(src, data=True):
            if edge_data.get("kind") != EDGE_KIND_REF:
                continue
            dst_data = self._g.nodes[dst]
            if dst_data.get("kind") == NODE_KIND_LEAF:
                out.append(dst_data["leaf_id"])
        return sorted(out)

    def has_cycle(self) -> bool:
        """Detect a cycle anywhere in the ref edges (ignores structural edges)."""
        ref_view = self._ref_only_subgraph()
        try:
            nx.find_cycle(ref_view, orientation="original")
            return True
        except nx.NetworkXNoCycle:
            return False

    def find_cycle(self) -> list[tuple[str, str]] | None:
        """Return one ref-edge cycle if present, else None.

        Result is a list of (source_leaf_id, target_leaf_id) pairs in
        traversal order — useful for the anomaly reporter.
        """
        ref_view = self._ref_only_subgraph()
        try:
            edges = nx.find_cycle(ref_view, orientation="original")
        except nx.NetworkXNoCycle:
            return None
        out: list[tuple[str, str]] = []
        for edge in edges:
            src, dst = edge[0], edge[1]
            out.append((self._leaf_id_of(src), self._leaf_id_of(dst)))
        return out

    def orphans(self) -> list[str]:
        """Leaf_ids that are neither referenced nor reference anything else."""
        ref_view = self._ref_only_subgraph()
        out: list[str] = []
        for node, data in self._g.nodes(data=True):
            if data.get("kind") != NODE_KIND_LEAF:
                continue
            if ref_view.degree(node) == 0:
                out.append(data["leaf_id"])
        return sorted(out)

    def latest_in_sequence(self, leaf_id: str) -> str:
        """Walk ``sequence`` edges forward to find the latest version of a leaf."""
        current = self.leaf_node(leaf_id)
        if current not in self._g:
            raise KeyError(leaf_id)
        visited: set[str] = {current}
        while True:
            next_node: str | None = None
            for _, dst, data in self._g.out_edges(current, data=True):
                if data.get("kind") == EDGE_KIND_SEQUENCE and dst not in visited:
                    next_node = dst
                    break
            if next_node is None:
                break
            current = next_node
            visited.add(current)
        return self._leaf_id_of(current)

    def shortest_ref_path(self, source_leaf_id: str, target_leaf_id: str) -> list[str] | None:
        """Shortest path (in leaf_ids) following only ``ref`` edges."""
        src = self.leaf_node(source_leaf_id)
        dst = self.leaf_node(target_leaf_id)
        ref_view = self._ref_only_subgraph()
        if src not in ref_view or dst not in ref_view:
            return None
        try:
            nodes = nx.shortest_path(ref_view, source=src, target=dst)
        except nx.NetworkXNoPath:
            return None
        return [self._leaf_id_of(node) for node in nodes]

    def iter_leaves(self) -> Iterator[str]:
        for node, data in self._g.nodes(data=True):
            if data.get("kind") == NODE_KIND_LEAF:
                yield data["leaf_id"]

    def stats(self) -> GraphStats:
        leaves = 0
        modules = 0
        structural = 0
        refs = 0
        seq = 0
        for _, data in self._g.nodes(data=True):
            if data.get("kind") == NODE_KIND_LEAF:
                leaves += 1
            elif data.get("kind") == NODE_KIND_MODULE:
                modules += 1
        for _, _, data in self._g.edges(data=True):
            kind = data.get("kind")
            if kind == EDGE_KIND_STRUCTURAL:
                structural += 1
            elif kind == EDGE_KIND_REF:
                refs += 1
            elif kind == EDGE_KIND_SEQUENCE:
                seq += 1
        return GraphStats(
            leaf_count=leaves,
            module_count=modules,
            structural_edges=structural,
            ref_edges=refs,
            sequence_edges=seq,
        )

    @property
    def raw(self) -> nx.MultiDiGraph:
        """Escape-hatch for adapters (e.g. neo4j) that need the underlying graph."""
        return self._g

    # ── Internals ───────────────────────────────────────────────────────

    def _ref_only_subgraph(self) -> nx.MultiDiGraph:
        sub = nx.MultiDiGraph()
        for node, data in self._g.nodes(data=True):
            if data.get("kind") == NODE_KIND_LEAF:
                sub.add_node(node, **data)
        for src, dst, key, data in self._g.edges(keys=True, data=True):
            if data.get("kind") == EDGE_KIND_REF:
                sub.add_edge(src, dst, key=key, **data)
        return sub

    def _leaf_id_of(self, node: str) -> str:
        data = self._g.nodes[node]
        if data.get("kind") != NODE_KIND_LEAF:
            raise ValueError(f"node {node!r} is not a leaf")
        return data["leaf_id"]


# ─────────────────────────────────────────────────────────────────────────
# Module-ancestor helpers
# ─────────────────────────────────────────────────────────────────────────


def _module_ancestor_chain(module: str) -> Iterable[str]:
    """Yield ['m2', 'm2.5', 'm2.5.3'] for input 'm2.5.3'.

    Returns an empty iterable for ``unknown`` / malformed labels so the
    leaf still gets added (without structural ancestry).
    """
    if not module or module == "unknown":
        return []
    if not module.lower().startswith("m"):
        return []
    parts = module.split(".")
    head = parts[0]  # 'm2'
    if not head or len(head) < 2 or not head[1:].isdigit():
        return []
    chain: list[str] = [head]
    for sub in parts[1:]:
        chain.append(f"{chain[-1]}.{sub}")
    return chain
