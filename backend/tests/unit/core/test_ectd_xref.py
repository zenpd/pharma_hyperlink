"""Unit tests for injection/ectd_xref.py."""

from __future__ import annotations

from pathlib import Path

from hyperlink_engine.core.detection.entity_extractor import ExtractedReference
from hyperlink_engine.core.injection.ectd_xref import EctdCrossRefBuilder
from hyperlink_engine.models import BackboneLeaf, BackboneSnapshot, DocumentProvenance


def _snapshot() -> BackboneSnapshot:
    prov = DocumentProvenance(
        source_path=Path("index.xml"),
        sha256="0" * 64,
        file_size_bytes=100,
    )
    return BackboneSnapshot(
        provenance=prov,
        schema_version="v3.2",
        region="us",
        sequence_number="0001",
        leaves=[
            BackboneLeaf(
                leaf_id="leaf-1",
                relative_path=Path("m2/2-5-clin-overview/2-5-clin-overview.docx"),
                module="m2.5",
            ),
            BackboneLeaf(
                leaf_id="leaf-2",
                relative_path=Path("m5/5-3-1-bio-stud-rep/study-001.docx"),
                module="m5.3.1",
            ),
        ],
    )


def _ref(label: str, mod: str, sub: str = "") -> ExtractedReference:
    return ExtractedReference(
        pattern_id="CTD_LEAF_MODULE_V1",
        label=label,
        text=f"Module {mod}.{sub}" if sub else f"Module {mod}",
        start=0,
        end=12,
        confidence=0.95,
        source_layer="regex",
        groups={"mod": mod, "sub": sub} if sub else {"mod": mod},
    )


def test_in_module_link_resolves() -> None:
    builder = EctdCrossRefBuilder(_snapshot())
    refs = [_ref("CTD_LEAF", "2", "5")]
    resolved, unresolved = builder.resolve(refs, current_module="m2.5")
    assert len(resolved) == 1
    assert resolved[0].leaf.module == "m2.5"
    assert not unresolved


def test_cross_module_deferred_to_phase_2() -> None:
    builder = EctdCrossRefBuilder(_snapshot())
    refs = [_ref("CTD_LEAF", "5", "3.1")]
    _, unresolved = builder.resolve(refs, current_module="m2.5")
    assert len(unresolved) == 1
    assert "cross-module" in unresolved[0].reason.lower()


def test_non_ctd_label_is_unresolved() -> None:
    builder = EctdCrossRefBuilder(_snapshot())
    ref = ExtractedReference(
        pattern_id="SECTION_REF_LABELED_V1",
        label="SECTION_REF",
        text="Section 2.5.3",
        start=0,
        end=13,
        confidence=0.92,
        source_layer="regex",
        groups={"num": "2.5.3"},
    )
    _, unresolved = builder.resolve([ref])
    assert unresolved
    assert "not yet supported" in unresolved[0].reason


def test_unknown_module_returns_unresolved() -> None:
    builder = EctdCrossRefBuilder(_snapshot())
    refs = [_ref("CTD_LEAF", "9")]  # m9 doesn't exist in catalog regex anyway
    _, unresolved = builder.resolve(refs, current_module="m9")
    assert unresolved
    assert "no leaf" in unresolved[0].reason.lower()


def test_inject_cross_module_xref_is_noop() -> None:
    builder = EctdCrossRefBuilder(_snapshot())
    # The Phase 1 stub must not raise.
    builder.inject_cross_module_xref(
        source_leaf=Path("m2/x.docx"),
        target_leaf=Path("m5/y.docx"),
        anchor="section_2_5_3",
    )
