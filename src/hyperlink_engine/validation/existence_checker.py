"""Layer 5 — Link existence checker.

For every injected link the engine produced, verify the target actually
resolves:

* External URLs — structurally valid (scheme + host)
* Internal anchors (.docx bookmark) — bookmark exists in target document
* Named destinations (PDF) — exist in the target PDF's named-dest table
* Cross-document — target file path exists on disk

The checker is **offline** in Phase 1: it never makes network requests for
external URLs (per the on-prem mandate). Phase 3's viewer-compatibility
layer adds optional offline domain whitelist checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from docx import Document

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import LinkKind, LinkRecord, LinkStatus

_log = get_logger("validation.existence")


@dataclass(frozen=True)
class LinkProbe:
    """Minimal description of one injected link used by the checker."""

    source_doc: str
    link_text: str
    location_descriptor: str
    kind: LinkKind
    target: str
    target_doc: Path | None = None


_VALID_URL_SCHEME_RE = re.compile(r"^(https?|ftp|mailto)$", re.IGNORECASE)


def _check_external_url(target: str) -> tuple[LinkStatus, str | None]:
    if not target:
        return LinkStatus.BROKEN, "empty URL"
    parsed = urlparse(target)
    if not _VALID_URL_SCHEME_RE.fullmatch(parsed.scheme or ""):
        return LinkStatus.BROKEN, f"unsupported scheme {parsed.scheme!r}"
    if parsed.scheme.lower() in {"http", "https", "ftp"} and not parsed.netloc:
        return LinkStatus.BROKEN, "URL missing host"
    return LinkStatus.UNVERIFIED, None  # network probes are Phase 3 only


def _check_docx_anchor(docx_path: Path, anchor: str) -> tuple[LinkStatus, str | None]:
    """An internal .docx anchor is a w:bookmarkStart with the given name."""
    if not docx_path.exists():
        return LinkStatus.BROKEN, f"target document {docx_path} does not exist"
    try:
        document = Document(str(docx_path))
    except Exception as exc:  # noqa: BLE001 — file-shape issues
        return LinkStatus.BROKEN, f"could not open target docx: {exc}"
    # Iterate over the underlying XML body and look for w:bookmarkStart names.
    from docx.oxml.ns import qn

    body = document.part.element
    for bookmark in body.iter(qn("w:bookmarkStart")):
        if bookmark.get(qn("w:name")) == anchor:
            return LinkStatus.OK, None
    return LinkStatus.BROKEN, f"bookmark {anchor!r} not found in {docx_path.name}"


def _check_pdf_named_destination(pdf_path: Path, name: str) -> tuple[LinkStatus, str | None]:
    if not pdf_path.exists():
        return LinkStatus.BROKEN, f"target PDF {pdf_path} does not exist"
    try:
        import fitz
    except ImportError:
        return LinkStatus.UNVERIFIED, "PyMuPDF not available"
    try:
        document = fitz.open(str(pdf_path))
    except Exception as exc:  # noqa: BLE001
        return LinkStatus.BROKEN, f"could not open target pdf: {exc}"
    try:
        resolver = getattr(document, "resolve_names", None)
        if not callable(resolver):
            return LinkStatus.UNVERIFIED, "named destinations not available in this PyMuPDF"
        names = resolver() or {}
        if name in names:
            return LinkStatus.OK, None
        return LinkStatus.BROKEN, f"named destination {name!r} not found"
    finally:
        document.close()


def check_link(probe: LinkProbe) -> LinkRecord:
    """Run the appropriate existence check for one link."""
    if probe.kind == LinkKind.EXTERNAL_URL:
        status, err = _check_external_url(probe.target)
    elif probe.kind == LinkKind.INTERNAL_BOOKMARK:
        target_doc = probe.target_doc or Path(probe.source_doc)
        if target_doc.suffix.lower() == ".pdf":
            status, err = _check_pdf_named_destination(target_doc, probe.target)
        else:
            status, err = _check_docx_anchor(target_doc, probe.target)
    elif probe.kind in {LinkKind.CROSS_DOC, LinkKind.CROSS_MODULE}:
        if probe.target_doc is None:
            status, err = LinkStatus.BROKEN, "cross-doc link missing target_doc"
        elif not probe.target_doc.exists():
            status, err = LinkStatus.BROKEN, f"target {probe.target_doc} not found"
        else:
            # Resolve the anchor inside the target doc, if any.
            if probe.target_doc.suffix.lower() == ".pdf":
                status, err = _check_pdf_named_destination(probe.target_doc, probe.target)
            else:
                status, err = _check_docx_anchor(probe.target_doc, probe.target)
    else:
        status, err = LinkStatus.UNVERIFIED, f"unsupported link kind {probe.kind!r}"

    return LinkRecord(
        source_doc=probe.source_doc,
        link_text=probe.link_text,
        link_location_descriptor=probe.location_descriptor,
        target_doc=str(probe.target_doc) if probe.target_doc else None,
        target_anchor=probe.target,
        status=status,
        confidence=1.0 if status == LinkStatus.OK else 0.5,
        error_msg=err,
    )


def check_all(probes: list[LinkProbe]) -> list[LinkRecord]:
    """Run existence checks across a list of probes."""
    records = [check_link(probe) for probe in probes]
    _log.info(
        "existence_check_complete",
        total=len(records),
        ok=sum(1 for r in records if r.status == LinkStatus.OK),
        broken=sum(1 for r in records if r.status == LinkStatus.BROKEN),
        unverified=sum(1 for r in records if r.status == LinkStatus.UNVERIFIED),
    )
    return records
