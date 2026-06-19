"""Layer 4 — PDF hyperlink injection.

Two flavors of link to inject:

* **External URLs** (``LinkKind.EXTERNAL_URL``) — a rectangular link
  annotation on a page that opens a browser to the target URL.
* **Internal anchors** (``LinkKind.INTERNAL_BOOKMARK``) — a link to a
  named destination inside the **same** PDF. Phase 1 creates the named
  destination on the same page (top-left), which is enough for the
  W4 smoke. Cross-document and cross-module links land in Week 6.

Design rules:

* The source PDF is never mutated; we always save a separate output.
* PyMuPDF (``fitz``) is the primary engine — its link annotation API is
  smaller and reliable. ``pikepdf`` is wired as a structural validator
  to confirm the saved PDF round-trips, but it is not required for the
  injection itself in Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import HyperlinkSpec, LinkKind, PdfLocation

_log = get_logger("injection.pdf")


class PdfInjectionError(RuntimeError):
    """Raised when a PDF link cannot be injected."""


@dataclass(frozen=True)
class PdfHyperlinkSpec:
    """A single PDF hyperlink to inject."""

    location: PdfLocation
    kind: LinkKind
    target: str  # URL for external; named-destination key for internal
    display_text: str | None = None  # informational; PDF link annots don't render text

    @classmethod
    def from_generic(cls, spec: HyperlinkSpec) -> "PdfHyperlinkSpec":
        if not isinstance(spec.location, PdfLocation):
            raise PdfInjectionError("PdfHyperlinkSpec requires a PdfLocation")
        return cls(
            location=spec.location,
            kind=spec.kind,
            target=spec.target,
            display_text=spec.display_text,
        )


class PdfLinker:
    """Inject hyperlinks into a copy of a PDF.

    Usage:

        linker = PdfLinker(source.pdf, output.pdf)
        linker.add_external_link(location, url="https://...")
        linker.add_internal_link(location, anchor="section_2_5_3")
        linker.save()
    """

    def __init__(self, source_path: Path, output_path: Path) -> None:
        source_path = Path(source_path)
        if not source_path.exists():
            raise PdfInjectionError(f"source PDF {source_path} does not exist")
        if source_path == Path(output_path):
            raise PdfInjectionError("source_path and output_path must differ")

        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise PdfInjectionError("PyMuPDF is required for PDF linking") from exc

        self._fitz = fitz
        self._source_path = source_path
        self._output_path = Path(output_path)
        self._document = fitz.open(str(source_path))
        self._pending: list[PdfHyperlinkSpec] = []
        self._named_destinations: dict[str, tuple[int, float, float]] = {}

    # ── Public API ───────────────────────────────────────────────────────

    def add_external_link(
        self,
        location: PdfLocation,
        url: str,
        display_text: str | None = None,
    ) -> None:
        self._pending.append(
            PdfHyperlinkSpec(
                location=location,
                kind=LinkKind.EXTERNAL_URL,
                target=url,
                display_text=display_text,
            )
        )

    def add_internal_link(
        self,
        location: PdfLocation,
        anchor: str,
        display_text: str | None = None,
    ) -> None:
        self._pending.append(
            PdfHyperlinkSpec(
                location=location,
                kind=LinkKind.INTERNAL_BOOKMARK,
                target=anchor,
                display_text=display_text,
            )
        )

    def add_link(self, spec: HyperlinkSpec) -> None:
        self._pending.append(PdfHyperlinkSpec.from_generic(spec))

    def declare_named_destination(
        self,
        name: str,
        page_index: int,
        x: float = 72.0,
        y: float = 72.0,
    ) -> None:
        """Register a named destination for later internal-link resolution.

        Phase 1 stores the destination in an in-memory map; the saver writes
        them as page-level link targets when an internal link references the
        same name. Phase 2 will promote these into proper PDF named-dest
        catalog entries (pikepdf).
        """
        if page_index < 0 or page_index >= self._document.page_count:
            raise PdfInjectionError(
                f"named destination {name!r}: page_index {page_index} out of range"
            )
        self._named_destinations[name] = (page_index, x, y)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ── Save / inject ────────────────────────────────────────────────────

    def save(self) -> Path:
        """Inject every pending link and write the output PDF."""
        if self._output_path.exists():
            self._output_path.unlink()
        self._output_path.parent.mkdir(parents=True, exist_ok=True)

        injected = 0
        for spec in self._pending:
            self._inject_one(spec)
            injected += 1

        self._document.save(str(self._output_path))
        self._document.close()

        _log.info(
            "pdf_injection_complete",
            source=str(self._source_path),
            output=str(self._output_path),
            links_injected=injected,
        )
        return self._output_path

    # ── Internal ─────────────────────────────────────────────────────────

    def _inject_one(self, spec: PdfHyperlinkSpec) -> None:
        if spec.location.page_index >= self._document.page_count:
            raise PdfInjectionError(
                f"page_index {spec.location.page_index} out of range "
                f"(doc has {self._document.page_count} pages)"
            )
        page = self._document.load_page(spec.location.page_index)
        rect = self._fitz.Rect(
            spec.location.x0, spec.location.y0, spec.location.x1, spec.location.y1
        )
        # Narrow the clickable rectangle to the matched phrase when we know it,
        # so a PDF link covers just the reference text — parity with the docx
        # run-level links — instead of the whole PyMuPDF span/line. Best-effort:
        # if the phrase isn't found inside the span we keep the span rectangle.
        if spec.display_text:
            try:
                hits = page.search_for(spec.display_text, clip=rect)
            except Exception:  # noqa: BLE001 — search must never break injection
                hits = []
            if hits:
                tight = hits[0]
                for h in hits[1:]:
                    tight |= h  # union of hits (covers a phrase wrapped across lines)
                if not tight.is_empty:
                    rect = tight
        if spec.kind == LinkKind.EXTERNAL_URL:
            page.insert_link(
                {"kind": self._fitz.LINK_URI, "from": rect, "uri": spec.target}
            )
        elif spec.kind == LinkKind.INTERNAL_BOOKMARK:
            dest = self._named_destinations.get(spec.target)
            if dest is None:
                # Default: link to the top of the same page so we don't fail
                # outright. The validation layer will flag the missing dest.
                target_page = spec.location.page_index
                target_x, target_y = 72.0, 72.0
                _log.warning(
                    "pdf_internal_link_unresolved",
                    anchor=spec.target,
                    page=spec.location.page_index,
                )
            else:
                target_page, target_x, target_y = dest
            page.insert_link(
                {
                    "kind": self._fitz.LINK_GOTO,
                    "from": rect,
                    "page": target_page,
                    "to": self._fitz.Point(target_x, target_y),
                }
            )
        else:
            raise PdfInjectionError(f"unsupported PDF link kind: {spec.kind!r}")
