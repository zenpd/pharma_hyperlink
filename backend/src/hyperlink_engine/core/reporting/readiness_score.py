"""W8.2 — Submission Readiness Score.

Computes a 0–100 score that estimates how ready a dossier batch is for
regulatory submission based on link health and anomaly severity.

The default formula (configurable via the ``weights`` parameter)::

    score = 100
      - 5  × broken_links
      - 2  × orphaned_refs
      - 3  × style_violations
      - 10 × blocker_anomalies
      - 2  × warning_anomalies   (added; warnings aren't free)

The score is clamped to [0, 100]. Per-module sub-scores use the same
formula applied only to the links/anomalies in that module's documents.

All results are returned as :class:`ReadinessResult` / :class:`ModuleScore`
Pydantic models so they can be serialised to JSON for the dashboard API.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.validation.anomaly_detector import (
    DossierAnomalySummary,
)
from hyperlink_engine.models import AnomalyKind
from hyperlink_engine.workers.batch_runner import BatchRunReport

_log = get_logger("reporting.readiness_score")


# ─────────────────────────────────────────────────────────────────────────────
# Scoring weights
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScoringWeights:
    """Penalty weights applied per issue count.

    All fields are *points deducted per occurrence*.
    """

    per_broken_link: float = 5.0
    per_orphaned_ref: float = 2.0
    per_style_violation: float = 3.0
    per_blocker_anomaly: float = 10.0
    per_warning_anomaly: float = 2.0

    @classmethod
    def default(cls) -> "ScoringWeights":
        return cls()

    @classmethod
    def strict(cls) -> "ScoringWeights":
        """Higher penalties — suitable for NDA-class submissions."""
        return cls(
            per_broken_link=8.0,
            per_orphaned_ref=3.0,
            per_style_violation=4.0,
            per_blocker_anomaly=15.0,
            per_warning_anomaly=3.0,
        )

    @classmethod
    def lenient(cls) -> "ScoringWeights":
        """Lower penalties — useful for early-draft dossier reviews."""
        return cls(
            per_broken_link=3.0,
            per_orphaned_ref=1.0,
            per_style_violation=1.0,
            per_blocker_anomaly=5.0,
            per_warning_anomaly=1.0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Result models
# ─────────────────────────────────────────────────────────────────────────────


class ModuleScore(BaseModel):
    """Readiness score for one CTD module (e.g., 'm2', 'm5.3')."""

    module: str
    score: float = Field(ge=0.0, le=100.0)
    broken_links: int = Field(ge=0)
    orphaned_refs: int = Field(ge=0)
    style_violations: int = Field(ge=0)
    blocker_anomalies: int = Field(ge=0)
    warning_anomalies: int = Field(ge=0)
    document_count: int = Field(ge=0)


class ReadinessResult(BaseModel):
    """Overall and per-module submission readiness scores."""

    overall_score: float = Field(ge=0.0, le=100.0)
    grade: str  # A / B / C / D / F

    # Inputs used to compute the score
    total_links: int = Field(ge=0)
    broken_links: int = Field(ge=0)
    orphaned_refs: int = Field(ge=0)
    style_violations: int = Field(ge=0)
    blocker_anomalies: int = Field(ge=0)
    warning_anomalies: int = Field(ge=0)
    document_count: int = Field(ge=0)

    # Detailed per-module breakdown (may be empty if module info not available)
    module_scores: list[ModuleScore] = Field(default_factory=list)

    # Human-readable summary
    summary: str = ""

    @property
    def is_submission_ready(self) -> bool:
        """True when score ≥ 90 AND zero blockers."""
        return self.overall_score >= 90.0 and self.blocker_anomalies == 0

    @property
    def broken_rate(self) -> float:
        if not self.total_links:
            return 0.0
        return self.broken_links / self.total_links


def _grade(score: float) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    if score >= 55:
        return "D"
    return "F"


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _compute_score(
    *,
    broken_links: int,
    orphaned_refs: int,
    style_violations: int,
    blocker_anomalies: int,
    warning_anomalies: int,
    weights: ScoringWeights,
) -> float:
    deduction = (
        broken_links * weights.per_broken_link
        + orphaned_refs * weights.per_orphaned_ref
        + style_violations * weights.per_style_violation
        + blocker_anomalies * weights.per_blocker_anomaly
        + warning_anomalies * weights.per_warning_anomaly
    )
    return _clamp(100.0 - deduction)


# ─────────────────────────────────────────────────────────────────────────────
# Main API
# ─────────────────────────────────────────────────────────────────────────────


def compute_readiness_score(
    batch_report: BatchRunReport,
    anomaly_summary: DossierAnomalySummary | None = None,
    *,
    weights: ScoringWeights | None = None,
    style_violations: int = 0,
    module_map: dict[str, list[str]] | None = None,
) -> ReadinessResult:
    """Compute the overall submission readiness score.

    Parameters
    ----------
    batch_report:
        The :class:`pipeline.batch_runner.BatchRunReport` from
        :func:`pipeline.batch_runner.run_batch`.
    anomaly_summary:
        Aggregated anomaly data from the anomaly detector.  Pass ``None`` to
        score based on link health only.
    weights:
        Override the default :class:`ScoringWeights`.
    style_violations:
        Count of Dosscriber style-mutation violations (from style_preserver diffs).
    module_map:
        Optional mapping of module label → list of document paths in that module.
        When provided, per-module sub-scores are computed.
    """
    w = weights or ScoringWeights.default()

    # Aggregate counts from batch report
    broken_links = batch_report.total_broken
    total_links = batch_report.total_links
    doc_count = batch_report.documents_processed

    # Aggregate anomaly counts
    blockers = 0
    warnings = 0
    orphaned = 0

    if anomaly_summary is not None:
        blockers = anomaly_summary.total_blockers
        warnings = anomaly_summary.total_warnings
        orphaned = len(anomaly_summary.by_kind(AnomalyKind.ORPHANED_REFERENCE))

    score = _compute_score(
        broken_links=broken_links,
        orphaned_refs=orphaned,
        style_violations=style_violations,
        blocker_anomalies=blockers,
        warning_anomalies=warnings,
        weights=w,
    )
    grade = _grade(score)

    # Build per-module breakdown when the caller supplies a module map
    module_scores: list[ModuleScore] = []
    if module_map and anomaly_summary is not None:
        for mod_label, doc_paths in module_map.items():
            doc_set = set(doc_paths)
            mod_reports = [
                r for r in anomaly_summary.per_document if r.document in doc_set
            ]
            mod_blockers = sum(r.blocker_count for r in mod_reports)
            mod_warnings = sum(r.warning_count for r in mod_reports)
            mod_orphans = sum(
                len(r.by_kind(AnomalyKind.ORPHANED_REFERENCE)) for r in mod_reports
            )

            # Link counts per module: approximate from batch results
            # (a more precise breakdown requires per-doc link tracking)
            mod_broken = 0
            for result in batch_report.results:
                if str(result.source_path) in doc_set:
                    mod_broken += result.broken_count

            mod_score = _compute_score(
                broken_links=mod_broken,
                orphaned_refs=mod_orphans,
                style_violations=0,
                blocker_anomalies=mod_blockers,
                warning_anomalies=mod_warnings,
                weights=w,
            )
            module_scores.append(
                ModuleScore(
                    module=mod_label,
                    score=mod_score,
                    broken_links=mod_broken,
                    orphaned_refs=mod_orphans,
                    style_violations=0,
                    blocker_anomalies=mod_blockers,
                    warning_anomalies=mod_warnings,
                    document_count=len(doc_paths),
                )
            )

    summary = _build_summary(
        score=score,
        grade=grade,
        broken_links=broken_links,
        total_links=total_links,
        blockers=blockers,
        warnings=warnings,
        doc_count=doc_count,
    )

    result = ReadinessResult(
        overall_score=round(score, 2),
        grade=grade,
        total_links=total_links,
        broken_links=broken_links,
        orphaned_refs=orphaned,
        style_violations=style_violations,
        blocker_anomalies=blockers,
        warning_anomalies=warnings,
        document_count=doc_count,
        module_scores=module_scores,
        summary=summary,
    )

    _log.info(
        "readiness_score_computed",
        score=result.overall_score,
        grade=grade,
        broken=broken_links,
        blockers=blockers,
        warnings=warnings,
        docs=doc_count,
        submission_ready=result.is_submission_ready,
    )
    return result


def _build_summary(
    *,
    score: float,
    grade: str,
    broken_links: int,
    total_links: int,
    blockers: int,
    warnings: int,
    doc_count: int,
) -> str:
    lines = [
        f"Submission Readiness Score: {score:.1f}/100 (Grade {grade})",
        f"  Documents processed : {doc_count}",
        f"  Links total         : {total_links}",
        f"  Broken links        : {broken_links}",
        f"  Blocker anomalies   : {blockers}",
        f"  Warning anomalies   : {warnings}",
    ]
    if score >= 90 and blockers == 0:
        lines.append("  → SUBMISSION READY ✓")
    elif blockers > 0:
        lines.append(f"  → NOT READY: {blockers} blocker(s) must be resolved.")
    elif broken_links > 0:
        lines.append(f"  → NOT READY: {broken_links} broken link(s) must be fixed.")
    else:
        lines.append("  → CONDITIONAL: review warnings before final submission.")
    return "\n".join(lines)
