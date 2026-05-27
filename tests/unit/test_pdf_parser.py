"""Unit tests for parsing/pdf_parser.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from hyperlink_engine.parsing.pdf_parser import parse_pdf


@pytest.fixture
def linked_pdf(tmp_path: Path) -> Path:
    """Build a small PDF with text, a bookmark, and an external link."""
    import fitz

    path = tmp_path / "linked.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Section 2.5 Clinical Overview", fontsize=14)
    page1.insert_text((72, 120), "See Table 14.2.1.1 below.", fontsize=11)

    page2 = doc.new_page()
    page2.insert_text((72, 72), "NCT46913810 registered.", fontsize=11)
    link_rect = fitz.Rect(72, 72, 280, 90)
    page2.insert_link({"kind": fitz.LINK_URI, "from": link_rect, "uri": "https://clinicaltrials.gov"})

    # Add a 2-entry table of contents
    doc.set_toc([[1, "Section 2.5", 1], [1, "Registration", 2]])
    doc.save(str(path))
    doc.close()
    return path


def test_parse_extracts_pages_and_spans(linked_pdf: Path) -> None:
    parsed = parse_pdf(linked_pdf)
    assert parsed.page_count == 2
    assert len(parsed.pages) == 2

    page1 = parsed.pages[0]
    assert page1.blocks, "expected blocks on page 1"
    combined = " ".join(block.text for block in page1.blocks)
    assert "Section 2.5" in combined
    assert "Table 14.2.1.1" in combined


def test_parse_extracts_existing_links(linked_pdf: Path) -> None:
    parsed = parse_pdf(linked_pdf)
    assert parsed.existing_links, "expected at least one external link"
    uri_links = [link for link in parsed.existing_links if link.uri]
    assert any("clinicaltrials.gov" in (link.uri or "") for link in uri_links)


def test_parse_extracts_bookmarks(linked_pdf: Path) -> None:
    parsed = parse_pdf(linked_pdf)
    titles = [title for _, title, _ in parsed.bookmarks]
    assert "Section 2.5" in titles
    assert "Registration" in titles
    # Pages normalized to 0-based
    for _, _, page in parsed.bookmarks:
        assert page >= 0


def test_span_bbox_is_within_page(linked_pdf: Path) -> None:
    parsed = parse_pdf(linked_pdf)
    page = parsed.pages[0]
    for block in page.blocks:
        for span in block.spans:
            x0, y0, x1, y1 = span.bbox
            assert 0 <= x0 <= x1 <= page.width + 1
            assert 0 <= y0 <= y1 <= page.height + 1


def test_int_to_hex_helper() -> None:
    from hyperlink_engine.parsing.pdf_parser import _int_to_hex

    assert _int_to_hex(0) == "000000"
    assert _int_to_hex(0xFF0000) == "FF0000"
    assert _int_to_hex(None) is None
    assert _int_to_hex("not-an-int") is None  # type: ignore[arg-type]


def test_parse_handles_blank_page(tmp_path: Path) -> None:
    """A blank page (no text, no image) is the realistic 'no-text' case for the parser."""
    import fitz

    path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page
    doc.save(str(path))
    doc.close()

    parsed = parse_pdf(path)
    assert parsed.page_count == 1
    # Blank page yields zero text blocks; the pdfplumber fallback also returns ""
    assert parsed.pages[0].blocks == []
