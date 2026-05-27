"""Unit tests for reporting/gate_review_pdf.py (W12.2)."""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pytest

from hyperlink_engine.audit.trail import get_audit_trail, reset_audit_trail
from hyperlink_engine.reporting.gate_review_pdf import (
    Approver,
    AuditEntry,
    GateReviewBundle,
    record_gate_signoff,
    write_gate_review_pdf,
)
from hyperlink_engine.reporting.readiness_score import ModuleScore, ReadinessResult


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_audit(tmp_path: Path) -> None:
    reset_audit_trail()
    get_audit_trail(tmp_path / "audit.jsonl")
    yield
    reset_audit_trail()


def _make_readiness(score: float = 88.0) -> ReadinessResult:
    grade = "A" if score >= 95 else "B" if score >= 85 else "C" if score >= 70 else "D"
    return ReadinessResult(
        overall_score=score,
        grade=grade,
        total_links=2147,
        broken_links=13,
        orphaned_refs=9,
        style_violations=2,
        blocker_anomalies=13,
        warning_anomalies=34,
        document_count=500,
        module_scores=[
            ModuleScore(
                module="m2", score=92.0, broken_links=2, orphaned_refs=1,
                style_violations=0, blocker_anomalies=1, warning_anomalies=5,
                document_count=120,
            ),
            ModuleScore(
                module="m5", score=74.0, broken_links=8, orphaned_refs=4,
                style_violations=1, blocker_anomalies=7, warning_anomalies=18,
                document_count=180,
            ),
        ],
        summary="Mock summary",
    )


def _make_approvers() -> list[Approver]:
    return [
        Approver(name="V. Iyer", role="QC Lead", status="signed",
                 timestamp="2026-05-27 14:38", initials="VI",
                 signature_hash="0xa3f1c8…"),
        Approver(name="D. Park", role="Author", status="signed",
                 timestamp="2026-05-27 14:42", initials="DP"),
        Approver(name="M. Tanaka", role="Regulatory Affairs", status="pending",
                 timestamp=None, initials="MT"),
        Approver(name="S. Bhatt", role="Submission Gate", status="blocked",
                 timestamp=None, initials="SB"),
    ]


def _make_audit() -> list[AuditEntry]:
    return [
        AuditEntry(when="2026-05-27 14:01:12", actor="Engine",
                   action="34 anomalies flagged", hash="0x1c8a…",
                   detail="Style mutation cluster"),
        AuditEntry(when="2026-05-27 14:21:33", actor="V. Iyer",
                   action="Resolved 4 blockers in m2.5.1", hash="0x4e2d…"),
        AuditEntry(when="2026-05-27 14:38:55", actor="V. Iyer",
                   action="Signed as QC Lead", hash="0xa3f1…",
                   detail="AKID: PIV-2918 · ECDSA-P256"),
    ]


# ── write_gate_review_pdf ────────────────────────────────────────────────────


def test_pdf_is_created_at_path(tmp_path: Path) -> None:
    out = tmp_path / "gate.pdf"
    result = write_gate_review_pdf(
        path=out,
        dossier_id="NDA-215842",
        sponsor="SunPharma",
        readiness=_make_readiness(),
        approvers=_make_approvers(),
        audit_events=_make_audit(),
    )
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 1000  # non-trivial PDF


def test_pdf_is_a_real_pdf(tmp_path: Path) -> None:
    out = tmp_path / "gate.pdf"
    write_gate_review_pdf(
        path=out,
        dossier_id="NDA-215842",
        sponsor="SunPharma",
        readiness=_make_readiness(),
        approvers=_make_approvers(),
        audit_events=_make_audit(),
    )
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 1
        text = doc[0].get_text()
        # Sanity: dossier identity + key labels surface in the PDF
        assert "NDA-215842" in text
        assert "SunPharma" in text
        assert "SUBMISSION GATE REVIEW" in text
        assert "READINESS" in text
    finally:
        doc.close()


def test_pdf_contains_readiness_score(tmp_path: Path) -> None:
    out = tmp_path / "score.pdf"
    write_gate_review_pdf(
        path=out,
        dossier_id="NDA-215842",
        sponsor="SunPharma",
        readiness=_make_readiness(score=92.5),
    )
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
        assert "92.5" in text
        assert "Grade B" in text
    finally:
        doc.close()


def test_pdf_contains_approvers(tmp_path: Path) -> None:
    out = tmp_path / "ap.pdf"
    write_gate_review_pdf(
        path=out,
        dossier_id="NDA-001",
        sponsor="SunPharma",
        approvers=_make_approvers(),
    )
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
        assert "V. Iyer" in text
        assert "QC Lead" in text
        assert "APPROVER CHAIN" in text
    finally:
        doc.close()


def test_pdf_contains_audit_events(tmp_path: Path) -> None:
    out = tmp_path / "audit.pdf"
    write_gate_review_pdf(
        path=out,
        dossier_id="NDA-001",
        sponsor="SunPharma",
        audit_events=_make_audit(),
    )
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
        assert "AUDIT TRAIL" in text
        assert "Signed as QC Lead" in text
    finally:
        doc.close()


def test_pdf_writes_audit_event(tmp_path: Path) -> None:
    out = tmp_path / "ev.pdf"
    write_gate_review_pdf(
        path=out, dossier_id="NDA-001", sponsor="SunPharma"
    )
    records = get_audit_trail().read_all()
    assert any(r["action"] == "gate_review_pdf_exported" for r in records)


def test_pdf_compliance_footer_present(tmp_path: Path) -> None:
    out = tmp_path / "footer.pdf"
    write_gate_review_pdf(
        path=out, dossier_id="NDA-001", sponsor="SunPharma"
    )
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
        assert "21 CFR Part 11" in text
        assert "On-prem inference" in text
    finally:
        doc.close()


def test_pdf_no_readiness_input(tmp_path: Path) -> None:
    """Gracefully renders even when readiness=None."""
    out = tmp_path / "noscore.pdf"
    write_gate_review_pdf(
        path=out, dossier_id="NDA-001", sponsor="SunPharma", readiness=None
    )
    doc = fitz.open(str(out))
    try:
        text = doc[0].get_text()
        assert "not available" in text or "Readiness score" in text
    finally:
        doc.close()


def test_pdf_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "deep" / "nested" / "gate.pdf"
    write_gate_review_pdf(
        path=out, dossier_id="NDA-001", sponsor="SunPharma"
    )
    assert out.exists()


# ── record_gate_signoff ──────────────────────────────────────────────────────


def test_record_signoff_writes_audit_event() -> None:
    record_gate_signoff(
        dossier_id="NDA-001",
        approver_name="V. Iyer",
        approver_role="QC Lead",
        signature_hash="0xa3f1c8",
        details={"notes": "All blockers resolved"},
    )
    records = get_audit_trail().read_all()
    relevant = [r for r in records if r["action"] == "gate_review_signed"]
    assert len(relevant) == 1
    assert "QC Lead" in relevant[0]["actor"]
    assert relevant[0]["document"] == "NDA-001"
    assert relevant[0]["details"]["signature_hash"] == "0xa3f1c8"


def test_record_signoff_without_hash() -> None:
    record_gate_signoff(
        dossier_id="NDA-001",
        approver_name="Test User",
        approver_role="Author",
    )
    records = get_audit_trail().read_all()
    relevant = [r for r in records if r["action"] == "gate_review_signed"]
    assert len(relevant) == 1


# ── GateReviewBundle dataclass ───────────────────────────────────────────────


def test_bundle_default_factory() -> None:
    b = GateReviewBundle(dossier_id="x", sponsor="y")
    assert b.approvers == []
    assert b.audit_events == []
    assert b.submission_type == "NDA"
    assert b.generated_at is not None
