"""Unit tests for ingestion/ectd_loader.py."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from hyperlink_engine.ingestion.ectd_loader import EctdLoadError, load_backbone
from hyperlink_engine.models import LeafOperation


@pytest.fixture
def v32_backbone(tmp_path: Path) -> Path:
    path = tmp_path / "index.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns="urn:hl7-org:v3"
                  xmlns:xlink="http://www.w3.org/1999/xlink"
                  dtd-version="3.2">
              <fda-regional submission-type="nda" submission-id="sponsor-0001">
                <leaf ID="leaf-1" operation="new"
                      xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx"
                      checksum="abc123" checksum-type="md5">
                  <title>2-5 Clinical Overview</title>
                </leaf>
                <leaf ID="leaf-2" operation="replace"
                      xlink:href="m5/5-3-1-bio-stud-rep/study-001.docx">
                  <title>Study 001 CSR</title>
                </leaf>
                <leaf ID="leaf-3" operation="new"
                      xlink:href="m1/us/1-3-1-letter.docx">
                  <title>Cover letter</title>
                </leaf>
              </fda-regional>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    return path


def test_loader_parses_v32_backbone(v32_backbone: Path) -> None:
    snap = load_backbone(v32_backbone)
    assert snap.schema_version == "v3.2"
    assert snap.region == "us"
    assert snap.sequence_number == "0001"
    assert snap.leaf_count == 3


def test_leaf_module_derivation(v32_backbone: Path) -> None:
    snap = load_backbone(v32_backbone)
    by_id = {leaf.leaf_id: leaf for leaf in snap.leaves}
    assert by_id["leaf-1"].module == "m2.5"
    assert by_id["leaf-2"].module == "m5.3.1"
    assert by_id["leaf-3"].module == "m1"  # region directory has no numeric subpath


def test_leaf_operation_parsed(v32_backbone: Path) -> None:
    snap = load_backbone(v32_backbone)
    by_id = {leaf.leaf_id: leaf for leaf in snap.leaves}
    assert by_id["leaf-1"].operation == LeafOperation.NEW
    assert by_id["leaf-2"].operation == LeafOperation.REPLACE


def test_leaf_checksum_picked_up(v32_backbone: Path) -> None:
    snap = load_backbone(v32_backbone)
    leaf1 = next(leaf for leaf in snap.leaves if leaf.leaf_id == "leaf-1")
    assert leaf1.checksum == "abc123"
    assert leaf1.checksum_type == "md5"


def test_leaves_by_module(v32_backbone: Path) -> None:
    snap = load_backbone(v32_backbone)
    m5_leaves = snap.leaves_by_module("m5")
    assert len(m5_leaves) == 1
    assert m5_leaves[0].leaf_id == "leaf-2"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EctdLoadError, match="does not exist"):
        load_backbone(tmp_path / "ghost.xml")


def test_malformed_xml(tmp_path: Path) -> None:
    bad = tmp_path / "bad.xml"
    bad.write_text("<ectd><leaf></ectd>", encoding="utf-8")
    with pytest.raises(EctdLoadError, match="not well-formed XML"):
        load_backbone(bad)


def test_loads_real_synthetic_backbone() -> None:
    """End-to-end smoke test against the synthetic dossier generated in Week 1."""
    synthetic = Path("data/synthetic/index.xml")
    if not synthetic.exists():
        pytest.skip("synthetic dataset not generated yet — run `make synthetic`")
    snap = load_backbone(synthetic)
    assert snap.leaf_count >= 20
    assert snap.schema_version == "v3.2"


def test_loader_rejects_directory(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    with pytest.raises(EctdLoadError, match="is not a file"):
        load_backbone(sub)


def test_unknown_op_falls_back_to_new(tmp_path: Path) -> None:
    path = tmp_path / "weird.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="weird-1" operation="hocus-pocus"
                    xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx">
                <title>x</title>
              </leaf>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone(path)
    assert snap.leaves[0].operation == LeafOperation.NEW


def test_leaf_with_inline_checksum_element(tmp_path: Path) -> None:
    path = tmp_path / "inline_chk.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="ic-1" operation="new"
                    xlink:href="m3/3-2-quality/3-2-s-drug-substance.docx">
                <title>quality</title>
                <checksum>deadbeefcafe</checksum>
              </leaf>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone(path)
    assert snap.leaves[0].checksum == "deadbeefcafe"


def test_leaf_missing_href_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "no_href.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="ok"
                    xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx">
                <title>ok</title>
              </leaf>
              <leaf ID="dangling">
                <title>missing-href</title>
              </leaf>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone(path)
    assert snap.leaf_count == 1
    assert snap.leaves[0].leaf_id == "ok"


def test_eu_regional_detected(tmp_path: Path) -> None:
    path = tmp_path / "eu.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <eu-regional submission-type="maa" sequence="0007">
                <leaf ID="eu-1" operation="new"
                      xlink:href="m1/eu/1-2-application-form.docx">
                  <title>EU app form</title>
                </leaf>
              </eu-regional>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone(path)
    assert snap.region == "eu"
    assert snap.sequence_number == "0007"


def test_v4_detected_by_root_element(tmp_path: Path) -> None:
    path = tmp_path / "v4.xml"
    path.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <submission xmlns:xlink="http://www.w3.org/1999/xlink">
              <leaf ID="v4-1" operation="new"
                    xlink:href="m2/2-5-clin-overview/x.docx">
                <title>v4</title>
              </leaf>
            </submission>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone(path)
    assert snap.schema_version == "v4.0"


def test_module_label_for_unknown_path() -> None:
    from hyperlink_engine.ingestion.ectd_loader import _leaf_module

    assert _leaf_module("nowhere/special.docx") == "unknown"
    assert _leaf_module("m9/weird.docx") == "unknown"  # regex requires 1-5
    assert _leaf_module("m1") == "m1"
