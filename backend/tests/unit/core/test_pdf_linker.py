"""Unit tests for injection/pdf_linker.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from hyperlink_engine.core.injection.pdf_linker import PdfInjectionError, PdfLinker
from hyperlink_engine.models import PdfLocation


@pytest.fixture
def base_pdf(tmp_path: Path) -> Path:
    import fitz

    path = tmp_path / "base.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Page 1 text", fontsize=12)
    page2 = doc.new_page()
    page2.insert_text((72, 100), "Page 2 text", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _location(page: int = 0) -> PdfLocation:
    return PdfLocation(page_index=page, x0=72.0, y0=100.0, x1=200.0, y1=120.0)


def test_external_link_round_trips(base_pdf: Path, tmp_path: Path) -> None:
    import fitz

    output = tmp_path / "linked.pdf"
    linker = PdfLinker(base_pdf, output)
    linker.add_external_link(_location(), url="https://example.org/study")
    out_path = linker.save()
    assert out_path.exists()

    doc = fitz.open(str(out_path))
    try:
        links = doc.load_page(0).get_links()
        uris = [link.get("uri") for link in links if "uri" in link]
        assert "https://example.org/study" in uris
    finally:
        doc.close()


def test_internal_link_with_declared_destination(base_pdf: Path, tmp_path: Path) -> None:
    import fitz

    output = tmp_path / "internal.pdf"
    linker = PdfLinker(base_pdf, output)
    linker.declare_named_destination("section_2_5_3", page_index=1, x=72.0, y=72.0)
    linker.add_internal_link(_location(page=0), anchor="section_2_5_3")
    linker.save()

    doc = fitz.open(str(output))
    try:
        links = doc.load_page(0).get_links()
        goto_links = [link for link in links if link.get("kind") == fitz.LINK_GOTO]
        assert goto_links
        assert goto_links[0]["page"] == 1
    finally:
        doc.close()


def _span_and_word_rects(path: Path):
    """Real on-page rects for the whole phrase and a target word inside it."""
    import fitz

    doc = fitz.open(str(path))
    try:
        page = doc.load_page(0)
        span = page.search_for("Page 1 text")[0]
        word = page.search_for("text")[0]
    finally:
        doc.close()
    return span, word


def test_display_text_narrows_link_rect_to_phrase(base_pdf: Path, tmp_path: Path) -> None:
    """PLAN NINE D2 — when the matched phrase is known, the clickable rectangle
    shrinks to just that phrase instead of covering the whole span (parity with
    the run-level docx links)."""
    import fitz

    span, word = _span_and_word_rects(base_pdf)
    assert (word.x1 - word.x0) < (span.x1 - span.x0)  # sanity: the word is shorter

    output = tmp_path / "narrowed.pdf"
    linker = PdfLinker(base_pdf, output)
    # The link location is the whole span "Page 1 text"; display_text "text"
    # should shrink the clickable rect to just that word.
    loc = PdfLocation(page_index=0, x0=span.x0, y0=span.y0, x1=span.x1, y1=span.y1)
    linker.add_external_link(loc, url="https://example.org", display_text="text")
    linker.save()

    doc = fitz.open(str(output))
    try:
        rect = doc.load_page(0).get_links()[0]["from"]
        assert (rect.x1 - rect.x0) < (span.x1 - span.x0) - 1.0, "rect was not narrowed"
    finally:
        doc.close()


def test_missing_display_text_keeps_span_rect(base_pdf: Path, tmp_path: Path) -> None:
    """Without a phrase (or when it isn't found) the original span rect is kept."""
    import fitz

    span, _ = _span_and_word_rects(base_pdf)
    output = tmp_path / "wide.pdf"
    linker = PdfLinker(base_pdf, output)
    loc = PdfLocation(page_index=0, x0=span.x0, y0=span.y0, x1=span.x1, y1=span.y1)
    linker.add_external_link(loc, url="https://example.org")  # no display_text
    linker.save()

    doc = fitz.open(str(output))
    try:
        rect = doc.load_page(0).get_links()[0]["from"]
        assert abs((rect.x1 - rect.x0) - (span.x1 - span.x0)) < 1.0, "span rect changed"
    finally:
        doc.close()


def test_internal_link_without_destination_still_saves(base_pdf: Path, tmp_path: Path) -> None:
    output = tmp_path / "unresolved.pdf"
    linker = PdfLinker(base_pdf, output)
    linker.add_internal_link(_location(page=0), anchor="ghost_anchor")
    out_path = linker.save()
    assert out_path.exists()  # the validator will flag the missing dest later


def test_source_path_unchanged_after_save(base_pdf: Path, tmp_path: Path) -> None:
    output = tmp_path / "out.pdf"
    before = base_pdf.read_bytes()
    linker = PdfLinker(base_pdf, output)
    linker.add_external_link(_location(), url="https://example.org")
    linker.save()
    assert base_pdf.read_bytes() == before


def test_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(PdfInjectionError, match="does not exist"):
        PdfLinker(tmp_path / "nope.pdf", tmp_path / "out.pdf")


def test_rejects_same_source_and_output(base_pdf: Path) -> None:
    with pytest.raises(PdfInjectionError, match="must differ"):
        PdfLinker(base_pdf, base_pdf)


def test_rejects_page_index_out_of_range(base_pdf: Path, tmp_path: Path) -> None:
    linker = PdfLinker(base_pdf, tmp_path / "out.pdf")
    linker.add_external_link(
        PdfLocation(page_index=99, x0=0.0, y0=0.0, x1=10.0, y1=10.0),
        url="https://example.org",
    )
    with pytest.raises(PdfInjectionError, match="out of range"):
        linker.save()


def test_declare_named_destination_rejects_bad_page(base_pdf: Path, tmp_path: Path) -> None:
    linker = PdfLinker(base_pdf, tmp_path / "out.pdf")
    with pytest.raises(PdfInjectionError, match="out of range"):
        linker.declare_named_destination("foo", page_index=99)


def test_pending_count_tracks_additions(base_pdf: Path, tmp_path: Path) -> None:
    linker = PdfLinker(base_pdf, tmp_path / "out.pdf")
    assert linker.pending_count == 0
    linker.add_external_link(_location(), url="https://example.org")
    linker.add_internal_link(_location(page=1), anchor="x")
    assert linker.pending_count == 2
