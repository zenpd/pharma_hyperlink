"""Tests for the optional OCR preprocessing (scanned PDF -> searchable PDF).

The real OCR stack (ocrmypdf + Tesseract + Ghostscript) is optional and usually
absent in CI, so these tests exercise the GATING and FALL-BACK logic — the part
that guarantees zero regression when OCR is off/unavailable — and stub the actual
OCR call. No dependency on ocrmypdf being installed.
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF is a core dependency

from hyperlink_engine.core.ingestion import ocr_preprocess as ocr


# ── fixtures (built with PyMuPDF, no external deps) ─────────────────────────

def _text_pdf(path, text="Section 5.3 references Table 14.1.1 and Appendix A here."):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


def _blank_pdf(path, pages=2):
    """A PDF with pages but NO extractable text — mimics a scanned/image-only doc."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


# ── needs_ocr ───────────────────────────────────────────────────────────────

def test_needs_ocr_true_for_textless_pdf(tmp_path):
    assert ocr.needs_ocr(_blank_pdf(tmp_path / "scan.pdf")) is True


def test_needs_ocr_false_for_text_pdf(tmp_path):
    assert ocr.needs_ocr(_text_pdf(tmp_path / "text.pdf")) is False


def test_needs_ocr_false_on_unreadable(tmp_path):
    p = tmp_path / "nope.pdf"
    p.write_bytes(b"not a pdf")
    assert ocr.needs_ocr(p) is False


# ── maybe_ocr: gating + fall-back (the no-regression guarantees) ────────────

def test_maybe_ocr_skips_text_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    p = _text_pdf(tmp_path / "text.pdf")
    assert ocr.maybe_ocr(p, tmp_path / "ocr") == p  # text PDF never OCR'd


def test_maybe_ocr_skips_non_pdf(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hello")
    assert ocr.maybe_ocr(p, tmp_path / "ocr") == p


def test_maybe_ocr_falls_back_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    p = _blank_pdf(tmp_path / "scan.pdf")
    assert ocr.maybe_ocr(p, tmp_path / "ocr") == p  # scanned but OCR off -> original


def test_maybe_ocr_falls_back_when_ocr_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pdf", lambda *a, **k: None)  # simulate OCR failure
    p = _blank_pdf(tmp_path / "scan.pdf")
    assert ocr.maybe_ocr(p, tmp_path / "ocr") == p


# ── maybe_ocr: success + idempotency (stubbed OCR) ─────────────────────────

def test_maybe_ocr_returns_searchable_copy_on_success(tmp_path, monkeypatch):
    out = tmp_path / "ocr"

    def _fake_ocr_pdf(src, dst, *, language="eng"):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"%PDF-1.7 fake searchable")
        return dst

    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pdf", _fake_ocr_pdf)
    p = _blank_pdf(tmp_path / "scan.pdf")
    result = ocr.maybe_ocr(p, out)
    assert result == out / "scan.pdf"   # same filename, in the ocr/ dir
    assert result.exists()


def test_maybe_ocr_reuses_existing_copy(tmp_path, monkeypatch):
    out = tmp_path / "ocr"
    out.mkdir()
    (out / "scan.pdf").write_bytes(b"%PDF already searchable")
    calls = {"n": 0}

    def _fake_ocr_pdf(src, dst, *, language="eng"):
        calls["n"] += 1
        return dst

    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_pdf", _fake_ocr_pdf)
    p = _blank_pdf(tmp_path / "scan.pdf")
    assert ocr.maybe_ocr(p, out) == out / "scan.pdf"
    assert calls["n"] == 0  # existing copy reused, no re-OCR


# ── ocr_pdf guard ────────────────────────────────────────────────────────────

def test_ocr_pdf_returns_none_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    assert ocr.ocr_pdf(tmp_path / "a.pdf", tmp_path / "b.pdf") is None


# ── node_load_dossier: default (OCR off) is byte-identical ──────────────────

def test_node_load_dossier_unchanged_when_ocr_off(tmp_path, monkeypatch):
    """With ocr_enabled=False (default), records carry no OCR keys."""
    from hyperlink_engine.orchestration.nodes import node_load_dossier
    from hyperlink_engine.orchestration.state import PipelineState, run_store

    pdf = _blank_pdf(tmp_path / "scan.pdf")
    out = tmp_path / "out"
    state = PipelineState.new([pdf], out, "DOS-TEST")
    run_store.create(state)
    state = node_load_dossier(state)

    rec = state["ingest_records"][0]
    assert rec["source_path"] == str(pdf)          # original, not OCR'd
    assert "ocr_applied" not in rec                 # no new keys on the default path
    assert "original_source_path" not in rec


# ── integration: real OCR round-trip (runs only where the stack is installed) ─

def test_ocr_roundtrip_recovers_text_when_stack_available(tmp_path):
    """End-to-end: a genuinely scanned (rasterized) PDF -> maybe_ocr -> text back.

    Runs the REAL OCR only where ocrmypdf + Tesseract + Ghostscript are installed
    (e.g. the office laptop); skipped everywhere else so CI stays green without the
    heavyweight stack.
    """
    if not ocr.available():
        pytest.skip("OCR stack (ocrmypdf + Tesseract + Ghostscript) not installed")

    # 1. a legible text page
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Section 5.3 and Table 14.1 per Appendix A.", fontsize=24)
    src = tmp_path / "text.pdf"
    doc.save(str(src))
    doc.close()

    # 2. rasterize -> scanned (image-only) PDF at 200 DPI so OCR can read it
    d = fitz.open(str(src))
    o = fitz.open()
    m = fitz.Matrix(200 / 72, 200 / 72)
    for i in range(d.page_count):
        pg = d.load_page(i)
        pix = pg.get_pixmap(matrix=m)
        npg = o.new_page(width=pg.rect.width, height=pg.rect.height)
        npg.insert_image(pg.rect, pixmap=pix)
    scanned = tmp_path / "scanned.pdf"
    o.save(str(scanned))
    o.close()
    d.close()

    assert ocr.needs_ocr(scanned) is True   # scanned = no text layer

    # 3. OCR -> searchable copy with recovered text
    out = ocr.maybe_ocr(scanned, tmp_path / "ocrout")
    assert out != scanned
    rec = fitz.open(str(out))
    recovered = "".join(rec.load_page(i).get_text() for i in range(rec.page_count))
    rec.close()
    assert len(recovered.strip()) > 10   # OCR pulled real text back out
