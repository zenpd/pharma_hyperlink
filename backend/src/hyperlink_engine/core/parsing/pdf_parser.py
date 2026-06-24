"""Layer 2 — PDF parsing.

Builds a typed `PdfDocument` from a loaded PyMuPDF handle:

* pages → blocks → spans → tokens (PyMuPDF's `get_text("dict")` shape)
* bookmarks (table of contents)
* existing link annotations
* named destinations
* per-span color (RGB) + bbox + font + size

The parser is read-only; it never writes back to the PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.ingestion.pdf_loader import (
    LoadedPdf,
    load_pdf,
    page_text_via_pdfplumber,
)
from hyperlink_engine.models import (
    PdfBlock,
    PdfDocument,
    PdfLinkAnnotation,
    PdfPage,
    PdfSpan,
)

if TYPE_CHECKING:  # pragma: no cover
    import fitz

_log = get_logger("parsing.pdf")


def _int_to_hex(color_int: int) -> str | None:
    """PyMuPDF stores span colors as a packed integer; convert to RRGGBB hex."""
    if color_int is None:
        return None
    try:
        return f"{int(color_int) & 0xFFFFFF:06X}"
    except (TypeError, ValueError):
        return None


def _parse_block(block: dict, block_index: int) -> PdfBlock:
    spans_out: list[PdfSpan] = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            bbox = tuple(span.get("bbox", (0.0, 0.0, 0.0, 0.0)))
            spans_out.append(
                PdfSpan(
                    text=span.get("text", ""),
                    bbox=bbox,  # type: ignore[arg-type]
                    font_name=span.get("font"),
                    font_size_pt=float(span.get("size", 0.0)) or None,
                    color_rgb=_int_to_hex(span.get("color")),
                )
            )
    return PdfBlock(
        block_index=block_index,
        bbox=tuple(block.get("bbox", (0.0, 0.0, 0.0, 0.0))),  # type: ignore[arg-type]
        spans=spans_out,
    )


def _parse_links(document: "fitz.Document", page: "fitz.Page", page_index: int) -> list[PdfLinkAnnotation]:
    """Collect every link annotation on a page in our typed shape."""
    annotations: list[PdfLinkAnnotation] = []
    for link in page.get_links():
        bbox = link.get("from")
        if bbox is None:
            continue
        rect = (float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1))
        uri = link.get("uri")
        target_page: int | None = None
        named_dest: str | None = link.get("nameddest")
        if "page" in link and link["page"] is not None and link["page"] >= 0:
            target_page = int(link["page"])
        annotations.append(
            PdfLinkAnnotation(
                page_index=page_index,
                bbox=rect,
                uri=uri,
                target_page=target_page,
                named_dest=named_dest,
            )
        )
    return annotations


def _parse_named_destinations(document: "fitz.Document") -> dict[str, int]:
    """Best-effort dump of named destinations -> page index.

    PyMuPDF's API for named destinations evolved across versions; we probe
    a few entry points and fall back to an empty dict if none are available.
    """
    out: dict[str, int] = {}
    resolver = getattr(document, "resolve_names", None)
    if callable(resolver):
        try:
            for name, dest in resolver().items():
                page = dest.get("page") if isinstance(dest, dict) else None
                if isinstance(page, int) and page >= 0:
                    out[str(name)] = page
        except Exception:  # pragma: no cover — robustness against API drift
            out.clear()
    return out


def _parse_toc(document: "fitz.Document") -> list[tuple[int, str, int]]:
    """PyMuPDF returns ToC as [[level, title, page], …]; PDF pages are 1-indexed."""
    try:
        raw = document.get_toc(simple=True) or []
    except Exception:  # pragma: no cover
        return []
    parsed: list[tuple[int, str, int]] = []
    for entry in raw:
        if len(entry) < 3:
            continue
        level = int(entry[0])
        title = str(entry[1])
        # ToC pages are 1-based in PyMuPDF; normalize to 0-based for parity with pages list.
        page = max(int(entry[2]) - 1, 0)
        parsed.append((level, title, page))
    return parsed


def parse_pdf_document(loaded: LoadedPdf) -> PdfDocument:
    """Project a loaded PyMuPDF document into our typed PdfDocument shape."""
    document = loaded.document

    pages_out: list[PdfPage] = []
    existing_links: list[PdfLinkAnnotation] = []

    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        page_dict = page.get_text("dict")
        blocks_out: list[PdfBlock] = []
        for b_idx, block in enumerate(page_dict.get("blocks", [])):
            # PyMuPDF marks image blocks with "type": 1; we keep only text blocks (type 0).
            if block.get("type", 0) != 0:
                continue
            blocks_out.append(_parse_block(block, b_idx))

        # Fallback: if PyMuPDF found no text on this page, try pdfplumber for the raw text.
        if not blocks_out:
            try:
                fallback_text = page_text_via_pdfplumber(loaded.provenance.source_path, page_index)
            except Exception:  # pragma: no cover — fallback failures must not crash parsing
                fallback_text = ""
            if fallback_text.strip():
                blocks_out.append(
                    PdfBlock(
                        block_index=0,
                        bbox=(0.0, 0.0, float(page.rect.width), float(page.rect.height)),
                        spans=[
                            PdfSpan(
                                text=fallback_text,
                                bbox=(0.0, 0.0, float(page.rect.width), float(page.rect.height)),
                            )
                        ],
                    )
                )

        pages_out.append(
            PdfPage(
                page_index=page_index,
                width=float(page.rect.width),
                height=float(page.rect.height),
                blocks=blocks_out,
            )
        )
        existing_links.extend(_parse_links(document, page, page_index))

    # PDF/A is hinted by metadata flags; we treat the presence of the XMP marker
    # as best-effort signal. Phase 3 viewer compatibility layer does the rigorous check.
    fmt = (document.metadata.get("format", "") if document.metadata else "") or ""
    is_pdf_a = fmt.strip().upper().startswith("PDF/A")

    parsed = PdfDocument(
        provenance=loaded.provenance,
        page_count=document.page_count,
        pages=pages_out,
        bookmarks=_parse_toc(document),
        existing_links=existing_links,
        named_destinations=_parse_named_destinations(document),
        is_pdf_a=is_pdf_a,
    )

    _log.info(
        "pdf_parsed",
        path=str(loaded.provenance.source_path),
        pages=parsed.page_count,
        existing_links=len(parsed.existing_links),
        bookmarks=len(parsed.bookmarks),
        named_dests=len(parsed.named_destinations),
    )
    return parsed


def parse_pdf(path: Path) -> PdfDocument:
    """Convenience: load + parse + close in one call."""
    with load_pdf(Path(path)) as loaded:
        return parse_pdf_document(loaded)
