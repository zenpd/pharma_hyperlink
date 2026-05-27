"""Unit tests for injection/ectd_backbone_writer.py."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from lxml import etree

from hyperlink_engine.injection.ectd_backbone_writer import (
    BackboneEditPlan,
    BackboneWriteError,
    BackboneWriter,
    LeafXrefEdit,
)

_XLINK_NS = "http://www.w3.org/1999/xlink"


@pytest.fixture
def basic_backbone(tmp_path: Path) -> Path:
    path = tmp_path / "index.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="L1" operation="new"
                    xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx">
                <title>Clinical Overview</title>
              </leaf>
              <leaf ID="L2" operation="new"
                    xlink:href="m5/5-3-1-bio-stud-rep/study-001.docx">
                <title>CSR Study 001</title>
              </leaf>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    return path


def test_edit_plan_starts_empty() -> None:
    plan = BackboneEditPlan()
    assert len(plan) == 0
    assert not plan
    plan.add_leaf_xref("L1", "m5/x.docx")
    assert len(plan) == 1
    assert plan


def test_edit_plan_extend() -> None:
    plan = BackboneEditPlan()
    plan.extend([LeafXrefEdit("L1", "m5/y.docx"), LeafXrefEdit("L2", "m5/z.docx")])
    assert len(plan) == 2


def test_writer_raises_when_source_missing(tmp_path: Path) -> None:
    with pytest.raises(BackboneWriteError, match="does not exist"):
        BackboneWriter(tmp_path / "missing.xml", tmp_path / "out.xml")


def test_writer_raises_on_malformed_xml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<ectd><leaf></ectd>", encoding="utf-8")
    with pytest.raises(BackboneWriteError, match="could not parse"):
        BackboneWriter(bad, tmp_path / "out.xml")


def test_apply_adds_leaf_xref_element(basic_backbone: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.xml"
    writer = BackboneWriter(basic_backbone, out)
    plan = BackboneEditPlan()
    plan.add_leaf_xref(
        "L1",
        "m5/5-3-1-bio-stud-rep/study-001.docx",
        anchor="section_5_3_1",
    )
    assert writer.apply(plan) == 1
    writer.save()
    assert out.exists()

    tree = etree.parse(str(out))
    root = tree.getroot()
    xrefs = [el for el in root.iter() if etree.QName(el).localname == "leaf-xref"]
    assert len(xrefs) == 1
    href = xrefs[0].attrib.get(f"{{{_XLINK_NS}}}href")
    assert href == "m5/5-3-1-bio-stud-rep/study-001.docx#section_5_3_1"


def test_apply_skips_unknown_source_leaf(basic_backbone: Path, tmp_path: Path) -> None:
    writer = BackboneWriter(basic_backbone, tmp_path / "out.xml")
    plan = BackboneEditPlan()
    plan.add_leaf_xref("DOES-NOT-EXIST", "m5/x.docx")
    assert writer.apply(plan) == 0


def test_apply_is_idempotent_for_duplicate_xref(basic_backbone: Path, tmp_path: Path) -> None:
    writer = BackboneWriter(basic_backbone, tmp_path / "out.xml")
    plan = BackboneEditPlan()
    plan.add_leaf_xref("L1", "m5/x.docx", anchor="a1")
    plan.add_leaf_xref("L1", "m5/x.docx", anchor="a1")  # duplicate
    applied = writer.apply(plan)
    assert applied == 1


def test_apply_supports_xref_without_anchor(basic_backbone: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.xml"
    writer = BackboneWriter(basic_backbone, out)
    plan = BackboneEditPlan()
    plan.add_leaf_xref("L1", "m5/5-3-1-bio-stud-rep/study-001.docx")
    writer.apply(plan)
    writer.save()
    tree = etree.parse(str(out))
    root = tree.getroot()
    xrefs = [el for el in root.iter() if etree.QName(el).localname == "leaf-xref"]
    assert xrefs[0].attrib.get(f"{{{_XLINK_NS}}}href") == "m5/5-3-1-bio-stud-rep/study-001.docx"


def test_save_creates_parent_dir(basic_backbone: Path, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deeper" / "out.xml"
    writer = BackboneWriter(basic_backbone, out)
    writer.save()
    assert out.exists()


def test_save_emits_xml_declaration(basic_backbone: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.xml"
    writer = BackboneWriter(basic_backbone, out)
    writer.save()
    content = out.read_text(encoding="utf-8")
    assert content.lstrip().startswith("<?xml")
