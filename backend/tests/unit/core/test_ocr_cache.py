"""Tests for the machine-global, content-addressed OCR cache in ``maybe_ocr``.

The cache is opt-in via ``cache_root`` and must:
  (a) skip the expensive OCR compute when a content+language-identical scan is
      already cached, and materialize a byte-identical copy into the per-run dir;
  (b) key on the OCR *language* so switching languages never serves the wrong one;
  (c) refuse to serve a truncated/corrupt cached PDF and self-heal by re-OCR'ing;
  (d) degrade to a normal per-run OCR when ``cache_root`` is None.
None of this needs a real Tesseract — ``available``/``needs_ocr`` are forced and
``ocr_pdf`` is faked to emit a *valid* 1-page PDF (so the integrity check passes).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hyperlink_engine.core.ingestion import ocr_preprocess as op


def _write_valid_pdf(path: Path) -> None:
    import fitz

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()


@pytest.fixture
def _forced_ocr(monkeypatch):
    """Make maybe_ocr believe OCR is available and every PDF is scanned."""
    monkeypatch.setattr(op, "available", lambda: True)
    monkeypatch.setattr(op, "needs_ocr", lambda p: True)


def _fake_ocr(calls: list):
    """Fake ``ocr_pdf`` that records (src, dst, language) and writes a VALID PDF."""

    def _run(src: Path, dst: Path, *, language: str = "eng") -> Path | None:
        calls.append((Path(src), Path(dst), language))
        _write_valid_pdf(Path(dst))
        return Path(dst)

    return _run


def _make_scan(tmp_path: Path, name: str = "scan.pdf", data: bytes = b"same-bytes") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_content_sha_is_identity_by_bytes(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"hello world")
    b = tmp_path / "b.pdf"; b.write_bytes(b"hello world")  # different name, same bytes
    assert op._content_sha(a) == op._content_sha(b)


def test_is_valid_pdf_accepts_real_rejects_garbage(tmp_path):
    good = tmp_path / "good.pdf"; _write_valid_pdf(good)
    bad = tmp_path / "bad.pdf"; bad.write_bytes(b"not a pdf at all")
    assert op._is_valid_pdf(good) is True
    assert op._is_valid_pdf(bad) is False


def test_cache_root_computes_once_then_reuses(tmp_path, monkeypatch, _forced_ocr):
    calls: list = []
    monkeypatch.setattr(op, "ocr_pdf", _fake_ocr(calls))
    cache_root = tmp_path / "ocr_cache"
    src = _make_scan(tmp_path)

    r1 = op.maybe_ocr(src, tmp_path / "run1" / "ocr", cache_root=cache_root)
    r2 = op.maybe_ocr(src, tmp_path / "run2" / "ocr", cache_root=cache_root)

    assert r1 == tmp_path / "run1" / "ocr" / "scan.pdf" and r1.exists()
    assert r2 == tmp_path / "run2" / "ocr" / "scan.pdf" and r2.exists()
    assert len(calls) == 1  # OCR compute ran once; 2nd run copied from cache
    assert cache_root in calls[0][1].parents


def test_different_language_is_a_separate_cache_entry(tmp_path, monkeypatch, _forced_ocr):
    """Switching HYPERLINK_OCR_LANGUAGE must NOT serve the other language's OCR."""
    calls: list = []
    monkeypatch.setattr(op, "ocr_pdf", _fake_ocr(calls))
    cache_root = tmp_path / "ocr_cache"
    src = _make_scan(tmp_path)

    op.maybe_ocr(src, tmp_path / "eng" / "ocr", cache_root=cache_root, language="eng")
    op.maybe_ocr(src, tmp_path / "deu" / "ocr", cache_root=cache_root, language="deu")

    assert len(calls) == 2  # re-OCR'd for the new language, not reused
    langs = {c[2] for c in calls}
    assert langs == {"eng", "deu"}
    # distinct cache subfolders per language
    entries = sorted(p for p in cache_root.rglob("scan.pdf"))
    assert len(entries) == 2


def test_corrupt_cache_entry_self_heals(tmp_path, monkeypatch, _forced_ocr):
    """A truncated/corrupt cached PDF is re-OCR'd, never served as-is."""
    calls: list = []
    monkeypatch.setattr(op, "ocr_pdf", _fake_ocr(calls))
    cache_root = tmp_path / "ocr_cache"
    src = _make_scan(tmp_path)

    op.maybe_ocr(src, tmp_path / "run1" / "ocr", cache_root=cache_root)  # populates cache
    assert len(calls) == 1
    cached = next(cache_root.rglob("scan.pdf"))
    cached.write_bytes(b"%PDF-truncated-garbage")  # corrupt it (size>0 but invalid)

    r2 = op.maybe_ocr(src, tmp_path / "run2" / "ocr", cache_root=cache_root)
    assert len(calls) == 2  # invalid entry rejected -> re-OCR'd (self-heal)
    assert op._is_valid_pdf(r2)  # the served result is a valid PDF


def test_no_cache_root_ocrs_per_run(tmp_path, monkeypatch, _forced_ocr):
    calls: list = []
    monkeypatch.setattr(op, "ocr_pdf", _fake_ocr(calls))
    src = _make_scan(tmp_path)

    op.maybe_ocr(src, tmp_path / "run1" / "ocr")  # legacy: no cache_root
    op.maybe_ocr(src, tmp_path / "run2" / "ocr")

    assert len(calls) == 2  # legacy behavior: OCR recomputed per run
