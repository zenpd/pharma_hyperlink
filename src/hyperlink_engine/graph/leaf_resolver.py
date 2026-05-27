"""W5.3 — Leaf-to-leaf resolver.

Given a detected reference like ``"Module 5.3.1 CSR for Study SP-2024-001"``,
return the matching ``BackboneLeaf`` in the dossier (or ``None`` if no
plausible target exists).

The resolver tries strategies in increasing cost order:

  1. **Exact module match** — when the reference's module string maps to
     a single leaf in the snapshot. Used for ``CTD_LEAF`` references that
     carry an explicit ``mod``/``sub`` groups.
  2. **Module prefix match** — when the module string only resolves a
     subtree (e.g. ``m5.3``), pick the smallest matching leaf set; tie
     break by closest module specificity.
  3. **Title-based fuzzy match** — Jaccard over title tokens for the
     remaining candidates; useful for ``"CSR for Study SP-2024-001"`` style
     references that don't include a module path.
  4. **Study-ID match** — for ``STUDY_ID`` references, search leaf titles +
     paths for the study ID literal.

Anything below ``min_confidence`` is reported as unresolved so the caller
can decide whether to ask the LLM, log a warning, or skip.

The resolver is intentionally read-only against the backbone — it never
mutates the snapshot or the graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.detection.entity_extractor import ExtractedReference
from hyperlink_engine.graph.backbone_graph import BackboneGraph
from hyperlink_engine.models import BackboneLeaf, BackboneSnapshot

_log = get_logger("graph.leaf_resolver")


@dataclass(frozen=True)
class LeafResolution:
    """A resolved leaf with its decision trail."""

    leaf: BackboneLeaf
    confidence: float
    strategy: str  # "module_exact" | "module_prefix" | "title_fuzzy" | "study_id"


@dataclass(frozen=True)
class UnresolvedLeaf:
    """A reference the resolver could not map to any leaf with enough confidence."""

    reference: ExtractedReference
    reason: str
    best_candidate: BackboneLeaf | None = None
    best_score: float = 0.0


class LeafResolver:
    """Resolve free-text / structured references to backbone leaves."""

    def __init__(
        self,
        snapshot: BackboneSnapshot,
        *,
        graph: BackboneGraph | None = None,
        min_confidence: float = 0.55,
    ) -> None:
        self._snapshot = snapshot
        self._graph = graph
        self._min_confidence = min_confidence
        self._by_module: dict[str, list[BackboneLeaf]] = {}
        for leaf in snapshot.leaves:
            self._by_module.setdefault(leaf.module, []).append(leaf)

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    # ── Public API ──────────────────────────────────────────────────────

    def resolve(self, reference: ExtractedReference) -> LeafResolution | UnresolvedLeaf:
        """Try strategies in order; return the first one above threshold."""
        # Strategy 1 & 2: module-driven resolution for CTD_LEAF refs.
        if reference.label == "CTD_LEAF":
            res = self._resolve_by_module(reference)
            if res is not None:
                return res

        # Strategy 4: study-id literal search.
        if reference.label == "STUDY_ID":
            res = self._resolve_by_study_id(reference)
            if res is not None:
                return res

        # Strategy 3: title-fuzzy fallback for any reference type.
        res = self._resolve_by_title(reference)
        if res is not None:
            return res

        return UnresolvedLeaf(
            reference=reference,
            reason="no strategy produced a confident match",
        )

    def resolve_many(
        self, references: list[ExtractedReference]
    ) -> tuple[list[LeafResolution], list[UnresolvedLeaf]]:
        resolved: list[LeafResolution] = []
        unresolved: list[UnresolvedLeaf] = []
        for ref in references:
            outcome = self.resolve(ref)
            if isinstance(outcome, LeafResolution):
                resolved.append(outcome)
            else:
                unresolved.append(outcome)
        _log.info(
            "leaf_resolver_batch",
            total=len(references),
            resolved=len(resolved),
            unresolved=len(unresolved),
        )
        return resolved, unresolved

    # ── Strategy implementations ────────────────────────────────────────

    def _resolve_by_module(self, ref: ExtractedReference) -> LeafResolution | None:
        module = self._derive_module(ref)
        if module is None:
            return None

        # Exact module match.
        exact = self._by_module.get(module)
        if exact:
            leaf = exact[0]
            return LeafResolution(leaf=leaf, confidence=0.95, strategy="module_exact")

        # Prefix match — pick the deepest matching module.
        matching = [
            (mod, leaves)
            for mod, leaves in self._by_module.items()
            if mod.startswith(module) or module.startswith(mod)
        ]
        if not matching:
            return None
        # Prefer the most specific module (longest label) that contains a leaf.
        matching.sort(key=lambda kv: len(kv[0]), reverse=True)
        best_mod, best_leaves = matching[0]
        leaf = best_leaves[0]
        # Confidence drops the further we drift from the requested module.
        depth_delta = abs(len(best_mod.split(".")) - len(module.split(".")))
        confidence = max(0.6, 0.9 - 0.1 * depth_delta)
        return LeafResolution(
            leaf=leaf, confidence=confidence, strategy="module_prefix"
        )

    def _resolve_by_study_id(self, ref: ExtractedReference) -> LeafResolution | None:
        needle = ref.text.strip().lower()
        if not needle:
            return None
        best: tuple[float, BackboneLeaf] | None = None
        for leaf in self._snapshot.leaves:
            haystack = " ".join(
                filter(
                    None,
                    [leaf.title or "", str(leaf.relative_path), leaf.leaf_id],
                )
            ).lower()
            if needle in haystack:
                # Direct substring hit — high confidence.
                if best is None or 0.92 > best[0]:
                    best = (0.92, leaf)
        if best is None:
            return None
        score, leaf = best
        if score < self._min_confidence:
            return None
        return LeafResolution(leaf=leaf, confidence=score, strategy="study_id")

    def _resolve_by_title(self, ref: ExtractedReference) -> LeafResolution | None:
        ref_tokens = _tokenize(ref.text)
        if not ref_tokens:
            return None
        best: tuple[float, BackboneLeaf] | None = None
        for leaf in self._snapshot.leaves:
            title = leaf.title or ""
            if not title:
                continue
            score = _jaccard(ref_tokens, _tokenize(title))
            if best is None or score > best[0]:
                best = (score, leaf)
        if best is None:
            return None
        score, leaf = best
        if score < self._min_confidence:
            return None
        return LeafResolution(leaf=leaf, confidence=score, strategy="title_fuzzy")

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _derive_module(ref: ExtractedReference) -> str | None:
        """Mirror of ``EctdCrossRefBuilder._derive_module`` to keep behavior aligned."""
        groups = ref.groups or {}
        if "mod" not in groups:
            return None
        mod = groups["mod"]
        sub = groups.get("sub", "") or groups.get("subpath", "")
        if sub:
            first = str(sub).split("/")[0]
            if "-" in first:
                digits = "".join(ch if ch.isdigit() else "" for ch in first)
                if digits and len(digits) >= 2:
                    return f"m{digits[0]}." + ".".join(digits[1:])
            if first:
                return f"m{mod}.{first}"
        return f"m{mod}"


# ─────────────────────────────────────────────────────────────────────────
# Token / similarity helpers
# ─────────────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric token set for Jaccard comparisons."""
    if not text:
        return set()
    out: set[str] = set()
    cur: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            token = "".join(cur)
            if len(token) > 1:  # drop noise like single digits / 'a'
                out.add(token)
            cur.clear()
    if cur:
        token = "".join(cur)
        if len(token) > 1:
            out.add(token)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ─────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ─────────────────────────────────────────────────────────────────────────


def resolve_for_snapshot(
    references: list[ExtractedReference],
    snapshot: BackboneSnapshot,
    *,
    min_confidence: float = 0.55,
) -> tuple[list[LeafResolution], list[UnresolvedLeaf]]:
    """One-shot helper: build a resolver and resolve a batch in one call."""
    resolver = LeafResolver(snapshot, min_confidence=min_confidence)
    return resolver.resolve_many(references)


def leaf_path(leaf: BackboneLeaf, base: Path | None = None) -> Path:
    """Absolute filesystem path of a leaf, given the snapshot's base dir."""
    if base is None:
        return leaf.relative_path
    return Path(base) / leaf.relative_path
