"""Unit tests for graph/sequence_history.py (W6.2)."""

from __future__ import annotations

from pathlib import Path

from hyperlink_engine.core.graph.backbone_graph import BackboneGraph
from hyperlink_engine.core.graph.sequence_history import (
    SequenceTimeline,
    TimelineEntry,
    find_latest_leaf,
)
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    LeafOperation,
)


def _provenance() -> DocumentProvenance:
    return DocumentProvenance(
        source_path=Path("index.xml"), sha256="0" * 64, file_size_bytes=10
    )


def _snap(
    sequence: str,
    *leaves: BackboneLeaf,
) -> BackboneSnapshot:
    return BackboneSnapshot(
        provenance=_provenance(),
        schema_version="v3.2",
        region="us",
        sequence_number=sequence,
        leaves=list(leaves),
    )


def _leaf(
    leaf_id: str,
    relpath: str,
    *,
    op: LeafOperation = LeafOperation.NEW,
    checksum: str | None = None,
    title: str | None = None,
    module: str = "m5.3.1",
) -> BackboneLeaf:
    return BackboneLeaf(
        leaf_id=leaf_id,
        relative_path=Path(relpath),
        module=module,
        operation=op,
        checksum=checksum,
        title=title,
    )


# ── Basic construction & ordering ───────────────────────────────────────


def test_timeline_sorts_snapshots_ascending() -> None:
    s1 = _snap("0002", _leaf("L", "m5/x.docx"))
    s2 = _snap("0001", _leaf("L", "m5/x.docx"))
    tl = SequenceTimeline.from_snapshots([s1, s2])
    assert [s.sequence_number for s in tl.snapshots] == ["0001", "0002"]
    assert tl.snapshot_count == 2


def test_history_of_returns_chronological_entries() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx", checksum="aa"))
    s2 = _snap("0002", _leaf("L", "m5/x.docx", op=LeafOperation.REPLACE, checksum="bb"))
    tl = SequenceTimeline.from_snapshots([s1, s2])
    history = tl.history_of(Path("m5/x.docx"))
    assert len(history) == 2
    assert history[0].sequence_number == "0001"
    assert history[1].sequence_number == "0002"
    assert all(isinstance(e, TimelineEntry) for e in history)


# ── latest_by_path / latest_by_leaf_id ──────────────────────────────────


def test_latest_by_path_returns_newest_leaf() -> None:
    s1 = _snap("0001", _leaf("L-v1", "m5/x.docx", checksum="aa"))
    s2 = _snap("0002", _leaf("L-v2", "m5/x.docx", op=LeafOperation.REPLACE, checksum="bb"))
    tl = SequenceTimeline.from_snapshots([s1, s2])
    latest = tl.latest_by_path(Path("m5/x.docx"))
    assert latest is not None
    assert latest.leaf_id == "L-v2"


def test_latest_by_path_returns_none_on_terminal_delete() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx"))
    s2 = _snap("0002", _leaf("L", "m5/x.docx", op=LeafOperation.DELETE))
    tl = SequenceTimeline.from_snapshots([s1, s2])
    assert tl.latest_by_path(Path("m5/x.docx")) is None


def test_latest_by_path_normalizes_separators() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx"))
    tl = SequenceTimeline.from_snapshots([s1])
    # Using a Windows-style path should still find the leaf.
    found = tl.latest_by_path(Path("m5") / "x.docx")
    assert found is not None and found.leaf_id == "L"


def test_latest_by_leaf_id_returns_newest() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx", checksum="aa"))
    s2 = _snap(
        "0002", _leaf("L", "m5/x.docx", op=LeafOperation.REPLACE, checksum="bb")
    )
    tl = SequenceTimeline.from_snapshots([s1, s2])
    latest = tl.latest_by_leaf_id("L")
    assert latest is not None and latest.checksum == "bb"


def test_latest_by_leaf_id_unknown_returns_none() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx"))
    tl = SequenceTimeline.from_snapshots([s1])
    assert tl.latest_by_leaf_id("ZZZ") is None


# ── latest_for_study ────────────────────────────────────────────────────


def test_latest_for_study_picks_newest_match() -> None:
    s1 = _snap(
        "0001",
        _leaf(
            "L-v1",
            "m5/SP-2024-001-csr-draft.docx",
            title="CSR for Study SP-2024-001 (draft)",
            checksum="aa",
        ),
    )
    s2 = _snap(
        "0002",
        _leaf(
            "L-v2",
            "m5/SP-2024-001-csr-draft.docx",
            op=LeafOperation.REPLACE,
            title="CSR for Study SP-2024-001 (final)",
            checksum="bb",
        ),
    )
    tl = SequenceTimeline.from_snapshots([s1, s2])
    leaf = tl.latest_for_study("SP-2024-001")
    assert leaf is not None
    assert leaf.checksum == "bb"  # picks the v2 leaf


def test_latest_for_study_respects_module_filter() -> None:
    s1 = _snap(
        "0001",
        _leaf(
            "M2-overview",
            "m2/2-5/x.docx",
            module="m2.5",
            title="SP-2024-001 summary",
        ),
        _leaf(
            "M5-csr",
            "m5/5-3-1/y.docx",
            module="m5.3.1",
            title="CSR for SP-2024-001",
        ),
    )
    tl = SequenceTimeline.from_snapshots([s1])
    leaf = tl.latest_for_study("SP-2024-001", module="m5")
    assert leaf is not None
    assert leaf.leaf_id == "M5-csr"


def test_latest_for_study_returns_none_when_missing() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx", title="something else"))
    tl = SequenceTimeline.from_snapshots([s1])
    assert tl.latest_for_study("XYZ-999") is None


def test_latest_for_study_empty_input_returns_none() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx", title="SP-2024-001 CSR"))
    tl = SequenceTimeline.from_snapshots([s1])
    assert tl.latest_for_study("") is None
    assert tl.latest_for_study("   ") is None


def test_latest_for_study_skips_deleted_leaves() -> None:
    s1 = _snap(
        "0001",
        _leaf("L", "m5/x.docx", title="CSR SP-2024-001"),
    )
    s2 = _snap(
        "0002",
        _leaf("L", "m5/x.docx", op=LeafOperation.DELETE, title="CSR SP-2024-001"),
    )
    tl = SequenceTimeline.from_snapshots([s1, s2])
    # The latest version is a DELETE → no result.
    assert tl.latest_for_study("SP-2024-001") is None


# ── Graph wiring ────────────────────────────────────────────────────────


def test_wire_sequence_edges_links_consecutive_versions() -> None:
    """A graph built from the union snapshot gets NEXT_SEQUENCE edges."""
    s1 = _snap("0001", _leaf("L-v1", "m5/x.docx", checksum="aa"))
    s2 = _snap(
        "0002",
        _leaf("L-v2", "m5/x.docx", op=LeafOperation.REPLACE, checksum="bb"),
    )
    # Build the graph from a union of all leaves so both v1 and v2 are nodes.
    union = _snap("0002", *s1.leaves, *s2.leaves)
    graph = BackboneGraph.from_snapshot(union)
    tl = SequenceTimeline.from_snapshots([s1, s2])
    added = tl.wire_sequence_edges(graph)
    assert added == 1
    assert graph.latest_in_sequence("L-v1") == "L-v2"


def test_wire_sequence_edges_skips_missing_nodes() -> None:
    s1 = _snap("0001", _leaf("L-v1", "m5/x.docx"))
    s2 = _snap("0002", _leaf("L-v2", "m5/x.docx", op=LeafOperation.REPLACE))
    # Graph only has the current sequence — prior leaf isn't a node.
    graph = BackboneGraph.from_snapshot(s2)
    tl = SequenceTimeline.from_snapshots([s1, s2])
    added = tl.wire_sequence_edges(graph)
    assert added == 0


def test_wire_sequence_edges_skips_when_leaf_id_unchanged() -> None:
    """Same leaf_id across sequences → no self-loop NEXT_SEQUENCE edge."""
    s1 = _snap("0001", _leaf("L", "m5/x.docx", checksum="aa"))
    s2 = _snap(
        "0002", _leaf("L", "m5/x.docx", op=LeafOperation.REPLACE, checksum="bb")
    )
    graph = BackboneGraph.from_snapshot(s2)
    tl = SequenceTimeline.from_snapshots([s1, s2])
    added = tl.wire_sequence_edges(graph)
    assert added == 0


# ── find_latest_leaf top-level helper ──────────────────────────────────


def test_find_latest_leaf_helper() -> None:
    s1 = _snap(
        "0001",
        _leaf(
            "L-v1",
            "m5/x.docx",
            title="CSR SP-2024-001",
            checksum="aa",
        ),
    )
    s2 = _snap(
        "0002",
        _leaf(
            "L-v2",
            "m5/x.docx",
            op=LeafOperation.REPLACE,
            title="CSR SP-2024-001",
            checksum="bb",
        ),
    )
    leaf = find_latest_leaf("SP-2024-001", module="m5", snapshots=[s1, s2])
    assert leaf is not None
    assert leaf.checksum == "bb"


def test_find_latest_leaf_returns_none_when_missing() -> None:
    s1 = _snap("0001", _leaf("L", "m5/x.docx"))
    assert find_latest_leaf("MISSING", module=None, snapshots=[s1]) is None
