"""Unit tests for reporting/readiness_score.py (W8.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hyperlink_engine.core.reporting.readiness_score import (
    ReadinessResult,
    ScoringWeights,
    _compute_score,
    _grade,
    compute_readiness_score,
)
from hyperlink_engine.core.validation.anomaly_detector import (
    AnomalyReport,
    DossierAnomalySummary,
    aggregate_anomaly_reports,
)
from hyperlink_engine.models import AnomalyKind, AnomalySeverity
from hyperlink_engine.workers.batch_runner import BatchRunReport

# ── Helper ────────────────────────────────────────────────────────────────────


def _make_batch_report(
    links: int = 100,
    broken: int = 0,
    docs: int = 10,
) -> BatchRunReport:
    report = BatchRunReport()
    report._total_links = links
    report._total_broken = broken
    report._documents_processed = docs
    # Use real property accessors; override via monkey-patch
    report.__class__.total_links = property(lambda self: self._total_links)
    report.__class__.total_broken = property(lambda self: self._total_broken)
    report.__class__.documents_processed = property(lambda self: self._documents_processed)
    return report


def _make_summary(blockers: int = 0, warnings: int = 0, orphans: int = 0) -> DossierAnomalySummary:
    from hyperlink_engine.models import Anomaly

    reports: list[AnomalyReport] = []
    for _ in range(blockers):
        reports.append(
            AnomalyReport(
                document="doc.docx",
                anomalies=[
                    Anomaly(
                        kind=AnomalyKind.DEPRECATED_STUDY_ID,
                        severity=AnomalySeverity.BLOCKER,
                        document="doc.docx",
                        text="x",
                        confidence=0.99,
                    )
                ],
            )
        )
    for _ in range(warnings):
        reports.append(
            AnomalyReport(
                document="doc.docx",
                anomalies=[
                    Anomaly(
                        kind=AnomalyKind.BLUE_TEXT_NO_LINK,
                        severity=AnomalySeverity.WARNING,
                        document="doc.docx",
                        text="y",
                        confidence=0.85,
                    )
                ],
            )
        )
    for _ in range(orphans):
        reports.append(
            AnomalyReport(
                document="doc.docx",
                anomalies=[
                    Anomaly(
                        kind=AnomalyKind.ORPHANED_REFERENCE,
                        severity=AnomalySeverity.WARNING,
                        document="doc.docx",
                        text="z",
                        confidence=0.80,
                    )
                ],
            )
        )
    return aggregate_anomaly_reports(reports)


# ── _grade ────────────────────────────────────────────────────────────────────


def test_grade_A() -> None:
    assert _grade(98.0) == "A"


def test_grade_B() -> None:
    assert _grade(90.0) == "B"


def test_grade_C() -> None:
    assert _grade(75.0) == "C"


def test_grade_D() -> None:
    assert _grade(60.0) == "D"


def test_grade_F() -> None:
    assert _grade(40.0) == "F"


# ── _compute_score ────────────────────────────────────────────────────────────


def test_perfect_score() -> None:
    w = ScoringWeights.default()
    score = _compute_score(
        broken_links=0,
        orphaned_refs=0,
        style_violations=0,
        blocker_anomalies=0,
        warning_anomalies=0,
        weights=w,
    )
    assert score == 100.0


def test_score_clamped_at_zero() -> None:
    w = ScoringWeights.default()
    score = _compute_score(
        broken_links=100,
        orphaned_refs=100,
        style_violations=100,
        blocker_anomalies=100,
        warning_anomalies=100,
        weights=w,
    )
    assert score == 0.0


def test_score_deduction_formula() -> None:
    w = ScoringWeights(
        per_broken_link=5.0,
        per_blocker_anomaly=10.0,
        per_orphaned_ref=2.0,
        per_style_violation=3.0,
        per_warning_anomaly=2.0,
    )
    # 2 broken (10) + 1 blocker (10) = 20 points deducted
    score = _compute_score(
        broken_links=2,
        orphaned_refs=0,
        style_violations=0,
        blocker_anomalies=1,
        warning_anomalies=0,
        weights=w,
    )
    assert score == 80.0


# ── ScoringWeights variants ────────────────────────────────────────────────


def test_strict_weights_have_higher_per_broken() -> None:
    assert ScoringWeights.strict().per_broken_link > ScoringWeights.default().per_broken_link


def test_lenient_weights_have_lower_per_blocker() -> None:
    assert ScoringWeights.lenient().per_blocker_anomaly < ScoringWeights.default().per_blocker_anomaly


# ── compute_readiness_score ───────────────────────────────────────────────────


def test_perfect_dossier_is_submission_ready(tmp_path: Path) -> None:
    from docx import Document

    from hyperlink_engine.workers.batch_runner import (
        DossierBatchDescriptor,
        run_batch,
    )
    from hyperlink_engine.workers.cache import ExtractorConfig

    src = tmp_path / "doc.docx"
    doc = Document()
    doc.add_paragraph("No refs here")
    doc.save(str(src))

    desc = DossierBatchDescriptor(
        sources=[src],
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
        extractor_config=ExtractorConfig.regex_only(),
    )
    report = run_batch(desc, mode="sync")
    result = compute_readiness_score(report, anomaly_summary=None)
    assert isinstance(result, ReadinessResult)
    assert result.overall_score == 100.0
    assert result.grade == "A"
    assert result.is_submission_ready


def test_blockers_prevent_submission_readiness() -> None:
    from hyperlink_engine.workers.batch_runner import BatchRunReport

    report = BatchRunReport()
    summary = _make_summary(blockers=1)
    result = compute_readiness_score(report, anomaly_summary=summary)
    assert not result.is_submission_ready


def test_summary_string_not_empty(tmp_path: Path) -> None:
    from hyperlink_engine.workers.batch_runner import BatchRunReport

    report = BatchRunReport()
    result = compute_readiness_score(report, anomaly_summary=None)
    assert len(result.summary) > 0


def test_readiness_with_orphans(tmp_path: Path) -> None:
    from hyperlink_engine.workers.batch_runner import BatchRunReport

    report = BatchRunReport()
    summary = _make_summary(orphans=3)
    result = compute_readiness_score(report, anomaly_summary=summary)
    assert result.orphaned_refs == 3
    # Orphaned refs are also counted as warnings in the summary, so both
    # penalties apply: 3 × per_orphaned_ref(2) + 3 × per_warning(2) = 12
    # → score = 100 - 12 = 88.
    assert result.overall_score == pytest.approx(88.0, abs=0.1)


# ── ReadinessResult.broken_rate ───────────────────────────────────────────────


def test_broken_rate_no_links() -> None:
    result = ReadinessResult(
        overall_score=100.0,
        grade="A",
        total_links=0,
        broken_links=0,
        orphaned_refs=0,
        style_violations=0,
        blocker_anomalies=0,
        warning_anomalies=0,
        document_count=0,
    )
    assert result.broken_rate == 0.0


def test_broken_rate_calculated() -> None:
    result = ReadinessResult(
        overall_score=80.0,
        grade="B",
        total_links=100,
        broken_links=5,
        orphaned_refs=0,
        style_violations=0,
        blocker_anomalies=0,
        warning_anomalies=0,
        document_count=10,
    )
    assert result.broken_rate == pytest.approx(0.05)
