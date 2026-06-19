"""Layer 1 — PDF ingestion.

PyMuPDF (`fitz`) is the primary engine for text, links, and named destinations.
`pdfplumber` is wired as a fallback specifically for complex table extraction;
Phase 1 only exposes a hook that the parser may call when PyMuPDF returns no
text for a page (defensive coverage for scanned / image-heavy PDFs).
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
