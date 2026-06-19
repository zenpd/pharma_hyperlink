"""Layer 1 — eCTD backbone XML ingestion.

Parses `index.xml` and emits a read-only `BackboneSnapshot`. The loader is
schema-aware: it handles ICH eCTD v3.2 (the dominant variant today), v4.0
(structured-product-labeling-style), and is structured so regional flavors
(FDA `us-regional`, EMA `eu-regional`, PMDA `jp-regional`, Health Canada
`ca-regional`) can be plugged in without rewriting the leaf walker.

Phase 2 adds:
  * Regional sub-backbone merging (`load_backbone_with_regional`)
  * Per-leaf MD5 verification against the file system (`verify_checksums`)
  * Cross-sequence diffing (`diff_snapshots`) — drives the "modified" flag
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

from lxml import etree

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import (
    BackboneDiff,
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    LeafIntegrityReport,
    LeafIntegrityStatus,
    LeafOperation,
)

_log = get_logger("ingestion.ectd")

_BUFFER_SIZE = 1024 * 1024

# Default namespaces seen across ICH spec variants. Real-world dossiers
# sometimes use the bare HL7 namespace, sometimes a versioned one — we
# resolve both by stripping the namespace at query time.
_XLINK_NS = "http://www.w3.org/1999/xlink"

_MODULE_FROM_PATH_RE = re.compile(
    r"^(?P<mod>m[1-5])(?:[/\\](?P<sub>[0-9][0-9a-z\-]*))?",
    re.IGNORECASE,
)


class EctdLoadError(RuntimeError):
    """Raised when an eCTD backbone XML cannot be parsed or is malformed."""


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_BUFFER_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _md5_of(path: Path) -> str:
    """Streaming MD5 — eCTD spec mandates MD5 (RFC 1321) for leaf checksums."""
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_BUFFER_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _local_name(tag: str) -> str:
    """Return the local part of a possibly-namespaced lxml tag."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _detect_schema_version(root: etree._Element) -> str:
    """Best-effort schema-version detection — explicit attribute first, then heuristics."""
    explicit = root.attrib.get("dtd-version") or root.attrib.get("schema-version")
    if explicit:
        return f"v{explicit}" if not explicit.startswith("v") else explicit
    # ICH v4.0 uses HL7 RIM-style elements; v3.2 uses <ectd>/<leaf>.
    if _local_name(root.tag).lower() == "ectd":
        return "v3.2"
    if _local_name(root.tag).lower() in {"submission", "documentlibrary"}:
        return "v4.0"
    return "unknown"


def _detect_region(root: etree._Element) -> str | None:
    """Look for a *-regional child element to identify the region."""
    for child in root.iter():
        local = _local_name(child.tag).lower()
        if local.endswith("-regional"):
            prefix = local.split("-regional", 1)[0]
            if prefix in {"fda", "us"}:
                return "us"
            if prefix in {"ema", "eu"}:
                return "eu"
            if prefix in {"pmda", "jp"}:
                return "jp"
            if prefix in {"hc", "ca"}:
                return "ca"
            return prefix or None
    return None


def _detect_sequence(root: etree._Element) -> str | None:
    for child in root.iter():
        attrs = child.attrib
        for key in ("submission-id", "sequence", "sequenceNumber"):
            value = attrs.get(key)
            if value:
                # Common pattern is "<sponsor>-0001"; normalize to the trailing 4-digit ID when present.
                m = re.search(r"(\d{4})$", value)
                return m.group(1) if m else value
    return None


def _leaf_module(rel_path: str) -> str:
    """Derive a 'm2.5' style module label from the leaf's relative href.

    Examples:
      'm2/2-5-clin-overview/...'        -> 'm2.5'
      'm5/5-3-1-bio-stud-rep/...'       -> 'm5.3.1'
      'm2/2-7-clin-summary/...'         -> 'm2.7'
      'm1/us/1-3-1-letter.docx'         -> 'm1'   (region directory, not numeric)
    """
    norm = rel_path.replace("\\", "/").lstrip("./")
    m = _MODULE_FROM_PATH_RE.match(norm)
    if not m:
        return "unknown"
    mod = m.group("mod").lower()  # e.g. 'm5'
    sub = m.group("sub")
    if not sub:
        return mod
    # Collect leading numeric pieces from the subfolder ("5-3-1-bio-..." -> ["5","3","1"]).
    nums: list[str] = []
    for piece in sub.split("-"):
        if piece.isdigit():
            nums.append(piece)
        else:
            break
    if len(nums) <= 1:
        return mod  # only the module digit, no meaningful sub-section
    # nums[0] should agree with mod's digit; build "m<digit>.<sub1>.<sub2>..."
    return f"m{nums[0]}." + ".".join(nums[1:])


def _iter_leaves(root: etree._Element) -> Iterable[etree._Element]:
    """Yield every <leaf> element regardless of namespace."""
    for element in root.iter():
        if _local_name(element.tag).lower() == "leaf":
            yield element


def _leaf_href(leaf: etree._Element) -> str | None:
    """Extract xlink:href first, fall back to href."""
    href = leaf.attrib.get(f"{{{_XLINK_NS}}}href")
    if href:
        return href
    return leaf.attrib.get("href")


def _leaf_title(leaf: etree._Element) -> str | None:
    for child in leaf:
        if _local_name(child.tag).lower() == "title" and (child.text or "").strip():
            return child.text.strip()
    return None


def _leaf_checksum(leaf: etree._Element) -> tuple[str | None, str]:
    """Return (checksum_value, checksum_type)."""
    chk_type = leaf.attrib.get("checksum-type") or "md5"
    direct = leaf.attrib.get("checksum")
    if direct:
        return direct, chk_type
    for child in leaf:
        if _local_name(child.tag).lower() == "checksum" and (child.text or "").strip():
            return child.text.strip(), chk_type
    return None, chk_type


def _leaf_operation(leaf: etree._Element) -> LeafOperation:
    op = (leaf.attrib.get("operation") or "new").lower()
    try:
        return LeafOperation(op)
    except ValueError:
        return LeafOperation.NEW


def parse_backbone(root: etree._Element, provenance: DocumentProvenance) -> BackboneSnapshot:
    leaves_out: list[BackboneLeaf] = []
    for idx, leaf in enumerate(_iter_leaves(root)):
        href = _leaf_href(leaf)
        if not href:
            _log.warning("ectd_leaf_missing_href", index=idx, leaf_id=leaf.attrib.get("ID"))
            continue
        leaf_id = leaf.attrib.get("ID") or f"leaf-anon-{idx}"
        chk, chk_type = _leaf_checksum(leaf)
        leaves_out.append(
            BackboneLeaf(
                leaf_id=leaf_id,
                relative_path=Path(href),
                module=_leaf_module(href),
                operation=_leaf_operation(leaf),
                checksum=chk,
                checksum_type=chk_type,
                title=_leaf_title(leaf),
            )
        )

    return BackboneSnapshot(
        provenance=provenance,
        schema_version=_detect_schema_version(root),
        region=_detect_region(root),
        sequence_number=_detect_sequence(root),
        leaves=leaves_out,
    )


def load_backbone(path: Path) -> BackboneSnapshot:
    """Read `index.xml` (or equivalent) from disk and return a BackboneSnapshot."""
    path = Path(path)
    if not path.exists():
        raise EctdLoadError(f"{path} does not exist")
    if not path.is_file():
        raise EctdLoadError(f"{path} is not a file")

    sha = _sha256_of(path)
    size = path.stat().st_size
    provenance = DocumentProvenance(source_path=path, sha256=sha, file_size_bytes=size)

    try:
        # Disable DTD/network loading; backbone XML must be self-contained.
        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
        tree = etree.parse(str(path), parser=parser)
    except etree.XMLSyntaxError as exc:
        raise EctdLoadError(f"{path} is not well-formed XML: {exc}") from exc

    snapshot = parse_backbone(tree.getroot(), provenance)
    _log.info(
        "ectd_loaded",
        path=str(path),
        schema=snapshot.schema_version,
        region=snapshot.region,
        sequence=snapshot.sequence_number,
        leaves=snapshot.leaf_count,
    )
    return snapshot


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 additions — regional merging, checksum verification, diffing.
# ─────────────────────────────────────────────────────────────────────────


# Common locations where regional backbones live, relative to the main
# index.xml. We probe them in order and merge whichever exist.
_REGIONAL_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("us", "m1/us/us-regional.xml"),
    ("eu", "m1/eu/eu-regional.xml"),
    ("jp", "m1/jp/jp-regional.xml"),
    ("ca", "m1/ca/ca-regional.xml"),
)


def load_backbone_with_regional(
    index_path: Path,
    *,
    extra_regional: Iterable[Path] = (),
) -> BackboneSnapshot:
    """Load the main index.xml then merge any matching regional sub-backbones.

    The ICH spec splits the backbone across modules: ``index.xml`` covers
    modules 2–5 (cross-region content), and each region carries an
    ``m1/<region>/<region>-regional.xml`` for Module 1. Real submissions
    therefore *require* both files to know every leaf.

    Args:
      index_path: Path to the main backbone (``index.xml``).
      extra_regional: Optional explicit regional XML paths to merge in,
        in addition to whatever auto-discovery finds.

    Returns:
      A single merged ``BackboneSnapshot``. ``regional_sources`` lists
      every regional file that contributed leaves.
    """
    base = load_backbone(index_path)
    index_root = index_path.parent
    seen_ids = {leaf.leaf_id for leaf in base.leaves}
    merged_leaves: list[BackboneLeaf] = list(base.leaves)
    merged_sources: list[Path] = list(base.regional_sources)

    candidate_paths: list[tuple[str | None, Path]] = []
    for region_hint, rel in _REGIONAL_CANDIDATES:
        candidate = index_root / rel
        if candidate.exists():
            candidate_paths.append((region_hint, candidate))
    for extra in extra_regional:
        extra = Path(extra)
        if not extra.exists():
            raise EctdLoadError(f"regional backbone {extra} does not exist")
        candidate_paths.append((None, extra))

    for region_hint, regional_path in candidate_paths:
        regional = load_backbone(regional_path)
        merged_sources.append(regional_path)
        for leaf in regional.leaves:
            if leaf.leaf_id in seen_ids:
                _log.warning(
                    "ectd_regional_leaf_collision",
                    leaf_id=leaf.leaf_id,
                    source=str(regional_path),
                )
                continue
            tagged = leaf.model_copy(
                update={"region_source": region_hint or regional.region or "unknown"}
            )
            merged_leaves.append(tagged)
            seen_ids.add(leaf.leaf_id)

    # Region precedence: explicit on base wins; otherwise inherit from regional.
    final_region = base.region
    if final_region is None:
        for region_hint, _ in candidate_paths:
            if region_hint:
                final_region = region_hint
                break

    return base.model_copy(
        update={
            "leaves": merged_leaves,
            "regional_sources": merged_sources,
            "region": final_region,
        }
    )


def verify_checksums(
    snapshot: BackboneSnapshot,
    *,
    base_dir: Path | None = None,
) -> list[LeafIntegrityReport]:
    """Recompute every leaf's checksum and compare to the declared value.

    Args:
      snapshot: The backbone snapshot to verify.
      base_dir: Directory the leaves' ``relative_path`` resolves against.
        Defaults to the snapshot's provenance source directory.

    Returns:
      One ``LeafIntegrityReport`` per leaf in the snapshot.
    """
    if base_dir is None:
        base_dir = snapshot.provenance.source_path.parent
    base_dir = Path(base_dir)

    reports: list[LeafIntegrityReport] = []
    for leaf in snapshot.leaves:
        leaf_path = base_dir / leaf.relative_path
        if not leaf_path.exists():
            reports.append(
                LeafIntegrityReport(
                    leaf_id=leaf.leaf_id,
                    relative_path=leaf.relative_path,
                    status=LeafIntegrityStatus.MISSING_FILE,
                    expected=leaf.checksum,
                    actual=None,
                    error_msg=f"{leaf_path} not found",
                )
            )
            continue
        if not leaf.checksum:
            reports.append(
                LeafIntegrityReport(
                    leaf_id=leaf.leaf_id,
                    relative_path=leaf.relative_path,
                    status=LeafIntegrityStatus.NO_CHECKSUM,
                    expected=None,
                    actual=None,
                )
            )
            continue
        # eCTD spec is MD5; respect the recorded checksum_type if the
        # backbone author used something else.
        algo = (leaf.checksum_type or "md5").lower()
        if algo == "md5":
            actual = _md5_of(leaf_path)
        elif algo == "sha256":
            actual = _sha256_of(leaf_path)
        else:
            reports.append(
                LeafIntegrityReport(
                    leaf_id=leaf.leaf_id,
                    relative_path=leaf.relative_path,
                    status=LeafIntegrityStatus.NO_CHECKSUM,
                    expected=leaf.checksum,
                    actual=None,
                    error_msg=f"unsupported checksum algo {algo!r}",
                )
            )
            continue
        if actual.lower() == leaf.checksum.lower():
            status = LeafIntegrityStatus.OK
        else:
            status = LeafIntegrityStatus.MISMATCH
        reports.append(
            LeafIntegrityReport(
                leaf_id=leaf.leaf_id,
                relative_path=leaf.relative_path,
                status=status,
                expected=leaf.checksum,
                actual=actual,
            )
        )
    return reports


def diff_snapshots(prev: BackboneSnapshot, current: BackboneSnapshot) -> BackboneDiff:
    """Set-difference two backbones, typically across sequence numbers.

    A leaf is considered "modified" when its checksum (preferred) or its
    declared operation differs between the two snapshots. This drives the
    cross-sequence change report Phase 2 needs for "latest valid leaf"
    lookups in W6.2.
    """
    prev_index = {leaf.leaf_id: leaf for leaf in prev.leaves}
    cur_index = {leaf.leaf_id: leaf for leaf in current.leaves}

    added: list[str] = sorted(set(cur_index) - set(prev_index))
    removed: list[str] = sorted(set(prev_index) - set(cur_index))
    modified: list[str] = []
    unchanged: list[str] = []

    for leaf_id in sorted(set(prev_index) & set(cur_index)):
        prev_leaf = prev_index[leaf_id]
        cur_leaf = cur_index[leaf_id]
        # Prefer checksum comparison when both sides have it; otherwise
        # fall back to the declared operation as a weaker signal.
        if prev_leaf.checksum and cur_leaf.checksum:
            if prev_leaf.checksum.lower() != cur_leaf.checksum.lower():
                modified.append(leaf_id)
            else:
                unchanged.append(leaf_id)
        elif cur_leaf.operation != LeafOperation.NEW or prev_leaf.operation != cur_leaf.operation:
            modified.append(leaf_id)
        else:
            unchanged.append(leaf_id)

    return BackboneDiff(
        added_leaf_ids=added,
        removed_leaf_ids=removed,
        modified_leaf_ids=modified,
        unchanged_leaf_ids=unchanged,
    )
