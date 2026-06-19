"""Layer 1 — Word (.docx) ingestion.

The loader is the **only** module that touches the filesystem for .docx files.
It captures provenance (sha256, file size, ingest time), validates the file is
a real OOXML package, and hands a read-only handle to the parser. The original
file is never mutated; the injection layer always writes to a separate output
path.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocxObject

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import DocumentProvenance

_log = get_logger("ingestion.docx")

_BUFFER_SIZE = 1024 * 1024  # 1 MiB streaming hash buffer


class DocxLoadError(RuntimeError):
    """Raised when a .docx file cannot be opened or is structurally invalid."""


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_BUFFER_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_ooxml(path: Path) -> None:
    """Cheap sanity check — a valid .docx is a zip with /word/document.xml."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise DocxLoadError(f"{path} is not a valid .docx (bad zip): {exc}") from exc
    if "word/document.xml" not in names:
        raise DocxLoadError(f"{path} is missing word/document.xml — not a Word OOXML package")


def load_docx(path: Path) -> tuple[DocxObject, DocumentProvenance]:
    """Open a .docx file and return (python-docx Document, provenance).

    The Document object is read-only by convention here — callers must not
    mutate it; if a write is needed, route through the injection layer which
    always writes to a separate output path.
    """
    path = Path(path)
    if not path.exists():
        raise DocxLoadError(f"{path} does not exist")
    if not path.is_file():
        raise DocxLoadError(f"{path} is not a file")
    _validate_ooxml(path)

    sha = _sha256_of(path)
    size = path.stat().st_size
    provenance = DocumentProvenance(source_path=path, sha256=sha, file_size_bytes=size)

    try:
        document = Document(str(path))
    except Exception as exc:  # python-docx raises a few exception shapes
        raise DocxLoadError(f"python-docx could not open {path}: {exc}") from exc

    _log.info(
        "docx_loaded",
        path=str(path),
        sha256=sha,
        size_bytes=size,
        paragraphs=len(document.paragraphs),
    )
    return document, provenance
