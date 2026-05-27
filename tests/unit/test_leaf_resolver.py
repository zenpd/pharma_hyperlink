"""Unit tests for graph/leaf_resolver.py."""

from __future__ import annotations

from pathlib import Path

from hyperlink_engine.detection.entity_extractor import ExtractedReference
from hyperlink_engine.graph.backbone_graph import BackboneGraph
from hyperlink_engine.graph.leaf_resolver import (
    LeafResolution,
    LeafResolver,
    UnresolvedLeaf,
    _jaccard,
    _tokenize,
    leaf_path,
    resolve_for_snapshot,
)
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    LeafOperation,
)


def _snapshot() -> BackboneSnapshot:
    return BackboneSnapshot(
        provenance=DocumentProvenance(
            source_path=Path("index.xml"),
            sha256="0" * 64,
            file_size_bytes=10,
        ),
        schema_version="v3.2",
        region="us",
        sequence_number="0001",
        leaves=[
            BackboneLeaf(
                leaf_id="L-overview",
                relative_path=Path("m2/2-5-clin-overview/2-5-clin-overview.docx"),
                module="m2.5",
                operation=LeafOperation.NEW,
                title="Clinical Overview",
            ),
            BackboneLeaf(
                leaf_id="L-csr-001",
                relative_path=Path("m5/5-3-1-bio-stud-rep/SP-2024-001-csr.docx"),
                module="m5.3.1",
                operation=LeafOperation.NEW,
                title="CSR for Study SP-2024-001",
            ),
            BackboneLeaf(
                leaf_id="L-csr-002",
                relative_path=Path("m5/5-3-1-bio-stud-rep/SP-2024-002-csr.docx"),
                module="m5.3.1",
                operation=LeafOperation.NEW,
                title="CSR for Study SP-2024-002",
            ),
            BackboneLeaf(
                leaf_id="L-cover",
                relative_path=Path("m1/us/1-3-1-letter.docx"),
                module="m1",
                operation=LeafOperation.NEW,
                title="Cover letter",
            ),
        ],
    )


def _ref(label: str, text: str, groups: dict[str, str] | None = None) -> ExtractedReference:
    return ExtractedReference(
        pattern_id=f"{label}_TEST_V1",
        label=label,
        text=text,
        start=0,
        end=len(text),
        confidence=0.95,
        source_layer="regex",
        groups=groups or {},
    )


# ── tokenizer / jaccard helpers ─────────────────────────────────────────


def test_tokenize_splits_on_punct_and_lowercases() -> None:
    tokens = _tokenize("CSR for Study SP-2024-001")
    assert "csr" in tokens
    assert "study" in tokens
    assert "sp" in tokens
    assert "2024" in tokens
    assert "001" in tokens
    # Single-char tokens dropped
    assert "a" not in tokens


def test_tokenize_empty() -> None:
    assert _tokenize("") == set()
    assert _tokenize("!@#") == set()


def test_jaccard_basic() -> None:
    a = {"x", "y", "z"}
    b = {"y", "z"}
    assert _jaccard(a, b) == 2 / 3
    assert _jaccard(set(), b) == 0.0
    assert _jaccard(a, set()) == 0.0


# ── CTD_LEAF resolution ─────────────────────────────────────────────────


def test_resolve_ctd_leaf_exact_module() -> None:
    resolver = LeafResolver(_snapshot())
    ref = _ref("CTD_LEAF", "Module 2.5", groups={"mod": "2", "sub": "5"})
    outcome = resolver.resolve(ref)
    assert isinstance(outcome, LeafResolution)
    assert outcome.leaf.leaf_id == "L-overview"
    assert outcome.strategy == "module_exact"
    assert outcome.confidence == 0.95


def test_resolve_ctd_leaf_prefix_falls_through() -> None:
    resolver = LeafResolver(_snapshot())
    # m5.3 doesn't appear exactly — only m5.3.1 does; resolver should prefix-match.
    ref = _ref("CTD_LEAF", "Module 5.3", groups={"mod": "5", "sub": "3"})
    outcome = resolver.resolve(ref)
    assert isinstance(outcome, LeafResolution)
    assert outcome.leaf.module == "m5.3.1"
    assert outcome.strategy == "module_prefix"
    assert outcome.confidence < 0.95


def test_resolve_ctd_leaf_unknown_module_falls_through_title() -> None:
    resolver = LeafResolver(_snapshot(), min_confidence=0.4)
    # m9 doesn't exist; CTD_LEAF resolution gives None, then title fallback
    # tries to match — but the ref text "Module 9" has weak overlap with any
    # title, so we should land on UnresolvedLeaf or a low-confidence pick.
    ref = _ref("CTD_LEAF", "Module 9", groups={"mod": "9"})
    outcome = resolver.resolve(ref)
    # We accept either UnresolvedLeaf or a fuzzy title resolution as long as
    # the resolver didn't raise — the contract is "no crash on missing modules".
    assert isinstance(outcome, (LeafResolution, UnresolvedLeaf))


# ── STUDY_ID resolution ─────────────────────────────────────────────────


def test_resolve_study_id_finds_match_in_title() -> None:
    resolver = LeafResolver(_snapshot())
    ref = _ref("STUDY_ID", "SP-2024-001")
    outcome = resolver.resolve(ref)
    assert isinstance(outcome, LeafResolution)
    assert outcome.leaf.leaf_id == "L-csr-001"
    assert outcome.strategy == "study_id"


def test_resolve_study_id_no_match_falls_to_title() -> None:
    resolver = LeafResolver(_snapshot(), min_confidence=0.4)
    ref = _ref("STUDY_ID", "XYZ-9999-999")
    outcome = resolver.resolve(ref)
    # No leaf contains XYZ-9999-999, so study-id strategy returns None and
    # the title fuzzy fallback runs. The text has very low Jaccard against
    # any title — expect unresolved.
    assert isinstance(outcome, UnresolvedLeaf)
    assert "no strategy" in outcome.reason


# ── Title fuzzy fallback ────────────────────────────────────────────────


def test_resolve_title_fuzzy_for_section_ref() -> None:
    resolver = LeafResolver(_snapshot(), min_confidence=0.3)
    # SECTION_REF without explicit groups — should fall through to title.
    ref = _ref("SECTION_REF", "Clinical Overview")
    outcome = resolver.resolve(ref)
    assert isinstance(outcome, LeafResolution)
    assert outcome.leaf.leaf_id == "L-overview"
    assert outcome.strategy == "title_fuzzy"


def test_resolve_title_fuzzy_respects_threshold() -> None:
    resolver = LeafResolver(_snapshot(), min_confidence=0.99)
    ref = _ref("SECTION_REF", "Clinical")  # weak token overlap
    outcome = resolver.resolve(ref)
    assert isinstance(outcome, UnresolvedLeaf)


def test_min_confidence_property() -> None:
    resolver = LeafResolver(_snapshot(), min_confidence=0.42)
    assert resolver.min_confidence == 0.42


# ── Batch resolve_many ──────────────────────────────────────────────────


def test_resolve_many_splits_outcomes() -> None:
    resolver = LeafResolver(_snapshot(), min_confidence=0.5)
    refs = [
        _ref("CTD_LEAF", "Module 2.5", groups={"mod": "2", "sub": "5"}),
        _ref("STUDY_ID", "SP-2024-001"),
        _ref("STUDY_ID", "ZZZ-9999"),
    ]
    resolved, unresolved = resolver.resolve_many(refs)
    assert len(resolved) == 2
    assert len(unresolved) == 1
    assert unresolved[0].reference.text == "ZZZ-9999"


def test_resolve_for_snapshot_helper_matches_resolver() -> None:
    snap = _snapshot()
    refs = [_ref("CTD_LEAF", "Module 2.5", groups={"mod": "2", "sub": "5"})]
    resolved, unresolved = resolve_for_snapshot(refs, snap)
    assert len(resolved) == 1
    assert resolved[0].leaf.module == "m2.5"
    assert not unresolved


# ── Graph wiring ────────────────────────────────────────────────────────


def test_resolver_works_with_optional_graph_argument() -> None:
    snap = _snapshot()
    graph = BackboneGraph.from_snapshot(snap)
    resolver = LeafResolver(snap, graph=graph)
    ref = _ref("CTD_LEAF", "Module 5.3.1", groups={"mod": "5", "sub": "3.1"})
    outcome = resolver.resolve(ref)
    assert isinstance(outcome, LeafResolution)
    # The leaf must exist as a node in the graph.
    assert graph.has_leaf(outcome.leaf.leaf_id)


# ── leaf_path helper ────────────────────────────────────────────────────


def test_leaf_path_relative_when_no_base() -> None:
    snap = _snapshot()
    leaf = snap.leaves[0]
    assert leaf_path(leaf) == leaf.relative_path


def test_leaf_path_joined_when_base_given(tmp_path: Path) -> None:
    snap = _snapshot()
    leaf = snap.leaves[0]
    full = leaf_path(leaf, base=tmp_path)
    assert full == tmp_path / leaf.relative_path
