"""Optional OCR preprocessing — turn scanned / image-only PDFs into *searchable*
PDFs so detection can find references in them.

Design (heavyweight + optional, must never regress the default path):
  * ``ocrmypdf`` is an OPTIONAL dependency and shells out to system Tesseract +
    Ghostscript. If any of those is missing, this module is a no-op.
  * It runs ONLY on PDFs with no extractable text (scanned) AND only when the
    caller opts in (``HYPERLINK_OCR_ENABLED``). Text PDFs are never touched — a
    text-length guard skips them.
  * Best-effort: any failure (missing binary, error) returns the ORIGINAL path,
    so the pipeline degrades to today's behaviour (0 links on that scan) rather
    than crashing.
  * The original file is never mutated — a new searchable copy is written into a
    per-run ``ocr/`` directory, keeping the same filename so downstream
    stem-based routing is unchanged.
"""
from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger

_log = get_logger("ingestion.ocr")

# A PDF with fewer than this many extractable characters across all pages is
# treated as scanned / image-only. A genuine text PDF is far above this.
_SCANNED_TEXT_THRESHOLD = 32


@lru_cache(maxsize=1)
def available() -> bool:
    """True when ocrmypdf + its system deps (Tesseract, Ghostscript) are usable."""
    try:
        import ocrmypdf  # noqa: F401
    except Exception:
        return False
    has_tesseract = shutil.which("tesseract") is not None
    has_ghostscript = any(
        shutil.which(b) for b in ("gs", "gswin64c", "gswin32c")
    )
    return has_tesseract and bool(has_ghostscript)


def needs_ocr(pdf_path: Path) -> bool:
    """True when a PDF has (near-)zero extractable text — i.e. it is scanned.

    Cheap PyMuPDF text sum with early-exit; a genuine text PDF returns above the
    threshold on the first page or two, so text PDFs are never sent to OCR.
    Any read failure returns False (do not OCR what we can't inspect).
    """
    try:
        import fitz
    except Exception:
        return False
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return False
    try:
        chars = 0
        for i in range(doc.page_count):
            chars += len(doc.load_page(i).get_text().strip())
            if chars >= _SCANNED_TEXT_THRESHOLD:
                return False
        return True
    except Exception:  # noqa: BLE001 — never raise from a guard
        return False
    finally:
        try:
            doc.close()
        except Exception:  # pragma: no cover
            pass


def ocr_pdf(src: Path, dst: Path, *, language: str = "eng") -> Path | None:
    """Run OCRmyPDF on ``src``, writing a searchable copy to ``dst``.

    Returns ``dst`` on success, or ``None`` on any failure (never raises).
    ``skip_text`` keeps pages that already carry text and only OCRs image pages,
    so it is safe on mixed documents and idempotent.
    """
    if not available():
        return None
    try:
        import ocrmypdf

        dst.parent.mkdir(parents=True, exist_ok=True)
        ocrmypdf.ocr(
            str(src),
            str(dst),
            language=language,
            skip_text=True,      # don't re-OCR pages that already have text
            deskew=True,         # straighten scans → better OCR accuracy
            progress_bar=False,
        )
        return dst if dst.exists() and dst.stat().st_size > 0 else None
    except Exception as exc:  # noqa: BLE001 — OCR is best-effort; fall back to original
        _log.warning("ocr_failed", src=str(src), error=str(exc))
        return None


def maybe_ocr(pdf_path: Path, out_dir: Path, *, language: str = "eng") -> Path:
    """Return a searchable copy of ``pdf_path`` when it is a scanned PDF and OCR
    is available; otherwise return the original path unchanged. Never raises.

    Idempotent: an existing searchable copy in ``out_dir`` (same filename) is
    reused instead of re-OCR'ing.
    """
    try:
        if (
            pdf_path.suffix.lower() != ".pdf"
            or not available()
            or not needs_ocr(pdf_path)
        ):
            return pdf_path
        dst = out_dir / pdf_path.name
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        result = ocr_pdf(pdf_path, dst, language=language)
        if result is not None:
            _log.info("ocr_applied", src=str(pdf_path), dst=str(result))
            return result
        return pdf_path
    except Exception as exc:  # noqa: BLE001 — never break ingestion
        _log.warning("maybe_ocr_error", src=str(pdf_path), error=str(exc))
        return pdf_path
