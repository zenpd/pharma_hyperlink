"""W8.1 — Anomaly Detection v1.

Detects five classes of anomaly in processed dossier documents:

1. **Blue text without hyperlink** — a run is coloured blue (matching the
   "hyperlink style" visual cue) but carries no actual link.  Sourced from
   :func:`parsing.docx_parser.candidate_blue_runs`.

2. **Orphaned references** — a reference was detected by the extraction layer
   but the injection step produced no link for it (no resolvable target).

3. **Circular references** — A → B → A in the eCTD backbone graph.  Delegates
   to :func:`validation.cross_module_integrity.detect_circular_refs`.

4. **Deprecated Study IDs** — a study identifier appears in text but is listed
   in ``data/deprecated_ids.yaml`` as withdrawn or superseded.

5. **Suspicious link targets** — the link's visible text and its destination
   anchor / URI are semantically inconsistent (e.g., visible "Section 5.3.2"
   points to Section 4.x).

Each anomaly carries:
  * ``kind``          — one of :class:`models.AnomalyKind`
  * ``severity``      — BLOCKER / WARNING / INFO
  * ``document``      — source document path (string)
  * ``location``      — optional :class:`models.RunLocation`
  * ``text``          — the offending text fragment
  * ``suggested_fix`` — human-readable remediation hint
  * ``confidence``    — detection confidence (0–1)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import yaml

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.models import (
    Anomaly,
    AnomalyKind,
    AnomalySeverity,
    DocxDocument,
    LinkRecord,
    LinkStatus,
    RunLocation,
)

_log = get_logger("validation.anomaly_detector")

# ─────────────────────────────────────────────────────────────────────────────
# Deprecated-ID registry
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "deprecated_ids.yaml"
)


@dataclass(frozen=True)
class DeprecatedEntry:
    """One entry from ``deprecated_ids.yaml``."""

    id: str
    reason: str
    replaced_by: str | None = None
    since: str | None = None


def _load_deprecated_registry(registry_path: Path | None = None) -> list[DeprecatedEntry]:
    """Load the deprecated study-ID YAML file.

    Returns an empty list if the file is missing or malformed (so the engine
    can still run without a populated registry).
    """
    path = Path(registry_path or _DEFAULT_REGISTRY_PATH)
    if not path.exists():
        _log.warning("deprecated_registry_missing", path=str(path))
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = raw.get("deprecated", []) if isinstance(raw, dict) else []
        return [
            DeprecatedEntry(
                id=e["id"],
                reason=e.get("reason", ""),
                replaced_by=e.get("replaced_by"),
                since=e.get("since"),
            )
            for e in entries
            if isinstance(e, dict) and "id" in e
        ]
    except Exception as exc:
        _log.warning("deprecated_registry_load_error", error=str(exc))
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Individual detection functions
# ─────────────────────────────────────────────────────────────────────────────


def detect_blue_text_no_link(
    parsed: DocxDocument,
    *,
    document_path: str | Path,
) -> list[Anomaly]:
    """Return anomalies for blue-coloured runs that carry no hyperlink.

    Delegates the blue-run enumeration to
    :func:`parsing.docx_parser.candidate_blue_runs` (which already applies the
    configured RGB tolerance) so the heuristic is defined in exactly one place.
    """
    from hyperlink_engine.core.parsing.docx_parser import candidate_blue_runs  # lazy import

    doc_str = str(document_path)
    anomalies: list[Anomaly] = []

    for para_idx, run_idx, run in candidate_blue_runs(parsed):
        anomalies.append(
            Anomaly(
                kind=AnomalyKind.BLUE_TEXT_NO_LINK,
                severity=AnomalySeverity.WARNING,
                document=doc_str,
                location=RunLocation(
                    paragraph_index=para_idx,
                    run_index=run_idx,
                    char_start=run.char_offset_in_paragraph,
                    char_end=run.char_offset_in_paragraph + max(1, len(run.text)),
                ),
                text=run.text,
                suggested_fix=(
                    f"Run at paragraph {para_idx}, run {run_idx} appears blue "
                    "but has no hyperlink. Either add a hyperlink or change the "
                    "color to black."
                ),
                confidence=0.85,
            )
        )
    return anomalies


def detect_orphaned_references(
    detection_texts: Sequence[str],
    link_records: Sequence[LinkRecord],
    *,
    document_path: str | Path,
) -> list[Anomaly]:
    """Detect references that were detected but never turned into a link.

    A reference is considered orphaned when it does not match any ``link_text``
    in ``link_records`` and has no resolved target.

    Parameters
    ----------
    detection_texts:
        Every reference text string produced by the extraction layer for this
        document (typically ``[det["text"] for det in detection_record["detections"]]``).
    link_records:
        The validated link records produced after injection (from the pipeline).
    document_path:
        Path of the source document (for the anomaly ``document`` field).
    """
    doc_str = str(document_path)
    linked_texts = {r.link_text for r in link_records}
    anomalies: list[Anomaly] = []
    for text in detection_texts:
        if text not in linked_texts:
            anomalies.append(
                Anomaly(
                    kind=AnomalyKind.ORPHANED_REFERENCE,
                    severity=AnomalySeverity.WARNING,
                    document=doc_str,
                    text=text,
                    suggested_fix=(
                        f'Reference "{text}" was detected but no hyperlink target '
                        "could be resolved. Verify the referenced section/document "
                        "exists in the dossier."
                    ),
                    confidence=0.80,
                )
            )
    return anomalies


def detect_deprecated_study_ids(
    text: str,
    *,
    document_path: str | Path,
    registry: list[DeprecatedEntry] | None = None,
    registry_path: Path | None = None,
) -> list[Anomaly]:
    """Scan ``text`` for any study ID listed in the deprecated registry.

    Parameters
    ----------
    text:
        The full text of the document (or a concatenated paragraph buffer).
    document_path:
        Source document path for the anomaly record.
    registry:
        Pre-loaded registry (pass this in hot-path code to avoid re-reading YAML).
    registry_path:
        Override the YAML registry file path (used in tests).
    """
    if registry is None:
        registry = _load_deprecated_registry(registry_path)

    doc_str = str(document_path)
    anomalies: list[Anomaly] = []

    for entry in registry:
        # Use word-boundary matching so "SP-2019-001B" doesn't match "SP-2019-001".
        pattern = re.escape(entry.id)
        for m in re.finditer(rf"(?<![A-Z0-9-]){pattern}(?![A-Z0-9-])", text):
            fix_msg = f'Study ID "{entry.id}" is deprecated ({entry.reason}).'
            if entry.replaced_by:
                fix_msg += f' Consider replacing with "{entry.replaced_by}".'
            anomalies.append(
                Anomaly(
                    kind=AnomalyKind.DEPRECATED_STUDY_ID,
                    severity=AnomalySeverity.BLOCKER,
                    document=doc_str,
                    text=m.group(0),
                    suggested_fix=fix_msg,
                    confidence=0.99,
                )
            )
    return anomalies


def detect_suspicious_targets(
    link_records: Sequence[LinkRecord],
    *,
    document_path: str | Path,
    similarity_threshold: float | None = None,
) -> list[Anomaly]:
    """Flag links where the visible text and the anchor name are inconsistent.

    Uses a simple heuristic: extract all digit sequences from the link text
    and from the target anchor; if they share no common numbers the link is
    suspicious (e.g., "Section 5.3.2" pointing to anchor "section_ref_4_1_0").

    Parameters
    ----------
    link_records:
        Validated link records for this document.
    document_path:
        Source document path.
    similarity_threshold:
        Override the settings ``target_similarity_threshold`` (used in tests).
    """
    settings = get_settings()
    threshold = similarity_threshold or settings.target_similarity_threshold
    doc_str = str(document_path)
    anomalies: list[Anomaly] = []

    _num_re = re.compile(r"\d+")

    for record in link_records:
        # Only check INTERNAL_BOOKMARK / CROSS_MODULE links that have an anchor.
        if not record.target_anchor:
            continue
        if record.status == LinkStatus.BROKEN:
            # Already flagged as broken; don't double-report.
            continue

        text_nums = set(_num_re.findall(record.link_text.lower()))
        anchor_nums = set(_num_re.findall(record.target_anchor.lower()))

        if not text_nums:
            # Link text has no numbers → nothing to compare.
            continue

        overlap = text_nums & anchor_nums
        jaccard = len(overlap) / len(text_nums | anchor_nums) if (text_nums | anchor_nums) else 1.0

        if jaccard < (1.0 - threshold):
            anomalies.append(
                Anomaly(
                    kind=AnomalyKind.SUSPICIOUS_TARGET,
                    severity=AnomalySeverity.WARNING,
                    document=doc_str,
                    text=record.link_text,
                    suggested_fix=(
                        f'Link text "{record.link_text}" points to anchor '
                        f'"{record.target_anchor}" — the numeric identifiers '
                        "don't match. Verify the intended destination."
                    ),
                    confidence=round(1.0 - jaccard, 3),
                )
            )
    return anomalies


# ─────────────────────────────────────────────────────────────────────────────
# AnomalyReport — per-document result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class AnomalyReport:
    """All anomalies detected in a single document."""

    document: str
    anomalies: list[Anomaly] = field(default_factory=list)

    # ── Convenience aggregates ─────────────────────────────────────────

    @property
    def blocker_count(self) -> int:
        return sum(1 for a in self.anomalies if a.severity == AnomalySeverity.BLOCKER)

    @property
    def warning_count(self) -> int:
        return sum(1 for a in self.anomalies if a.severity == AnomalySeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for a in self.anomalies if a.severity == AnomalySeverity.INFO)

    @property
    def total(self) -> int:
        return len(self.anomalies)

    def by_kind(self, kind: AnomalyKind) -> list[Anomaly]:
        return [a for a in self.anomalies if a.kind == kind]


# ─────────────────────────────────────────────────────────────────────────────
# High-level entry point
# ─────────────────────────────────────────────────────────────────────────────


def run_anomaly_detection(
    *,
    document_path: str | Path,
    parsed_doc: DocxDocument | None = None,
    detection_texts: Sequence[str] | None = None,
    link_records: Sequence[LinkRecord] | None = None,
    full_text: str | None = None,
    deprecated_registry: list[DeprecatedEntry] | None = None,
    deprecated_registry_path: Path | None = None,
    check_blue_text: bool = True,
    check_orphans: bool = True,
    check_deprecated: bool = True,
    check_suspicious: bool = True,
) -> AnomalyReport:
    """Run all enabled anomaly checks and return a combined :class:`AnomalyReport`.

    Parameters
    ----------
    document_path:
        Source document path (used in anomaly records).
    parsed_doc:
        Parsed :class:`models.DocxDocument` — required for blue-text check.
    detection_texts:
        List of reference texts produced by the extraction layer — required for
        orphan check.
    link_records:
        Validated link records after injection — required for orphan + suspicious
        target checks.
    full_text:
        Complete document text — required for deprecated-ID check.
    deprecated_registry:
        Pre-loaded deprecated-ID list (avoids repeated YAML reads in batch mode).
    deprecated_registry_path:
        Override path for the YAML registry (used in tests).
    check_*:
        Fine-grained toggles for each detection category.
    """
    doc_str = str(document_path)
    all_anomalies: list[Anomaly] = []

    # 1 — Blue text without hyperlink
    if check_blue_text and parsed_doc is not None:
        blue = detect_blue_text_no_link(parsed_doc, document_path=doc_str)
        all_anomalies.extend(blue)
        _log.debug("blue_text_anomalies", count=len(blue), document=doc_str)

    # 2 — Orphaned references
    if check_orphans and detection_texts is not None and link_records is not None:
        orphans = detect_orphaned_references(
            detection_texts, link_records, document_path=doc_str
        )
        all_anomalies.extend(orphans)
        _log.debug("orphaned_ref_anomalies", count=len(orphans), document=doc_str)

    # 3 — Circular references (graph-level; surfaced separately via cross_module_integrity)
    #     We emit a placeholder here if the caller injected pre-computed circular
    #     Anomaly objects (from detect_circular_refs).  The batch runner
    #     consolidates them after the graph audit.

    # 4 — Deprecated Study IDs
    if check_deprecated and full_text is not None:
        deprecated = detect_deprecated_study_ids(
            full_text,
            document_path=doc_str,
            registry=deprecated_registry,
            registry_path=deprecated_registry_path,
        )
        all_anomalies.extend(deprecated)
        _log.debug("deprecated_id_anomalies", count=len(deprecated), document=doc_str)

    # 5 — Suspicious link targets
    if check_suspicious and link_records is not None:
        suspicious = detect_suspicious_targets(link_records, document_path=doc_str)
        all_anomalies.extend(suspicious)
        _log.debug("suspicious_target_anomalies", count=len(suspicious), document=doc_str)

    _log.info(
        "anomaly_detection_complete",
        document=doc_str,
        total=len(all_anomalies),
        blockers=sum(1 for a in all_anomalies if a.severity == AnomalySeverity.BLOCKER),
        warnings=sum(1 for a in all_anomalies if a.severity == AnomalySeverity.WARNING),
    )
    return AnomalyReport(document=doc_str, anomalies=all_anomalies)


# ─────────────────────────────────────────────────────────────────────────────
# Dossier-level anomaly aggregation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DossierAnomalySummary:
    """Aggregated anomaly counts across all documents in a dossier batch."""

    per_document: list[AnomalyReport] = field(default_factory=list)

    @property
    def total_anomalies(self) -> int:
        return sum(r.total for r in self.per_document)

    @property
    def total_blockers(self) -> int:
        return sum(r.blocker_count for r in self.per_document)

    @property
    def total_warnings(self) -> int:
        return sum(r.warning_count for r in self.per_document)

    @property
    def all_anomalies(self) -> list[Anomaly]:
        out: list[Anomaly] = []
        for r in self.per_document:
            out.extend(r.anomalies)
        return out

    def by_kind(self, kind: AnomalyKind) -> list[Anomaly]:
        return [a for a in self.all_anomalies if a.kind == kind]

    def by_severity(self, severity: AnomalySeverity) -> list[Anomaly]:
        return [a for a in self.all_anomalies if a.severity == severity]

    def documents_with_blockers(self) -> list[str]:
        return [r.document for r in self.per_document if r.blocker_count > 0]


def aggregate_anomaly_reports(reports: list[AnomalyReport]) -> DossierAnomalySummary:
    """Combine per-document anomaly reports into a dossier-level summary."""
    return DossierAnomalySummary(per_document=reports)
