"""W6.2 — Sequence-aware leaf history.

eCTD submissions are *cumulative*. Each new sequence (0001, 0002, ...)
either adds new leaves, replaces existing ones, appends to existing ones,
or deletes them. To inject a link that stays valid across the dossier's
lifetime, we must point at the **latest valid version** of the target
leaf — not whichever copy we happened to find in an older sequence.

This module provides two primitives:

  * ``SequenceTimeline``   — accumulates snapshots in chronological order,
    deduplicates leaves by an identity key, and yields the latest valid
    leaf for any (study_id, module) or (relative_path,) lookup.

  * ``find_latest_leaf(study_id, module, snapshots)``  — convenience
    wrapper for the common pipeline case (Phase 2 W6.2 acceptance).

Identity rules (ICH-aligned):

  * If two leaves across snapshots share the same ``relative_path``,
    they're the same artefact (later sequence wins).
  * If two leaves share the same ``leaf_id``, the later sequence wins.
  * A leaf with ``operation == DELETE`` in the latest sequence removes
    the artefact from the timeline (no "latest" returned).

The timeline is also responsible for wiring ``NEXT_SEQUENCE`` edges into
the backbone graph so the resolver / dashboard can show provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.graph.backbone_graph import BackboneGraph
from hyperlink_engine.models import (
    BackboneLeaf,
    BackboneSnapshot,
    LeafOperation,
)

_log = get_logger("graph.sequence_history")


def _norm_path(path: Path) -> str:
    """Normalize a relative path for cross-snapshot identity comparison."""
    return PurePosixPath(*Path(path).parts).as_posix().lower()


@dataclass
class TimelineEntry:
    """One step in a leaf's sequence history."""

    sequence_number: str | None
    leaf: BackboneLeaf

    @property
    def is_terminal_delete(self) -> bool:
        return self.leaf.operation == LeafOperation.DELETE


@dataclass
class SequenceTimeline:
    """Cumulative view across an ordered list of backbone snapshots."""

    snapshots: list[BackboneSnapshot] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Sort snapshots ascending so "latest" is unambiguous.
        self.snapshots = sorted(
            self.snapshots,
            key=lambda s: (s.sequence_number or "0000"),
        )
        # Identity map keyed by normalized relative_path → list of entries.
        self._by_path: dict[str, list[TimelineEntry]] = {}
        # Secondary index by leaf_id (some submissions reuse the same id
        # across sequences instead of the same path).
        self._by_id: dict[str, list[TimelineEntry]] = {}
        for snap in self.snapshots:
            for leaf in snap.leaves:
                entry = TimelineEntry(sequence_number=snap.sequence_number, leaf=leaf)
                self._by_path.setdefault(_norm_path(leaf.relative_path), []).append(entry)
                self._by_id.setdefault(leaf.leaf_id, []).append(entry)

    # ── Constructors ────────────────────────────────────────────────────

    @classmethod
    def from_snapshots(cls, snapshots: list[BackboneSnapshot]) -> "SequenceTimeline":
        return cls(snapshots=list(snapshots))

    # ── Public queries ──────────────────────────────────────────────────

    def latest_by_path(self, relative_path: Path) -> BackboneLeaf | None:
        """Return the latest non-deleted leaf at the given relative path."""
        entries = self._by_path.get(_norm_path(relative_path))
        if not entries:
            return None
        latest = entries[-1]
        if latest.is_terminal_delete:
            return None
        return latest.leaf

    def latest_by_leaf_id(self, leaf_id: str) -> BackboneLeaf | None:
        entries = self._by_id.get(leaf_id)
        if not entries:
            return None
        latest = entries[-1]
        if latest.is_terminal_delete:
            return None
        return latest.leaf

    def latest_for_study(
        self,
        study_id: str,
        *,
        module: str | None = None,
    ) -> BackboneLeaf | None:
        """Latest leaf whose title / path / id contains the study_id literal.

        Optional ``module`` filter further constrains the search by module
        prefix (e.g. ``"m5.3.1"``).
        """
        needle = study_id.strip().lower()
        if not needle:
            return None
        candidates: list[BackboneLeaf] = []
        # Iterate snapshots in reverse so the *latest* matching leaf wins.
        for snap in reversed(self.snapshots):
            for leaf in snap.leaves:
                if module and not leaf.module.startswith(module):
                    continue
                haystack = " ".join(
                    [
                        leaf.title or "",
                        str(leaf.relative_path),
                        leaf.leaf_id,
                    ]
                ).lower()
                if needle in haystack:
                    # Reject if this leaf has since been deleted.
                    later = self.latest_by_path(leaf.relative_path)
                    if later is not None:
                        candidates.append(later)
        return candidates[0] if candidates else None

    def history_of(self, relative_path: Path) -> list[TimelineEntry]:
        """Full sequence history of a leaf (chronological, oldest → newest)."""
        return list(self._by_path.get(_norm_path(relative_path), []))

    # ── Graph wiring ────────────────────────────────────────────────────

    def wire_sequence_edges(self, graph: BackboneGraph) -> int:
        """Add ``NEXT_SEQUENCE`` edges connecting prior versions to current.

        Skips edges whose endpoints aren't both present in the graph —
        callers typically build the graph from the *current* snapshot only,
        so historical leaves may be missing. Returns the number of edges
        actually added.
        """
        added = 0
        for entries in self._by_path.values():
            for prev, cur in zip(entries, entries[1:], strict=False):
                if not graph.has_leaf(prev.leaf.leaf_id):
                    continue
                if not graph.has_leaf(cur.leaf.leaf_id):
                    continue
                if prev.leaf.leaf_id == cur.leaf.leaf_id:
                    continue
                graph.link_sequence(prev.leaf.leaf_id, cur.leaf.leaf_id)
                added += 1
        _log.info("sequence_edges_wired", added=added)
        return added

    @property
    def snapshot_count(self) -> int:
        return len(self.snapshots)


# ─────────────────────────────────────────────────────────────────────────
# Convenience top-level helpers
# ─────────────────────────────────────────────────────────────────────────


def find_latest_leaf(
    study_id: str,
    module: str | None,
    snapshots: list[BackboneSnapshot],
) -> BackboneLeaf | None:
    """One-shot helper: build a timeline and return the latest leaf for study+module."""
    timeline = SequenceTimeline.from_snapshots(snapshots)
    return timeline.latest_for_study(study_id, module=module)
