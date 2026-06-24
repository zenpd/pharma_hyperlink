"""Layer 4 — eCTD cross-reference injection.

Phase 1 shipped the in-module scaffold (Module 2 ↔ Module 2 subsections).
Phase 2 W6.1 fills in cross-module link generation (Module 2.5.3 →
Module 5.3.1 CSR etc.) by combining:

  * the backbone graph (W5.2 — resolves leaf membership and hierarchy)
  * the leaf resolver (W5.3 — turns free-text refs into target leaves)
  * the backbone writer (Phase 2 W6.1 — emits ``<leaf-xref>`` entries)

Outputs:
  * ``ResolvedXref`` / ``UnresolvedXref`` — same shape as Phase 1
  * ``CrossModuleLink`` — the model the docx/pdf linkers consume

The xref builder still never raises on bad input — unresolved references
are reported with a reason so the validation layer can surface them.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.detection.entity_extractor import ExtractedReference
from hyperlink_engine.core.graph.backbone_graph import BackboneGraph
from hyperlink_engine.core.graph.leaf_resolver import (
    LeafResolver,
    UnresolvedLeaf,
)
from hyperlink_engine.core.injection.ectd_backbone_writer import (
    BackboneEditPlan,
    BackboneWriter,
)
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    CrossModuleLink,
)

_log = get_logger("injection.ectd_xref")


def compute_relative_uri(
    *,
    source: Path,
    target: Path,
    anchor: str | None = None,
) -> str:
    """Compute the POSIX-style relative URI from one eCTD leaf to another.

    eCTD packages are filesystem-agnostic — the spec mandates POSIX
    separators and case-sensitive paths. We therefore convert both inputs
    to ``PurePosixPath`` before computing the relative path.

    The returned URI is suitable for direct injection as an OOXML
    external relationship target or a PDF URI annotation.
    """
    source_posix = PurePosixPath(*Path(source).parts)
    target_posix = PurePosixPath(*Path(target).parts)
    # posixpath.relpath handles cross-directory ".." traversal correctly.
    rel = posixpath.relpath(str(target_posix), start=str(source_posix.parent))
    if anchor:
        return f"{rel}#{anchor}"
    return rel


@dataclass(frozen=True)
class ResolvedXref:
    """A reference that successfully resolved to a backbone leaf."""

    reference: ExtractedReference
    leaf: BackboneLeaf
    confidence: float


@dataclass(frozen=True)
class UnresolvedXref:
    """A reference that could not be resolved against the backbone."""

    reference: ExtractedReference
    reason: str


class EctdCrossRefBuilder:
    """Resolve detected references against an eCTD backbone snapshot."""

    def __init__(
        self,
        backbone: BackboneSnapshot,
        *,
        graph: BackboneGraph | None = None,
        resolver: LeafResolver | None = None,
    ) -> None:
        self._backbone = backbone
        self._leaves_by_module: dict[str, list[BackboneLeaf]] = {}
        for leaf in backbone.leaves:
            self._leaves_by_module.setdefault(leaf.module, []).append(leaf)
        self._graph = graph
        self._resolver = resolver or LeafResolver(backbone, graph=graph)

    # ── Public API ──────────────────────────────────────────────────────

    def resolve(
        self,
        references: list[ExtractedReference],
        *,
        current_module: str | None = None,
    ) -> tuple[list[ResolvedXref], list[UnresolvedXref]]:
        """Map references to backbone leaves.

        Phase 1 implementation: handles ``CTD_LEAF`` references that point
        at an explicit module (``Module 2.5.3``, ``m5/...``). Everything
        else is recorded as unresolved with a reason — Week 6 fills in the
        section/table/figure resolution path.
        """
        resolved: list[ResolvedXref] = []
        unresolved: list[UnresolvedXref] = []
        for ref in references:
            if ref.label != "CTD_LEAF":
                unresolved.append(
                    UnresolvedXref(
                        reference=ref,
                        reason=f"label {ref.label!r} not yet supported in Phase 1",
                    )
                )
                continue
            module = self._derive_module(ref)
            if module is None:
                unresolved.append(
                    UnresolvedXref(reference=ref, reason="could not parse module from ref")
                )
                continue
            if current_module is not None and not self._same_module_family(current_module, module):
                unresolved.append(
                    UnresolvedXref(
                        reference=ref,
                        reason=f"cross-module link to {module} deferred to Phase 2",
                    )
                )
                continue
            leaf = self._best_leaf_for_module(module)
            if leaf is None:
                unresolved.append(
                    UnresolvedXref(reference=ref, reason=f"no leaf found for module {module}")
                )
                continue
            resolved.append(
                ResolvedXref(reference=ref, leaf=leaf, confidence=ref.confidence)
            )
        _log.info(
            "ectd_xref_resolution",
            total=len(references),
            resolved=len(resolved),
            unresolved=len(unresolved),
            current_module=current_module,
        )
        return resolved, unresolved

    # ── Phase 2 W6.1 — cross-module resolution ──────────────────────────

    def resolve_cross_module(
        self,
        references: list[ExtractedReference],
        *,
        source_leaf: BackboneLeaf,
    ) -> tuple[list[CrossModuleLink], list[UnresolvedXref]]:
        """Resolve free-text refs into ``CrossModuleLink`` records.

        The crucial difference from ``resolve()``: this method *expects*
        cross-module targets and uses the W5.3 ``LeafResolver`` (rather
        than the simpler exact-module map) so titles + study IDs are also
        tried before giving up.
        """
        links: list[CrossModuleLink] = []
        unresolved: list[UnresolvedXref] = []
        for ref in references:
            outcome = self._resolver.resolve(ref)
            if isinstance(outcome, UnresolvedLeaf):
                unresolved.append(
                    UnresolvedXref(reference=ref, reason=outcome.reason)
                )
                continue
            target_leaf = outcome.leaf
            if target_leaf.leaf_id == source_leaf.leaf_id:
                # Self-reference — drop with a clear reason.
                unresolved.append(
                    UnresolvedXref(
                        reference=ref,
                        reason="self-reference rejected by cross-module resolver",
                    )
                )
                continue
            anchor = self._anchor_for(ref)
            relative = compute_relative_uri(
                source=source_leaf.relative_path,
                target=target_leaf.relative_path,
                anchor=anchor,
            )
            rationale = (
                f"strategy={outcome.strategy} confidence={outcome.confidence:.2f}"
            )
            links.append(
                CrossModuleLink(
                    source_leaf_id=source_leaf.leaf_id,
                    target_leaf_id=target_leaf.leaf_id,
                    source_module=source_leaf.module,
                    target_module=target_leaf.module,
                    relative_uri=relative,
                    anchor=anchor,
                    confidence=outcome.confidence,
                    rationale=rationale,
                )
            )
        _log.info(
            "ectd_cross_module_resolution",
            source_leaf=source_leaf.leaf_id,
            requested=len(references),
            resolved=len(links),
            unresolved=len(unresolved),
        )
        return links, unresolved

    def build_edit_plan(
        self,
        links: list[CrossModuleLink],
    ) -> BackboneEditPlan:
        """Turn a list of CrossModuleLinks into a BackboneEditPlan.

        Each link becomes one ``<leaf-xref>`` entry attached to the
        source leaf in ``index.xml``. The resulting plan is fed to a
        ``BackboneWriter`` to serialize a new backbone copy.
        """
        plan = BackboneEditPlan()
        for link in links:
            target_leaf = self._backbone.leaf_by_id(link.target_leaf_id)
            if target_leaf is None:
                continue
            plan.add_leaf_xref(
                source_leaf_id=link.source_leaf_id,
                target_href=str(PurePosixPath(*target_leaf.relative_path.parts)),
                anchor=link.anchor,
            )
        return plan

    def inject_cross_module_xref(
        self,
        source_leaf: Path | BackboneLeaf,
        target_leaf: Path | BackboneLeaf,
        anchor: str | None = None,
        *,
        plan: BackboneEditPlan | None = None,
    ) -> BackboneEditPlan:
        """Queue a single ``<leaf-xref>`` edit.

        Phase 1 had this as a no-op; W6.1 makes it real but keeps the
        signature backward-compatible. Pass an existing ``BackboneEditPlan``
        to accumulate edits across many calls; otherwise a new one is
        returned.
        """
        plan = plan or BackboneEditPlan()
        # Accept either Path (legacy callers) or BackboneLeaf (new).
        if isinstance(source_leaf, BackboneLeaf):
            source_id = source_leaf.leaf_id
        else:
            match = self._leaf_by_relpath(source_leaf)
            if match is None:
                _log.warning("inject_cross_module_xref_unknown_source", path=str(source_leaf))
                return plan
            source_id = match.leaf_id
        if isinstance(target_leaf, BackboneLeaf):
            target_href = str(PurePosixPath(*target_leaf.relative_path.parts))
        else:
            target_href = str(PurePosixPath(*Path(target_leaf).parts))
        plan.add_leaf_xref(
            source_leaf_id=source_id,
            target_href=target_href,
            anchor=anchor,
        )
        return plan

    def write_backbone_with_edits(
        self,
        plan: BackboneEditPlan,
        *,
        source_backbone_path: Path,
        output_path: Path,
    ) -> Path:
        """Apply ``plan`` against ``source_backbone_path``, write to ``output_path``."""
        writer = BackboneWriter(source_backbone_path, output_path)
        writer.apply(plan)
        return writer.save()

    # ── helpers ─────────────────────────────────────────────────────────

    def _leaf_by_relpath(self, rel_path: Path) -> BackboneLeaf | None:
        candidate = PurePosixPath(*Path(rel_path).parts).as_posix()
        for leaf in self._backbone.leaves:
            if PurePosixPath(*leaf.relative_path.parts).as_posix() == candidate:
                return leaf
        return None

    @staticmethod
    def _anchor_for(ref: ExtractedReference) -> str | None:
        """Build a bookmark-friendly anchor for a target.

        Sections and tables get section-style anchors (``sec_2_5_3``,
        ``table_14_2_1``). Study IDs anchor to the study itself, mirroring
        the heuristic used in ``scripts/phase1_acceptance.py`` so the
        existence checker can resolve them.
        """
        label = ref.label
        if label in {"SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"}:
            num = ref.groups.get("num") or ref.text
            slug = num.replace(".", "_").replace("-", "_").replace(" ", "_")
            prefix = label.lower().split("_")[0]
            return f"{prefix}_{slug}"
        if label == "STUDY_ID":
            return f"study_{ref.text.replace('-', '_')}"
        return None

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _derive_module(ref: ExtractedReference) -> str | None:
        """Turn a CTD_LEAF reference into a module key like 'm2.5'."""
        if "mod" in ref.groups:
            mod = ref.groups["mod"]
            sub = ref.groups.get("sub", "") or ref.groups.get("subpath", "")
            if sub:
                # "Module 5.3.1" → "m5.3.1"; "m5/53-clin-stud-rep/..." → "m5.3"
                first = str(sub).split("/")[0]
                if "-" in first:
                    digits = "".join(ch if ch.isdigit() else "" for ch in first)
                    if digits and len(digits) >= 2:
                        return f"m{digits[0]}." + ".".join(digits[1:])
                if first:
                    return f"m{mod}.{first}"
            return f"m{mod}"
        return None

    @staticmethod
    def _same_module_family(module_a: str, module_b: str) -> bool:
        """True if both modules share the same top-level CTD module."""
        head_a = module_a.split(".")[0]
        head_b = module_b.split(".")[0]
        return head_a == head_b

    def _best_leaf_for_module(self, module: str) -> BackboneLeaf | None:
        """Find a leaf in the backbone that matches `module` exactly or by prefix."""
        if module in self._leaves_by_module:
            return self._leaves_by_module[module][0]
        # Fall back to the most specific prefix match
        candidates = [m for m in self._leaves_by_module if module.startswith(m)]
        if not candidates:
            return None
        best = max(candidates, key=len)
        return self._leaves_by_module[best][0]
