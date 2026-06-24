"""PDF preview parity with Word: ``_read_pdf_blocks`` must surface embedded
raster images as ``type:"image"`` blocks (base64 data URI), in reading order,
so the BEFORE / AFTER / Reference View panels render figures for PDFs the same
way they already do for .docx. The _linked output always kept the images; this
only adds them to the in-app preview.
"""

from __future__ import annotations

from pathlib import Path

from hyperlink_engine.api.app import _read_pdf_blocks


def _make_pdf_with_image(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 90), "See Figure A for the anti-tumor mechanism.", fontsize=12)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 80, 60))
    pix.set_rect(pix.irect, (200, 60, 90))
    page.insert_image(fitz.Rect(72, 120, 172, 200), stream=pix.tobytes("png"))
    page.insert_text((72, 230), "Figure A. Anti-tumor mechanism of afatinib.", fontsize=10)
    doc.save(str(path))
    doc.close()


def test_pdf_preview_emits_image_blocks(tmp_path: Path) -> None:
    pdf = tmp_path / "fig.pdf"
    _make_pdf_with_image(pdf)

    blocks = _read_pdf_blocks(pdf)
    images = [b for b in blocks if b.get("type") == "image"]

    # the embedded figure surfaces as an image block with a real data URI
    assert len(images) == 1
    assert images[0]["src"].startswith("data:image/")
    assert "base64," in images[0]["src"]

    # it carries an on-page width fraction so the UI renders it at document size
    # (not the raw pixel size) — the image is ~100pt wide on a ~612pt page.
    wf = images[0]["width_frac"]
    assert 0.0 < wf <= 1.0
    assert wf < 0.5  # a small figure must NOT be sized to the full pane width

    # regression: text still extracted, and the image slots BETWEEN the two
    # text paragraphs (reading order preserved, not dumped at the end)
    kinds = [b["type"] for b in blocks]
    assert "paragraph" in kinds
    assert kinds.index("image") > kinds.index("paragraph")


def test_pdf_preview_text_only_pdf_has_no_image_blocks(tmp_path: Path) -> None:
    """A text-only PDF must not gain spurious image blocks (no false figures)."""
    import fitz

    pdf = tmp_path / "textonly.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Plain text, see Section 6 and Table 3.", fontsize=12)
    doc.save(str(pdf))
    doc.close()

    blocks = _read_pdf_blocks(pdf)
    assert [b for b in blocks if b.get("type") == "image"] == []
    assert any(b["type"] == "paragraph" for b in blocks)
