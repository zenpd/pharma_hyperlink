"""Layer 1 — PDF ingestion.

PyMuPDF (`fitz`) is the primary engine for text, links, and named destinations.
`pdfplumber` is wired as a fallback specifically for complex table extraction;
it is called when PyMuPDF returns no text for a page (defensive coverage for
scanned / image-heavy PDFs).

Layer 1.5 — OCR:
When both PyMuPDF and pdfplumber return empty text (scanned/image-only page),
``page_text_via_ocr()`` renders the page to an image and runs Tesseract or
EasyOCR. The OCR path is gated by ``HYPERLINK_OCR_ENABLED=true`` and is
completely optional — missing OCR deps are logged and silently skipped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import DocumentProvenance

if TYPE_CHECKING:  # pragma: no cover — type hints only
    import fitz  # PyMuPDF

_log = get_logger("ingestion.pdf")

_BUFFER_SIZE = 1024 * 1024


class PdfLoadError(RuntimeError):
    """Raised when a PDF cannot be opened or is structurally invalid."""


@dataclass
class LoadedPdf:
    """Opened-but-not-parsed PDF handle.

    Holds the live PyMuPDF document and the provenance record.  Callers must
    call ``close()`` (or use ``with``) so file handles do not leak.
    """

    document: "fitz.Document"
    provenance: DocumentProvenance

    def __enter__(self) -> "LoadedPdf":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def close(self) -> None:
        try:
            self.document.close()
        except Exception:  # pragma: no cover — best-effort cleanup
            pass


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_BUFFER_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _peek_pdf_header(path: Path) -> None:
    with path.open("rb") as fh:
        head = fh.read(5)
    if head[:4] != b"%PDF":
        raise PdfLoadError(f"{path} does not start with %PDF — not a PDF file")


def load_pdf(path: Path) -> LoadedPdf:
    """Open a PDF for read-only parsing.  Caller owns the returned handle."""
    path = Path(path)
    if not path.exists():
        raise PdfLoadError(f"{path} does not exist")
    if not path.is_file():
        raise PdfLoadError(f"{path} is not a file")
    _peek_pdf_header(path)

    import fitz  # imported lazily — keep startup fast and avoid hard dep at import time

    sha = _sha256_of(path)
    size = path.stat().st_size
    provenance = DocumentProvenance(source_path=path, sha256=sha, file_size_bytes=size)

    try:
        document = fitz.open(str(path))
    except Exception as exc:
        raise PdfLoadError(f"PyMuPDF could not open {path}: {exc}") from exc

    _log.info(
        "pdf_loaded",
        path=str(path),
        sha256=sha,
        size_bytes=size,
        page_count=document.page_count,
    )
    return LoadedPdf(document=document, provenance=provenance)


def page_text_via_pdfplumber(path: Path, page_index: int) -> str:
    """Pdfplumber fallback for pages where PyMuPDF extraction is empty.

    Only used by the parser when PyMuPDF returns nothing on a page — heavier
    and slower, so we never call it unconditionally.
    """
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        if page_index >= len(pdf.pages):
            raise PdfLoadError(f"page_index {page_index} out of range for {path}")
        return pdf.pages[page_index].extract_text() or ""


def page_words_via_ocr(
    page: "fitz.Document",
    page_index: int,
    *,
    engine: str = "tesseract",
    language: str = "eng",
    dpi: int = 300,
    min_confidence: float = 0.5,
) -> "Any":
    """OCR fallback returning per-word pixel bboxes (OcrPageResultWithWords).

    Returns an OcrPageResultWithWords where each word carries a pixel-space
    bbox; the caller converts to PDF points via ``x_pt = x_px * 72.0 / dpi``.
    Falls back to an empty result on any error.
    """
    from hyperlink_engine.core.ingestion.ocr_processor import (
        OcrError,
        OcrNotAvailableError,
        OcrPageResultWithWords,
        ocr_pdf_page_words,
    )

    try:
        return ocr_pdf_page_words(
            page,
            page_index,
            engine=engine,
            language=language,
            dpi=dpi,
            min_confidence=min_confidence,
        )
    except OcrNotAvailableError as exc:
        _log.warning("ocr_not_available", page_index=page_index, reason=str(exc))
    except OcrError as exc:
        _log.warning("ocr_failed", page_index=page_index, reason=str(exc))
    except Exception as exc:  # pragma: no cover
        _log.error("ocr_unexpected_error", page_index=page_index, error=str(exc))
    return OcrPageResultWithWords(page_index=page_index, text="", confidence=0.0, engine=engine)


def page_text_via_ocr(
    page: "fitz.Document",
    page_index: int,
    *,
    engine: str = "tesseract",
    language: str = "eng",
    dpi: int = 300,
    min_confidence: float = 0.5,
) -> str:
    """OCR fallback — Layer 1.5.

    Renders a fitz.Page to an image (at ``dpi`` DPI) and runs the selected OCR
    engine. Returns the extracted text, or an empty string if OCR is unavailable
    or produces no output. This is intentionally tolerant — missing OCR deps are
    logged as warnings and never raise to the caller.

    Args:
        page:           A live fitz.Page object (not the Document).
        page_index:     0-based page index (for logging only).
        engine:         ``"tesseract"`` or ``"easyocr"``.
        language:       Tesseract lang code (``"eng"``) or comma-separated
                        EasyOCR languages (``"en,fr"``).
        dpi:            Render resolution. 300 is standard for regulatory docs.
        min_confidence: Discard OCR words below this confidence (0.0 – 1.0).
    """
    from hyperlink_engine.core.ingestion.ocr_processor import (
        OcrError,
        OcrNotAvailableError,
        ocr_pdf_page,
    )

    try:
        result = ocr_pdf_page(
            page,
            page_index,
            engine=engine,
            language=language,
            dpi=dpi,
            min_confidence=min_confidence,
        )
        return result.text
    except OcrNotAvailableError as exc:
        _log.warning("ocr_not_available", page_index=page_index, reason=str(exc))
        return ""
    except OcrError as exc:
        _log.warning("ocr_failed", page_index=page_index, reason=str(exc))
        return ""
    except Exception as exc:  # pragma: no cover — unexpected engine failure
        _log.error("ocr_unexpected_error", page_index=page_index, error=str(exc))
        return ""
