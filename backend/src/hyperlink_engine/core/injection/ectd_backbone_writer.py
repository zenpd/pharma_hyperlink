"""Layer 4 — eCTD backbone (index.xml) writer for Phase 2 W6.1.

Per ADR-0001, the engine never mutates source artefacts. The writer takes
an existing ``index.xml``, re-parses it, applies a queue of structured
edits (cross-module ``leaf-xref`` records, primarily) and emits a new
file at a separate output path.

Why we re-parse instead of mutating the in-memory ``BackboneSnapshot``:
``BackboneSnapshot`` is intentionally schema-agnostic and loses element
ordering / namespace declarations / comments. To round-trip cleanly
(important for diffability in regulatory submissions), we must work on
the original lxml tree.

The writer is intentionally narrow — it only knows about the edits the
pipeline needs today (``add_leaf_xref``). Future regional-specific edits
(``add_sequence_element``, etc.) plug in via the same ``BackboneEdit``
queue model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lxml import etree

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.ingestion.ectd_loader import _local_name

_log = get_logger("injection.ectd_writer")

_XLINK_NS = "http://www.w3.org/1999/xlink"


class BackboneWriteError(RuntimeError):
    """Raised when the writer cannot apply an edit or write the output file."""


@dataclass(frozen=True)
class LeafXrefEdit:
    """Add a ``<leaf-xref>`` element inside an existing ``<leaf>``.

    ICH eCTD v3.2 represents an outbound reference from one leaf to
    another as a child element with ``xlink:href`` pointing at the target
    leaf's relative path (optionally with an anchor fragment).
    """

    source_leaf_id: str
    target_href: str
    anchor: str | None = None


@dataclass
class BackboneEditPlan:
    """Mutable queue of edits the writer will apply when ``save()`` runs."""

    leaf_xrefs: list[LeafXrefEdit] = field(default_factory=list)

    def add_leaf_xref(
        self,
        source_leaf_id: str,
        target_href: str,
        anchor: str | None = None,
    ) -> None:
        self.leaf_xrefs.append(
            LeafXrefEdit(
                source_leaf_id=source_leaf_id,
                target_href=target_href,
                anchor=anchor,
            )
        )

    def __len__(self) -> int:
        return len(self.leaf_xrefs)

    def __bool__(self) -> bool:
        return bool(self.leaf_xrefs)

    def extend(self, edits: Iterable[LeafXrefEdit]) -> None:
        self.leaf_xrefs.extend(edits)


class BackboneWriter:
    """Reads a backbone XML file, applies edits, writes a new file.

    Workflow::

        writer = BackboneWriter(source_path, output_path)
        plan = BackboneEditPlan()
        plan.add_leaf_xref("leaf-25", "m5/5-3-1-bio-stud-rep/study-001.docx",
                           anchor="section_5_3_1")
        writer.apply(plan)
        writer.save()
    """

    def __init__(self, source_path: Path, output_path: Path) -> None:
        self.source_path = Path(source_path)
        self.output_path = Path(output_path)
        if not self.source_path.exists():
            raise BackboneWriteError(f"source backbone {self.source_path} does not exist")
        try:
            parser = etree.XMLParser(
                resolve_entities=False, no_network=True, load_dtd=False, remove_blank_text=False
            )
            self._tree = etree.parse(str(self.source_path), parser=parser)
        except etree.XMLSyntaxError as exc:
            raise BackboneWriteError(f"could not parse {self.source_path}: {exc}") from exc

    # ── Public API ──────────────────────────────────────────────────────

    def apply(self, plan: BackboneEditPlan) -> int:
        """Apply every edit in the plan. Returns the count applied."""
        applied = 0
        for edit in plan.leaf_xrefs:
            if self._apply_leaf_xref(edit):
                applied += 1
        _log.info(
            "ectd_backbone_edits_applied",
            source=str(self.source_path),
            requested=len(plan),
            applied=applied,
        )
        return applied

    def save(self) -> Path:
        """Serialize the modified tree to ``output_path`` and return it."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._tree.write(
            str(self.output_path),
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=True,
        )
        _log.info("ectd_backbone_saved", output=str(self.output_path))
        return self.output_path

    # ── Internals ───────────────────────────────────────────────────────

    def _find_leaf_by_id(self, leaf_id: str) -> etree._Element | None:
        for element in self._tree.iter():
            if _local_name(element.tag).lower() == "leaf":
                if element.attrib.get("ID") == leaf_id:
                    return element
        return None

    def _apply_leaf_xref(self, edit: LeafXrefEdit) -> bool:
        leaf = self._find_leaf_by_id(edit.source_leaf_id)
        if leaf is None:
            _log.warning(
                "ectd_leaf_xref_source_missing",
                source_leaf_id=edit.source_leaf_id,
            )
            return False
        href = edit.target_href
        if edit.anchor:
            href = f"{edit.target_href}#{edit.anchor}"
        # Skip if an identical xref already exists — round-trip idempotent.
        for existing in leaf:
            if _local_name(existing.tag).lower() != "leaf-xref":
                continue
            existing_href = existing.attrib.get(f"{{{_XLINK_NS}}}href") or existing.attrib.get("href")
            if existing_href == href:
                return False
        # Build the new <leaf-xref> in the same namespace as the parent leaf
        # so the serialized XML stays consistent.
        nsmap = leaf.nsmap or {}
        parent_ns = leaf.tag.split("}")[0].lstrip("{") if "}" in leaf.tag else None
        xref_tag = f"{{{parent_ns}}}leaf-xref" if parent_ns else "leaf-xref"
        xref = etree.SubElement(leaf, xref_tag, nsmap=nsmap if not parent_ns else None)
        xref.set(f"{{{_XLINK_NS}}}href", href)
        return True
