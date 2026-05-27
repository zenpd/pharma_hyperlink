"""W6.3 — cross-module integrity validation.

Whereas ``existence_checker.py`` (Phase 1) verifies any single link target
in isolation, this module validates **eCTD cross-module** links against
the dossier-wide invariants:

  1. The target leaf must exist in the current backbone snapshot
     (not just somewhere on disk).
  2. The target file must exist beneath the dossier root.
  3. If an anchor is requested, it must exist in the target document.
  4. No reference cycles in the resolved graph
     (Module A → Module B → Module A).
  5. No orphaned leaves — every leaf must either be referenced or
     contain at least one outbound reference (the anomaly detector
     consumes this in W8.1, so we expose it here as a primitive).

Each violation is emitted as a ``CrossModuleIntegrityReport`` — a richer
schema than ``LinkRecord`` because cross-module checks carry per-leaf
context the dashboard needs. The module also exposes ``to_link_records``
which converts a list of integrity reports into ``LinkRecord``s for the
existing CSV exporter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.graph.backbone_graph import BackboneGraph
from hyperlink_engine.models import (
    BackboneSnapshot,
    CrossModuleLink,
    LinkKind,
    LinkRecord,
    LinkStatus,
)
from hyperlink_engine.validation.existence_checker import (
    _check_docx_anchor,
    _check_pdf_named_destination,
)

_log = get_logger("validation.cross_module")


class IntegrityIssue(str, Enum):
    """Reason a cross-module link failed validation."""

    OK = "ok"
    TARGET_LEAF_MISSING_FROM_BACKBONE = "target_leaf_missing_from_backbone"
    TARGET_FILE_MISSING = "target_file_missing"
    ANCHOR_NOT_FOUND = "anchor_not_found"
    SOURCE_LEAF_MISSING = "source_leaf_missing"
    SELF_REFERENCE = "self_reference"
    CIRCULAR_REFERENCE = "circular_reference"


@dataclass(frozen=True)
class CrossModuleIntegrityReport:
    """One row in the W6.3 integrity audit."""

    link: CrossModuleLink
    issue: IntegrityIssue
    detail: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.issue == IntegrityIssue.OK


@dataclass(frozen=True)
class CircularReference:
    """A cycle detected among cross-module references."""

    leaf_path: list[str]  # leaf IDs forming the cycle, traversal order

    @property
    def length(self) -> int:
        return len(self.leaf_path)


@dataclass
class CrossModuleAudit:
    """Aggregate result of running every W6.3 check on a dossier."""

    reports: list[CrossModuleIntegrityReport] = field(default_factory=list)
    cycles: list[CircularReference] = field(default_factory=list)
    orphan_leaf_ids: list[str] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(not r.is_ok for r in self.reports) or bool(self.cycles)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.reports if r.is_ok)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.reports if not r.is_ok)


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────


def validate_cross_module_link(
    link: CrossModuleLink,
    snapshot: BackboneSnapshot,
    *,
    base_dir: Path,
) -> CrossModuleIntegrityReport:
    """Validate a single ``CrossModuleLink`` against the dossier on disk."""
    source = snapshot.leaf_by_id(link.source_leaf_id)
    target = snapshot.leaf_by_id(link.target_leaf_id)
    if source is None:
        return CrossModuleIntegrityReport(
            link=link,
            issue=IntegrityIssue.SOURCE_LEAF_MISSING,
            detail=f"source leaf {link.source_leaf_id!r} not in backbone",
        )
    if target is None:
        return CrossModuleIntegrityReport(
            link=link,
            issue=IntegrityIssue.TARGET_LEAF_MISSING_FROM_BACKBONE,
            detail=f"target leaf {link.target_leaf_id!r} not in backbone",
        )
    if source.leaf_id == target.leaf_id:
        return CrossModuleIntegrityReport(
            link=link,
            issue=IntegrityIssue.SELF_REFERENCE,
            detail="cross-module link points at its own source leaf",
        )
    target_path = Path(base_dir) / target.relative_path
    if not target_path.exists():
        return CrossModuleIntegrityReport(
            link=link,
            issue=IntegrityIssue.TARGET_FILE_MISSING,
            detail=f"{target_path} does not exist on disk",
        )
    if link.anchor:
        if target_path.suffix.lower() == ".pdf":
            status, detail = _check_pdf_named_destination(target_path, link.anchor)
        else:
            status, detail = _check_docx_anchor(target_path, link.anchor)
        if status == LinkStatus.BROKEN:
            return CrossModuleIntegrityReport(
                link=link,
                issue=IntegrityIssue.ANCHOR_NOT_FOUND,
                detail=detail,
            )
    return CrossModuleIntegrityReport(link=link, issue=IntegrityIssue.OK)


def validate_cross_module_links(
    links: list[CrossModuleLink],
    snapshot: BackboneSnapshot,
    *,
    base_dir: Path,
) -> list[CrossModuleIntegrityReport]:
    """Validate a batch of cross-module links — one report per input link."""
    reports: list[CrossModuleIntegrityReport] = []
    for link in links:
        reports.append(validate_cross_module_link(link, snapshot, base_dir=base_dir))
    _log.info(
        "cross_module_integrity_batch",
        total=len(reports),
        ok=sum(1 for r in reports if r.is_ok),
        failures=sum(1 for r in reports if not r.is_ok),
    )
    return reports


def detect_circular_refs(graph: BackboneGraph) -> list[CircularReference]:
    """Return every cycle of ``ref`` edges in the graph.

    The Phase 2 implementation reports the **first** cycle NetworkX finds.
    Phase 3 will iterate through SCCs for an exhaustive list — for now,
    we surface the smallest cycle (NetworkX returns the simple cycle from
    a DFS, which is typically minimal) and let the dashboard re-run
    detection after the user fixes the first issue.
    """
    cycle = graph.find_cycle()
    if cycle is None:
        return []
    # Convert the pair-list into a single ordered list of leaf IDs.
    ordered: list[str] = [cycle[0][0]] + [pair[1] for pair in cycle]
    return [CircularReference(leaf_path=ordered)]


def detect_orphans(
    graph: BackboneGraph,
    *,
    ignore_modules: set[str] | None = None,
) -> list[str]:
    """Leaf_ids with no inbound or outbound reference edges.

    ``ignore_modules`` lets callers exclude module families that are
    legitimately orphaned (e.g. cover letters in ``m1``).
    """
    ignore = ignore_modules or set()
    raw_orphans = graph.orphans()
    if not ignore:
        return raw_orphans
    out: list[str] = []
    for leaf_id in raw_orphans:
        node_data = graph.raw.nodes[graph.leaf_node(leaf_id)]
        module = node_data.get("module", "")
        if any(module.startswith(prefix) for prefix in ignore):
            continue
        out.append(leaf_id)
    return out


def run_full_audit(
    links: list[CrossModuleLink],
    snapshot: BackboneSnapshot,
    *,
    base_dir: Path,
    graph: BackboneGraph | None = None,
    orphan_ignore_modules: set[str] | None = None,
) -> CrossModuleAudit:
    """Convenience: per-link checks + cycle detection + orphan listing."""
    reports = validate_cross_module_links(links, snapshot, base_dir=base_dir)
    cycles: list[CircularReference] = []
    orphans: list[str] = []
    if graph is not None:
        cycles = detect_circular_refs(graph)
        orphans = detect_orphans(graph, ignore_modules=orphan_ignore_modules)
    audit = CrossModuleAudit(reports=reports, cycles=cycles, orphan_leaf_ids=orphans)
    _log.info(
        "cross_module_audit_complete",
        total_links=len(reports),
        failures=audit.failure_count,
        cycles=len(cycles),
        orphans=len(orphans),
    )
    return audit


# ─────────────────────────────────────────────────────────────────────────
# CSV exporter bridge
# ─────────────────────────────────────────────────────────────────────────


_ISSUE_TO_STATUS: dict[IntegrityIssue, LinkStatus] = {
    IntegrityIssue.OK: LinkStatus.OK,
    IntegrityIssue.TARGET_LEAF_MISSING_FROM_BACKBONE: LinkStatus.BROKEN,
    IntegrityIssue.TARGET_FILE_MISSING: LinkStatus.BROKEN,
    IntegrityIssue.ANCHOR_NOT_FOUND: LinkStatus.BROKEN,
    IntegrityIssue.SOURCE_LEAF_MISSING: LinkStatus.BROKEN,
    IntegrityIssue.SELF_REFERENCE: LinkStatus.SUSPICIOUS,
    IntegrityIssue.CIRCULAR_REFERENCE: LinkStatus.SUSPICIOUS,
}


def to_link_records(reports: list[CrossModuleIntegrityReport]) -> list[LinkRecord]:
    """Convert integrity reports into LinkRecords for the existing CSV writer."""
    records: list[LinkRecord] = []
    for report in reports:
        records.append(
            LinkRecord(
                source_doc=report.link.source_leaf_id,
                link_text=report.link.relative_uri,
                link_location_descriptor=f"cross-module:{report.link.source_module}→{report.link.target_module}",
                target_doc=report.link.target_leaf_id,
                target_anchor=report.link.anchor,
                status=_ISSUE_TO_STATUS[report.issue],
                confidence=report.link.confidence,
                error_msg=report.detail,
            )
        )
    return records


def _kind_for_link(_link: CrossModuleLink) -> LinkKind:
    """Reserved: future logic may distinguish CROSS_DOC vs CROSS_MODULE."""
    return LinkKind.CROSS_MODULE
