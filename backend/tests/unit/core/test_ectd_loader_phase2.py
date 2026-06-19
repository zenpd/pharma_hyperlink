"""Unit tests for Phase 2 additions to ingestion/ectd_loader.py."""

from __future__ import annotations

import hashlib
from pathlib import Path
from textwrap import dedent

import pytest

from hyperlink_engine.core.ingestion.ectd_loader import (
    diff_snapshots,
    load_backbone,
    load_backbone_with_regional,
    verify_checksums,
)
from hyperlink_engine.models import LeafIntegrityStatus, LeafOperation


def _write_index(path: Path, leaves_xml: str) -> None:
    path.write_text(
        dedent(
            f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <fda-regional submission-type="nda" submission-id="sponsor-0001">
                {leaves_xml}
              </fda-regional>
            </ectd>
            """
        ),
        encoding="utf-8",
    )


# ── load_backbone_with_regional ─────────────────────────────────────────


def test_regional_merge_picks_up_us_regional(tmp_path: Path) -> None:
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx">'
        "<title>Overview</title></leaf>",
    )
    us_dir = tmp_path / "m1" / "us"
    us_dir.mkdir(parents=True)
    us_xml = us_dir / "us-regional.xml"
    us_xml.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <us-regional xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="US-1" operation="new"
                    xlink:href="m1/us/1-3-1-letter.docx">
                <title>Cover letter</title>
              </leaf>
            </us-regional>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone_with_regional(main)
    assert snap.leaf_count == 2
    by_id = {leaf.leaf_id: leaf for leaf in snap.leaves}
    assert "L1" in by_id and "US-1" in by_id
    assert by_id["US-1"].region_source == "us"
    assert us_xml in snap.regional_sources


def test_regional_merge_dedupes_collisions(tmp_path: Path) -> None:
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="DUP" operation="new" '
        'xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx">'
        "<title>Main</title></leaf>",
    )
    us_dir = tmp_path / "m1" / "us"
    us_dir.mkdir(parents=True)
    (us_dir / "us-regional.xml").write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <us-regional xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="DUP" operation="new"
                    xlink:href="m1/us/dup.docx">
                <title>Regional dup</title>
              </leaf>
            </us-regional>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone_with_regional(main)
    # Main wins; regional collision dropped.
    assert snap.leaf_count == 1
    assert snap.leaves[0].title == "Main"


def test_regional_merge_extra_paths(tmp_path: Path) -> None:
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/x.docx"><title>x</title></leaf>',
    )
    extra = tmp_path / "extra.xml"
    extra.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <eu-regional xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="EU-1" operation="new"
                    xlink:href="m1/eu/eu-letter.docx">
                <title>EU letter</title>
              </leaf>
            </eu-regional>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone_with_regional(main, extra_regional=[extra])
    assert snap.leaf_count == 2
    assert any(leaf.leaf_id == "EU-1" for leaf in snap.leaves)
    # The base had us region already; explicit extra shouldn't override.
    assert snap.region == "us"


def test_regional_extra_missing_raises(tmp_path: Path) -> None:
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/x.docx"><title>x</title></leaf>',
    )
    from hyperlink_engine.core.ingestion.ectd_loader import EctdLoadError

    with pytest.raises(EctdLoadError, match="does not exist"):
        load_backbone_with_regional(main, extra_regional=[tmp_path / "ghost.xml"])


def test_regional_merge_inherits_region_when_main_silent(tmp_path: Path) -> None:
    main = tmp_path / "index.xml"
    main.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <ectd xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="L1" operation="new"
                    xlink:href="m2/x.docx"><title>x</title></leaf>
            </ectd>
            """
        ),
        encoding="utf-8",
    )
    jp_dir = tmp_path / "m1" / "jp"
    jp_dir.mkdir(parents=True)
    (jp_dir / "jp-regional.xml").write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <jp-regional xmlns:xlink="http://www.w3.org/1999/xlink" dtd-version="3.2">
              <leaf ID="JP-1" operation="new"
                    xlink:href="m1/jp/1-2-jp-form.docx">
                <title>JP form</title>
              </leaf>
            </jp-regional>
            """
        ),
        encoding="utf-8",
    )
    snap = load_backbone_with_regional(main)
    assert snap.region == "jp"


# ── verify_checksums ────────────────────────────────────────────────────


def test_verify_checksum_ok(tmp_path: Path) -> None:
    leaf_dir = tmp_path / "m2" / "2-5-clin-overview"
    leaf_dir.mkdir(parents=True)
    leaf_file = leaf_dir / "2-5-clin-overview.docx"
    leaf_file.write_bytes(b"hello world")
    digest = hashlib.md5(b"hello world").hexdigest()
    main = tmp_path / "index.xml"
    _write_index(
        main,
        f'<leaf ID="L1" operation="new" '
        f'xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx" '
        f'checksum="{digest}" checksum-type="md5">'
        "<title>x</title></leaf>",
    )
    snap = load_backbone(main)
    reports = verify_checksums(snap)
    assert len(reports) == 1
    assert reports[0].status == LeafIntegrityStatus.OK
    assert reports[0].actual == digest


def test_verify_checksum_mismatch(tmp_path: Path) -> None:
    leaf_dir = tmp_path / "m2" / "2-5-clin-overview"
    leaf_dir.mkdir(parents=True)
    (leaf_dir / "2-5-clin-overview.docx").write_bytes(b"actual content")
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/2-5-clin-overview/2-5-clin-overview.docx" '
        'checksum="ffffffffffffffffffffffffffffffff" checksum-type="md5">'
        "<title>x</title></leaf>",
    )
    snap = load_backbone(main)
    reports = verify_checksums(snap)
    assert reports[0].status == LeafIntegrityStatus.MISMATCH
    assert reports[0].expected == "ffffffffffffffffffffffffffffffff"


def test_verify_checksum_missing_file(tmp_path: Path) -> None:
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/missing.docx" checksum="0" checksum-type="md5">'
        "<title>x</title></leaf>",
    )
    snap = load_backbone(main)
    reports = verify_checksums(snap)
    assert reports[0].status == LeafIntegrityStatus.MISSING_FILE


def test_verify_checksum_no_checksum_declared(tmp_path: Path) -> None:
    leaf_dir = tmp_path / "m2"
    leaf_dir.mkdir(parents=True)
    (leaf_dir / "no-chk.docx").write_bytes(b"x")
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/no-chk.docx"><title>x</title></leaf>',
    )
    snap = load_backbone(main)
    reports = verify_checksums(snap)
    assert reports[0].status == LeafIntegrityStatus.NO_CHECKSUM


def test_verify_checksum_sha256_supported(tmp_path: Path) -> None:
    leaf_dir = tmp_path / "m2"
    leaf_dir.mkdir(parents=True)
    payload = b"sha256-tester"
    (leaf_dir / "x.docx").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    main = tmp_path / "index.xml"
    _write_index(
        main,
        f'<leaf ID="L1" operation="new" '
        f'xlink:href="m2/x.docx" checksum="{digest}" checksum-type="sha256">'
        "<title>x</title></leaf>",
    )
    snap = load_backbone(main)
    reports = verify_checksums(snap)
    assert reports[0].status == LeafIntegrityStatus.OK


def test_verify_checksum_unsupported_algo(tmp_path: Path) -> None:
    leaf_dir = tmp_path / "m2"
    leaf_dir.mkdir(parents=True)
    (leaf_dir / "x.docx").write_bytes(b"x")
    main = tmp_path / "index.xml"
    _write_index(
        main,
        '<leaf ID="L1" operation="new" '
        'xlink:href="m2/x.docx" checksum="deadbeef" checksum-type="crc32">'
        "<title>x</title></leaf>",
    )
    snap = load_backbone(main)
    reports = verify_checksums(snap)
    assert reports[0].status == LeafIntegrityStatus.NO_CHECKSUM
    assert "crc32" in (reports[0].error_msg or "")


# ── diff_snapshots ──────────────────────────────────────────────────────


def _snapshot(tmp_path: Path, leaves_xml: str, name: str = "index.xml") -> Path:
    path = tmp_path / name
    _write_index(path, leaves_xml)
    return path


def test_diff_detects_added_and_removed(tmp_path: Path) -> None:
    prev = load_backbone(
        _snapshot(
            tmp_path,
            '<leaf ID="A" operation="new" xlink:href="m2/a.docx" checksum="aa"><title>A</title></leaf>',
            name="prev.xml",
        )
    )
    cur = load_backbone(
        _snapshot(
            tmp_path,
            '<leaf ID="B" operation="new" xlink:href="m2/b.docx" checksum="bb"><title>B</title></leaf>',
            name="cur.xml",
        )
    )
    diff = diff_snapshots(prev, cur)
    assert diff.added_leaf_ids == ["B"]
    assert diff.removed_leaf_ids == ["A"]
    assert diff.is_clean is False


def test_diff_modified_by_checksum(tmp_path: Path) -> None:
    prev = load_backbone(
        _snapshot(
            tmp_path,
            '<leaf ID="X" operation="new" xlink:href="m2/x.docx" checksum="111"><title>X</title></leaf>',
            name="prev.xml",
        )
    )
    cur = load_backbone(
        _snapshot(
            tmp_path,
            '<leaf ID="X" operation="replace" xlink:href="m2/x.docx" checksum="222"><title>X</title></leaf>',
            name="cur.xml",
        )
    )
    diff = diff_snapshots(prev, cur)
    assert diff.modified_leaf_ids == ["X"]
    assert diff.unchanged_leaf_ids == []


def test_diff_clean_when_identical(tmp_path: Path) -> None:
    src = '<leaf ID="K" operation="new" xlink:href="m2/k.docx" checksum="kk"><title>K</title></leaf>'
    prev = load_backbone(_snapshot(tmp_path, src, name="a.xml"))
    cur = load_backbone(_snapshot(tmp_path, src, name="b.xml"))
    diff = diff_snapshots(prev, cur)
    assert diff.is_clean
    assert diff.unchanged_leaf_ids == ["K"]


def test_diff_modified_falls_back_to_operation_when_no_checksum(tmp_path: Path) -> None:
    prev = load_backbone(
        _snapshot(
            tmp_path,
            '<leaf ID="Y" operation="new" xlink:href="m2/y.docx"><title>Y</title></leaf>',
            name="prev.xml",
        )
    )
    cur = load_backbone(
        _snapshot(
            tmp_path,
            '<leaf ID="Y" operation="replace" xlink:href="m2/y.docx"><title>Y</title></leaf>',
            name="cur.xml",
        )
    )
    diff = diff_snapshots(prev, cur)
    assert diff.modified_leaf_ids == ["Y"]


# ── Leaf model extensions ───────────────────────────────────────────────


def test_is_modified_reflects_operation(tmp_path: Path) -> None:
    main = _snapshot(
        tmp_path,
        (
            '<leaf ID="N" operation="new" xlink:href="m2/n.docx"><title>n</title></leaf>'
            '<leaf ID="R" operation="replace" xlink:href="m2/r.docx"><title>r</title></leaf>'
            '<leaf ID="A" operation="append" xlink:href="m2/a.docx"><title>a</title></leaf>'
        ),
    )
    snap = load_backbone(main)
    by_id = {leaf.leaf_id: leaf for leaf in snap.leaves}
    assert by_id["N"].is_modified is False
    assert by_id["R"].is_modified is True
    assert by_id["A"].is_modified is True
    modified_ids = sorted(leaf.leaf_id for leaf in snap.modified_leaves)
    assert modified_ids == ["A", "R"]


def test_leaf_by_id_returns_none_for_unknown(tmp_path: Path) -> None:
    main = _snapshot(
        tmp_path,
        '<leaf ID="ONE" operation="new" xlink:href="m2/x.docx"><title>x</title></leaf>',
    )
    snap = load_backbone(main)
    assert snap.leaf_by_id("ONE") is not None
    assert snap.leaf_by_id("MISSING") is None
    assert snap.leaves[0].operation == LeafOperation.NEW
