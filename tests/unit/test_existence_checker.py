"""Unit tests for validation/existence_checker.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from hyperlink_engine.models import LinkKind, LinkStatus
from hyperlink_engine.validation.existence_checker import (
    LinkProbe,
    check_all,
    check_link,
)


# ── External URL ────────────────────────────────────────────────────────


def test_external_https_is_unverified() -> None:
    probe = LinkProbe(
        source_doc="doc.docx",
        link_text="example",
        location_descriptor="p0.r0",
        kind=LinkKind.EXTERNAL_URL,
        target="https://example.org/path",
    )
    record = check_link(probe)
    assert record.status == LinkStatus.UNVERIFIED
    assert record.error_msg is None


def test_external_missing_host_is_broken() -> None:
    probe = LinkProbe(
        source_doc="doc.docx",
        link_text="example",
        location_descriptor="p0.r0",
        kind=LinkKind.EXTERNAL_URL,
        target="https://",
    )
    record = check_link(probe)
    assert record.status == LinkStatus.BROKEN


def test_external_bad_scheme_is_broken() -> None:
    probe = LinkProbe(
        source_doc="doc.docx",
        link_text="x",
        location_descriptor="p0.r0",
        kind=LinkKind.EXTERNAL_URL,
        target="javascript:alert(1)",
    )
    record = check_link(probe)
    assert record.status == LinkStatus.BROKEN
    assert "scheme" in (record.error_msg or "")


# ── Internal docx anchor ────────────────────────────────────────────────


@pytest.fixture
def docx_with_bookmark(tmp_path: Path) -> Path:
    path = tmp_path / "doc.docx"
    doc = Document()
    para = doc.add_paragraph("Section 2.5.3 Clinical Overview")
    # Inject a w:bookmarkStart at the start of the paragraph
    p_element = para._p
    bookmark = p_element.makeelement(
        qn("w:bookmarkStart"),
        {qn("w:id"): "0", qn("w:name"): "section_2_5_3"},
    )
    p_element.insert(0, bookmark)
    doc.save(str(path))
    return path


def test_internal_docx_anchor_found(docx_with_bookmark: Path) -> None:
    probe = LinkProbe(
        source_doc=str(docx_with_bookmark),
        link_text="Section 2.5.3",
        location_descriptor="p0.r0",
        kind=LinkKind.INTERNAL_BOOKMARK,
        target="section_2_5_3",
        target_doc=docx_with_bookmark,
    )
    record = check_link(probe)
    assert record.status == LinkStatus.OK


def test_internal_docx_anchor_missing(docx_with_bookmark: Path) -> None:
    probe = LinkProbe(
        source_doc=str(docx_with_bookmark),
        link_text="Section 9.9.9",
        location_descriptor="p0.r0",
        kind=LinkKind.INTERNAL_BOOKMARK,
        target="ghost_anchor",
        target_doc=docx_with_bookmark,
    )
    record = check_link(probe)
    assert record.status == LinkStatus.BROKEN
    assert "not found" in (record.error_msg or "")


# ── Cross-doc ───────────────────────────────────────────────────────────


def test_cross_doc_missing_target(tmp_path: Path) -> None:
    probe = LinkProbe(
        source_doc="src.docx",
        link_text="x",
        location_descriptor="p0.r0",
        kind=LinkKind.CROSS_DOC,
        target="anchor",
        target_doc=tmp_path / "ghost.docx",
    )
    record = check_link(probe)
    assert record.status == LinkStatus.BROKEN


def test_cross_doc_without_target_doc_is_broken() -> None:
    probe = LinkProbe(
        source_doc="src.docx",
        link_text="x",
        location_descriptor="p0.r0",
        kind=LinkKind.CROSS_DOC,
        target="anchor",
        target_doc=None,
    )
    record = check_link(probe)
    assert record.status == LinkStatus.BROKEN
    assert "missing target_doc" in (record.error_msg or "")


# ── Summary ─────────────────────────────────────────────────────────────


def test_check_all_aggregates(docx_with_bookmark: Path) -> None:
    probes = [
        LinkProbe(
            source_doc=str(docx_with_bookmark),
            link_text="a",
            location_descriptor="p0.r0",
            kind=LinkKind.EXTERNAL_URL,
            target="https://example.org",
        ),
        LinkProbe(
            source_doc=str(docx_with_bookmark),
            link_text="b",
            location_descriptor="p0.r1",
            kind=LinkKind.INTERNAL_BOOKMARK,
            target="section_2_5_3",
            target_doc=docx_with_bookmark,
        ),
        LinkProbe(
            source_doc=str(docx_with_bookmark),
            link_text="c",
            location_descriptor="p0.r2",
            kind=LinkKind.INTERNAL_BOOKMARK,
            target="ghost",
            target_doc=docx_with_bookmark,
        ),
    ]
    records = check_all(probes)
    assert len(records) == 3
    statuses = {r.status for r in records}
    assert LinkStatus.OK in statuses
    assert LinkStatus.UNVERIFIED in statuses
    assert LinkStatus.BROKEN in statuses
