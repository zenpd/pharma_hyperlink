"""Unit tests for validation/viewer_compat.py (W9.2 + W9.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from hyperlink_engine.core.validation.viewer_compat import (
    AcrobatStubChecker,
    EmaEspreStubChecker,
    FdaEsgStubChecker,
    PdfJsHeadlessChecker,
    PmdaGatewayStubChecker,
    StructuralChecker,
    ViewerCheckStatus,
    ViewerCompatReport,
    ViewerLinkResult,
    _classify_link_kind,
    _enumerate_links_via_fitz,
    default_checkers,
    run_viewer_compatibility,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A real but tiny PDF with one external link annotation."""
    import fitz  # type: ignore

    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample with a link")
    # Add an external URL link annotation
    rect = fitz.Rect(72, 60, 200, 80)
    page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": "https://example.com"})
    # And an internal page-jump link
    page.insert_link(
        {"kind": fitz.LINK_GOTO, "from": rect, "page": 0, "to": fitz.Point(0, 0)}
    )
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def empty_pdf(tmp_path: Path) -> Path:
    """A PDF with no link annotations."""
    import fitz  # type: ignore

    path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


# ── _classify_link_kind ───────────────────────────────────────────────────────


def test_classify_link_kind_external() -> None:
    assert _classify_link_kind({"uri": "https://x"}) == "external"


def test_classify_link_kind_named_dest() -> None:
    assert _classify_link_kind({"nameddest": "sec_1"}) == "named_dest"


def test_classify_link_kind_internal() -> None:
    assert _classify_link_kind({"page": 2}) == "internal"


def test_classify_link_kind_cross_doc() -> None:
    assert _classify_link_kind({"file": "other.pdf"}) == "cross_doc"


def test_classify_link_kind_unknown() -> None:
    assert _classify_link_kind({}) == "unknown"


# ── _enumerate_links_via_fitz ────────────────────────────────────────────────


def test_enumerate_links_finds_links(sample_pdf: Path) -> None:
    links = _enumerate_links_via_fitz(sample_pdf)
    assert len(links) >= 1


def test_enumerate_links_handles_empty(empty_pdf: Path) -> None:
    links = _enumerate_links_via_fitz(empty_pdf)
    assert links == []


# ── StructuralChecker ─────────────────────────────────────────────────────────


def test_structural_checker_no_qpdf_returns_unverified(sample_pdf: Path) -> None:
    checker = StructuralChecker(qpdf_path=None)
    with patch("shutil.which", return_value=None):
        rows = checker.check(sample_pdf)
    assert len(rows) == 1
    assert rows[0].status == ViewerCheckStatus.UNVERIFIED


def test_structural_checker_qpdf_ok(sample_pdf: Path) -> None:
    """When qpdf returns rc=0, the result is OK."""
    fake_run = subprocess.CompletedProcess(
        args=["qpdf", "--check", str(sample_pdf)], returncode=0, stdout="", stderr=""
    )
    with patch("shutil.which", return_value="/usr/bin/qpdf"), patch(
        "subprocess.run", return_value=fake_run
    ):
        rows = StructuralChecker().check(sample_pdf)
    assert rows[0].status == ViewerCheckStatus.OK


def test_structural_checker_qpdf_failure(sample_pdf: Path) -> None:
    fake_run = subprocess.CompletedProcess(
        args=["qpdf", "--check", str(sample_pdf)],
        returncode=2,
        stdout="",
        stderr="bad xref",
    )
    with patch("shutil.which", return_value="/usr/bin/qpdf"), patch(
        "subprocess.run", return_value=fake_run
    ):
        rows = StructuralChecker().check(sample_pdf)
    assert rows[0].status == ViewerCheckStatus.STRUCTURAL_ERROR
    assert rows[0].error == "bad xref"


def test_structural_checker_qpdf_timeout(sample_pdf: Path) -> None:
    with patch("shutil.which", return_value="/usr/bin/qpdf"), patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired("qpdf", 30)
    ):
        rows = StructuralChecker().check(sample_pdf)
    assert rows[0].status == ViewerCheckStatus.STRUCTURAL_ERROR


# ── PdfJsHeadlessChecker (fitz fallback path) ────────────────────────────────


def test_pdfjs_checker_falls_back_to_fitz(sample_pdf: Path) -> None:
    """Without Playwright installed, the fitz fallback enumerates links."""
    checker = PdfJsHeadlessChecker(use_playwright=False)
    rows = checker.check(sample_pdf)
    assert rows
    # All rows should be OK (external + internal are supported by PDF.js)
    assert all(r.status == ViewerCheckStatus.OK for r in rows)


def test_pdfjs_checker_marks_cross_doc_as_viewer_limitation(tmp_path: Path) -> None:
    """Cross-doc links are flagged as VIEWER_LIMITATION for PDF.js."""
    import fitz  # type: ignore

    path = tmp_path / "cross.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_link(
        {
            "kind": fitz.LINK_GOTOR,
            "from": fitz.Rect(72, 60, 200, 80),
            "file": "other.pdf",
            "page": 0,
            "to": fitz.Point(0, 0),
        }
    )
    doc.save(str(path))
    doc.close()

    checker = PdfJsHeadlessChecker(use_playwright=False)
    rows = checker.check(path)
    assert any(r.status == ViewerCheckStatus.VIEWER_LIMITATION for r in rows)


def test_pdfjs_checker_empty_pdf(empty_pdf: Path) -> None:
    checker = PdfJsHeadlessChecker(use_playwright=False)
    rows = checker.check(empty_pdf)
    assert rows == []


# ── Stub checkers ────────────────────────────────────────────────────────────


def test_acrobat_stub_returns_unverified(sample_pdf: Path) -> None:
    rows = AcrobatStubChecker().check(sample_pdf)
    # 1 document-level + N per-link rows
    assert len(rows) >= 1
    assert all(r.status == ViewerCheckStatus.UNVERIFIED for r in rows)
    assert rows[0].viewer_id == "adobe_acrobat_pro"


def test_fda_esg_stub(sample_pdf: Path) -> None:
    rows = FdaEsgStubChecker().check(sample_pdf)
    assert rows[0].viewer_id == "fda_esg"
    assert rows[0].status == ViewerCheckStatus.UNVERIFIED


def test_ema_espre_stub(sample_pdf: Path) -> None:
    rows = EmaEspreStubChecker().check(sample_pdf)
    assert rows[0].viewer_id == "ema_espre"


def test_pmda_stub(sample_pdf: Path) -> None:
    rows = PmdaGatewayStubChecker().check(sample_pdf)
    assert rows[0].viewer_id == "pmda_gateway"


# ── ViewerCompatReport aggregates ────────────────────────────────────────────


def test_report_pass_rate_empty() -> None:
    rep = ViewerCompatReport(pdf_path=Path("dummy.pdf"))
    assert rep.pass_rate == 1.0
    assert rep.total == 0


def test_report_aggregates() -> None:
    rep = ViewerCompatReport(
        pdf_path=Path("dummy.pdf"),
        results=[
            ViewerLinkResult("v1", "l1", "external", ViewerCheckStatus.OK),
            ViewerLinkResult("v1", "l2", "internal", ViewerCheckStatus.BROKEN),
            ViewerLinkResult("v2", "l1", "external", ViewerCheckStatus.UNVERIFIED),
            ViewerLinkResult("v2", "l2", "named_dest", ViewerCheckStatus.STRUCTURAL_ERROR),
        ],
    )
    assert rep.total == 4
    assert rep.ok == 1
    assert rep.broken == 1
    assert rep.unverified == 1
    assert rep.structural_errors == 1
    assert rep.pass_rate == 0.25
    assert len(rep.by_viewer("v1")) == 2


def test_report_by_viewer_unknown_returns_empty() -> None:
    rep = ViewerCompatReport(pdf_path=Path("x.pdf"))
    assert rep.by_viewer("ghost") == []


# ── run_viewer_compatibility orchestrator ────────────────────────────────────


def test_run_viewer_compatibility_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_viewer_compatibility(tmp_path / "nope.pdf")


def test_run_viewer_compatibility_with_custom_checkers(sample_pdf: Path) -> None:
    checker = PdfJsHeadlessChecker(use_playwright=False)
    report = run_viewer_compatibility(sample_pdf, checkers=[checker])
    assert isinstance(report, ViewerCompatReport)
    assert report.pdf_path == sample_pdf
    # Only one checker → all rows belong to that viewer
    assert all(r.viewer_id == "pdfjs_chrome" for r in report.results)


def test_run_viewer_compatibility_empty_checker_list(sample_pdf: Path) -> None:
    report = run_viewer_compatibility(sample_pdf, checkers=[])
    assert report.total == 0


def test_run_viewer_compatibility_default_set(sample_pdf: Path) -> None:
    """Default checker set runs without crashing — no live deps required."""
    report = run_viewer_compatibility(sample_pdf)
    # We expect rows from at least the four stub adapters (1 doc row + N link rows each)
    viewer_ids = {r.viewer_id for r in report.results}
    assert "adobe_acrobat_pro" in viewer_ids
    assert "fda_esg" in viewer_ids
    assert "ema_espre" in viewer_ids
    assert "pmda_gateway" in viewer_ids


def test_default_checkers_includes_six_adapters() -> None:
    checkers = default_checkers()
    assert len(checkers) == 6
    viewer_ids = {c.viewer_id for c in checkers}
    assert "structural_qpdf" in viewer_ids
    assert "pdfjs_chrome" in viewer_ids
    assert "adobe_acrobat_pro" in viewer_ids
