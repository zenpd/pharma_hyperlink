"""Unit tests for ingestion/pdf_loader.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from hyperlink_engine.core.ingestion.pdf_loader import PdfLoadError, load_pdf


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Build a 2-page PDF with text + one external link using PyMuPDF."""
    import fitz

    path = tmp_path / "loader_sample.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Page 1: refer to Section 2.5.3", fontsize=12)
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Page 2: NCT46913810 is the study.", fontsize=12)
    # Add a real external link
    rect = fitz.Rect(72, 72, 300, 90)
    page2.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://example.org"})
    doc.save(str(path))
    doc.close()
    return path


def test_load_returns_handle(sample_pdf: Path) -> None:
    with load_pdf(sample_pdf) as loaded:
        assert loaded.document.page_count == 2
        assert loaded.provenance.file_size_bytes > 0
        assert len(loaded.provenance.sha256) == 64


def test_load_rejects_missing(tmp_path: Path) -> None:
    with pytest.raises(PdfLoadError, match="does not exist"):
        load_pdf(tmp_path / "nope.pdf")


def test_load_rejects_non_pdf(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.pdf"
    bogus.write_bytes(b"this is not a pdf")
    with pytest.raises(PdfLoadError, match="does not start with %PDF"):
        load_pdf(bogus)


def test_handle_closes_cleanly(sample_pdf: Path) -> None:
    loaded = load_pdf(sample_pdf)
    loaded.close()
    # Calling close again must not raise
    loaded.close()


def test_load_rejects_directory(tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    with pytest.raises(PdfLoadError, match="is not a file"):
        load_pdf(sub)


def test_pdfplumber_fallback_returns_text(sample_pdf: Path) -> None:
    from hyperlink_engine.core.ingestion.pdf_loader import page_text_via_pdfplumber

    text = page_text_via_pdfplumber(sample_pdf, page_index=0)
    assert "Page 1" in text


def test_pdfplumber_fallback_out_of_range(sample_pdf: Path) -> None:
    from hyperlink_engine.core.ingestion.pdf_loader import page_text_via_pdfplumber

    with pytest.raises(PdfLoadError, match="out of range"):
        page_text_via_pdfplumber(sample_pdf, page_index=99)
