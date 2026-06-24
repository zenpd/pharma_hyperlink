"""Unit tests for the W6.1 cross-module additions to injection/ectd_xref.py."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from lxml import etree

from hyperlink_engine.core.detection.entity_extractor import ExtractedReference
from hyperlink_engine.core.injection.ectd_xref import (
    EctdCrossRefBuilder,
    compute_relative_uri,
)
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    LeafOperation,
)

_XLINK_NS = "http://www.w3.org/1999/xlink"


# ── compute_relative_uri ────────────────────────────────────────────────


def test_relative_uri_simple_cross_module() -> None:
    src = Path("m2/2-5-clin-overview/2-5-clin-overview.docx")
    dst = Path("m5/5-3-1-bio-stud-rep/study-001.docx")
    rel = compute_relative_uri(source=src, target=dst)
    assert rel == "../../m5/5-3-1-bio-stud-rep/study-001.docx"


def test_relative_uri_with_anchor() -> None:
    src = Path("m2/2-5-clin-overview/2-5-clin-overview.docx")
    dst = Path("m5/5-3-1-bio-stud-rep/study-001.docx")
    rel = compute_relative_uri(source=src, target=dst, anchor="section_5_3_1")
    assert rel.endswith("#section_5_3_1")
    assert rel.startswith("../../m5/")


def test_relative_uri_same_directory() -> None:
    src = Path("m5/5-3-1-bio-stud-rep/a.docx")
    dst = Path("m5/5-3-1-bio-stud-rep/b.docx")
    rel = compute_relative_uri(source=src, target=dst)
    assert rel == "b.docx"


def test_relative_uri_normalizes_windows_paths() -> None:
    src = Path("m2") / "2-5" / "x.docx"
    dst = Path("m5") / "5-3" / "y.docx"
    rel = compute_relative_uri(source=src, target=dst)
    # No backslashes regardless of input separator.
    assert "\\" not in rel
    assert rel.endswith("y.docx")


# ── Builder cross-module resolution ─────────────────────────────────────


def _snap() -> BackboneSnapshot:
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
                relative_path=Path("m2/2-5-clin-overview/overview.docx"),
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
        ],
    )


def _ref(label: str, text: str, groups: dict[str, str] | None = None) -> ExtractedReference:
    return ExtractedReference(
        pattern_id=f"{label}_V1",
        label=label,
        text=text,
        start=0,
        end=len(text),
        confidence=0.95,
        source_layer="regex",
        groups=groups or {},
    )


def test_resolve_cross_module_returns_link() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    refs = [_ref("CTD_LEAF", "Module 5.3.1", groups={"mod": "5", "sub": "3.1"})]
    links, unresolved = builder.resolve_cross_module(refs, source_leaf=source)
    assert not unresolved
    assert len(links) == 1
    link = links[0]
    assert link.source_leaf_id == "L-overview"
    assert link.target_leaf_id == "L-csr-001"  # first leaf in m5.3.1 module
    assert link.relative_uri.startswith("../../m5/")


def test_resolve_cross_module_drops_self_ref() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    # SECTION_REF for Clinical Overview — title-fuzzy match will resolve to the
    # same leaf, which must be filtered out.
    refs = [_ref("SECTION_REF", "Clinical Overview")]
    links, unresolved = builder.resolve_cross_module(refs, source_leaf=source)
    assert not links
    assert unresolved
    assert "self-reference" in unresolved[0].reason


def test_resolve_cross_module_records_unresolved() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = snap.leaves[0]
    refs = [_ref("STUDY_ID", "ZZZ-9999-999")]  # nothing in titles
    links, unresolved = builder.resolve_cross_module(refs, source_leaf=source)
    assert not links
    assert len(unresolved) == 1


def test_resolve_cross_module_uses_study_id_anchor() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    refs = [_ref("STUDY_ID", "SP-2024-001")]
    links, _ = builder.resolve_cross_module(refs, source_leaf=source)
    assert len(links) == 1
    assert links[0].anchor == "study_SP_2024_001"
    assert links[0].relative_uri.endswith("#study_SP_2024_001")


def test_resolve_cross_module_section_anchor_shape() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = snap.leaves[0]
    refs = [
        _ref("CTD_LEAF", "Module 5.3.1", groups={"mod": "5", "sub": "3.1"}),
    ]
    links, _ = builder.resolve_cross_module(refs, source_leaf=source)
    assert links[0].anchor is None  # CTD_LEAF has no per-section anchor by default


def test_cross_module_link_is_same_module_helper() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    refs = [_ref("CTD_LEAF", "Module 5.3.1", groups={"mod": "5", "sub": "3.1"})]
    links, _ = builder.resolve_cross_module(refs, source_leaf=source)
    assert links[0].is_same_module is False
    # In-module case: m2 → m2
    refs2 = [_ref("CTD_LEAF", "Module 2.5", groups={"mod": "2", "sub": "5"})]
    links2, _ = builder.resolve_cross_module(refs2, source_leaf=source)
    # m2.5 maps back to L-overview which IS the source — self-ref filtered.
    assert not links2


# ── build_edit_plan + write_backbone_with_edits ────────────────────────


def _backbone_xml(tmp_path: Path) -> Path:
    path = tmp_path / "index.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="L-overview" operation="new"
                    xlink:href="m2/2-5-clin-overview/overview.docx">
                <title>Clinical Overview</title>
              </leaf>
              <leaf ID="L-csr-001" operation="new"
                    xlink:href="m5/5-3-1-bio-stud-rep/SP-2024-001-csr.docx">
                <title>CSR Study 001</title>
              </leaf>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    return path


def test_build_edit_plan_emits_correct_targets() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    refs = [_ref("STUDY_ID", "SP-2024-001")]
    links, _ = builder.resolve_cross_module(refs, source_leaf=source)
    plan = builder.build_edit_plan(links)
    assert len(plan) == 1
    edit = plan.leaf_xrefs[0]
    assert edit.source_leaf_id == "L-overview"
    assert edit.target_href.endswith("SP-2024-001-csr.docx")
    assert edit.anchor == "study_SP_2024_001"


def test_write_backbone_with_edits_roundtrips(tmp_path: Path) -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    refs = [_ref("STUDY_ID", "SP-2024-001")]
    links, _ = builder.resolve_cross_module(refs, source_leaf=source)
    plan = builder.build_edit_plan(links)

    src_path = _backbone_xml(tmp_path)
    out_path = tmp_path / "out.xml"
    builder.write_backbone_with_edits(
        plan, source_backbone_path=src_path, output_path=out_path
    )

    tree = etree.parse(str(out_path))
    root = tree.getroot()
    xrefs = [el for el in root.iter() if etree.QName(el).localname == "leaf-xref"]
    assert len(xrefs) == 1
    href = xrefs[0].attrib.get(f"{{{_XLINK_NS}}}href")
    assert "SP-2024-001-csr.docx#study_SP_2024_001" in href


# ── inject_cross_module_xref (Path + BackboneLeaf both supported) ───────


def test_inject_cross_module_xref_accepts_backbone_leaf() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    target = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-csr-001")
    plan = builder.inject_cross_module_xref(source, target, anchor="study_SP_2024_001")
    assert len(plan) == 1
    assert plan.leaf_xrefs[0].source_leaf_id == "L-overview"
    assert plan.leaf_xrefs[0].anchor == "study_SP_2024_001"


def test_inject_cross_module_xref_accepts_path() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    plan = builder.inject_cross_module_xref(
        Path("m2/2-5-clin-overview/overview.docx"),
        Path("m5/5-3-1-bio-stud-rep/SP-2024-001-csr.docx"),
        anchor="study_SP_2024_001",
    )
    assert len(plan) == 1
    assert plan.leaf_xrefs[0].source_leaf_id == "L-overview"


def test_inject_cross_module_xref_unknown_source_path_is_logged_not_raised() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    # Unknown path → no edit added, no exception.
    plan = builder.inject_cross_module_xref(
        Path("m9/missing.docx"),
        Path("m5/x.docx"),
        anchor=None,
    )
    assert len(plan) == 0


def test_inject_cross_module_xref_accumulates_into_existing_plan() -> None:
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    source = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-overview")
    target1 = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-csr-001")
    target2 = next(leaf for leaf in snap.leaves if leaf.leaf_id == "L-csr-002")
    plan = builder.inject_cross_module_xref(source, target1)
    builder.inject_cross_module_xref(source, target2, plan=plan)
    assert len(plan) == 2


# ── Backward-compat: legacy resolve() still works ──────────────────────


def test_legacy_resolve_still_works_with_extended_builder() -> None:
    """Phase 1 ``resolve()`` behavior must not regress."""
    snap = _snap()
    builder = EctdCrossRefBuilder(snap)
    refs = [_ref("CTD_LEAF", "Module 2.5", groups={"mod": "2", "sub": "5"})]
    resolved, unresolved = builder.resolve(refs, current_module="m2.5")
    assert len(resolved) == 1
    assert resolved[0].leaf.leaf_id == "L-overview"
    assert not unresolved
