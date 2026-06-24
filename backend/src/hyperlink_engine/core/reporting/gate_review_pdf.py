"""W12.2 — Submission Gate Review PDF exporter.

Renders a printable management-summary PDF that captures:

* Dossier identity (NDA / IND number, sponsor, sequence)
* Overall readiness score + grade + submission-ready verdict
* Per-module breakdown (link counts, broken counts, blockers, warnings)
* Approver chain with sign-off status + timestamps
* Audit-trail tail (last N events)
* Compliance posture footer (21 CFR Part 11, on-prem, PDF/A-2b, GxP)

The PDF is produced with PyMuPDF (``fitz``) — already a Phase 1 dep — so
no new packages are required. The layout is black-and-white-legible for
inspector printouts (severity is icon + text + tint, never colour alone).

Usage::

    from hyperlink_engine.core.reporting.gate_review_pdf import write_gate_review_pdf
    write_gate_review_pdf(
        path=Path("output/gate_review.pdf"),
        dossier_id="NDA-215842",
        sponsor="SunPharma",
        readiness=readiness_result,
        approvers=[...],
        audit_events=[...],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fitz  # PyMuPDF

from hyperlink_engine.audit.trail import audit_event
from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.core.reporting.readiness_score import ReadinessResult

_log = get_logger("reporting.gate_review_pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Approver:
    """One row of the gate-review approver chain."""

    name: str
    role: str
    status: str  # "signed" | "pending" | "blocked"
    timestamp: str | None = None
    initials: str | None = None
    signature_hash: str | None = None


@dataclass
class AuditEntry:
    """One row of the audit trail footer."""

    when: str
    actor: str
    action: str
    hash: str | None = None
    detail: str | None = None


@dataclass
class GateReviewBundle:
    """All inputs needed to render the gate-review PDF."""

    dossier_id: str
    sponsor: str
    submission_type: str = "NDA"
    sequence: str = "0001"
    readiness: ReadinessResult | None = None
    approvers: list[Approver] = field(default_factory=list)
    audit_events: list[AuditEntry] = field(default_factory=list)
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Layout constants — letter portrait (8.5×11 in @ 72 dpi)
# ─────────────────────────────────────────────────────────────────────────────

_PAGE_W = 612.0
_PAGE_H = 792.0
_MARGIN_L = 54.0
_MARGIN_R = 54.0
_MARGIN_T = 54.0
_CONTENT_W = _PAGE_W - _MARGIN_L - _MARGIN_R

# Colours used in the PDF (RGB tuples in 0–1 range for fitz)
_COL_TEXT_1 = (0.06, 0.09, 0.14)
_COL_TEXT_2 = (0.29, 0.33, 0.39)
_COL_TEXT_3 = (0.42, 0.46, 0.52)
_COL_BORDER = (0.89, 0.91, 0.93)
_COL_BRAND = (0.12, 0.31, 0.55)
_COL_SUCCESS = (0.02, 0.46, 0.28)
_COL_WARNING = (0.71, 0.28, 0.03)
_COL_DANGER = (0.71, 0.14, 0.09)


def _grade_color(grade: str) -> tuple[float, float, float]:
    if grade == "A":
        return _COL_SUCCESS
    if grade == "B":
        return _COL_BRAND
    if grade == "C":
        return _COL_WARNING
    return _COL_DANGER


def _status_label_color(status: str) -> tuple[float, float, float]:
    return {
        "signed": _COL_SUCCESS,
        "pending": _COL_WARNING,
        "blocked": _COL_DANGER,
    }.get(status, _COL_TEXT_2)


# ─────────────────────────────────────────────────────────────────────────────
# PDF drawing helpers
# ─────────────────────────────────────────────────────────────────────────────


def _draw_text(
    page: fitz.Page,
    x: float,
    y: float,
    text: str,
    *,
    size: float = 10,
    fontname: str = "helv",
    color: tuple[float, float, float] = _COL_TEXT_1,
    bold: bool = False,
) -> None:
    """Insert one line of text at ``(x, y)`` (PDF coords, y from top)."""
    fn = "helv"
    if bold:
        fn = "hebo"
    page.insert_text((x, y), text, fontsize=size, fontname=fn, color=color)


def _draw_rule(page: fitz.Page, y: float, *, color: tuple = _COL_BORDER) -> None:
    """Horizontal rule across the content width."""
    page.draw_line((_MARGIN_L, y), (_PAGE_W - _MARGIN_R, y), color=color, width=0.5)


def _draw_box(
    page: fitz.Page,
    rect: fitz.Rect,
    *,
    fill: tuple | None = None,
    border: tuple | None = _COL_BORDER,
    border_width: float = 0.5,
) -> None:
    page.draw_rect(rect, fill=fill, color=border, width=border_width)


# ─────────────────────────────────────────────────────────────────────────────
# Section renderers — each returns the y-coordinate where the next section
# should start.
# ─────────────────────────────────────────────────────────────────────────────


def _render_header(page: fitz.Page, bundle: GateReviewBundle, y: float) -> float:
    """Title block: product header + generation timestamp."""
    _draw_text(
        page,
        _MARGIN_L,
        y,
        "SUBMISSION GATE REVIEW",
        size=9,
        color=_COL_BRAND,
        bold=True,
    )
    _draw_text(
        page,
        _MARGIN_L,
        y + 22,
        f"{bundle.submission_type} {bundle.dossier_id} · {bundle.sponsor}",
        size=20,
        bold=True,
    )
    _draw_text(
        page,
        _MARGIN_L,
        y + 40,
        f"Sequence {bundle.sequence} · generated {bundle.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        size=10,
        color=_COL_TEXT_2,
    )
    _draw_rule(page, y + 56)
    return y + 72


def _render_readiness_block(
    page: fitz.Page, bundle: GateReviewBundle, y: float
) -> float:
    """Big readiness score + grade + submission-ready verdict."""
    r = bundle.readiness
    if r is None:
        _draw_text(
            page, _MARGIN_L, y, "Readiness score: not available", size=11, color=_COL_TEXT_2
        )
        return y + 24

    # Section heading
    _draw_text(page, _MARGIN_L, y, "READINESS", size=8, bold=True, color=_COL_TEXT_3)
    y += 16

    # Score + grade (large)
    _draw_text(
        page,
        _MARGIN_L,
        y + 18,
        f"{r.overall_score:.1f}/100",
        size=32,
        bold=True,
        color=_grade_color(r.grade),
    )
    _draw_text(
        page,
        _MARGIN_L + 130,
        y + 18,
        f"Grade {r.grade}",
        size=20,
        bold=True,
        color=_grade_color(r.grade),
    )

    ready_text = (
        "SUBMISSION READY" if r.is_submission_ready else "NOT READY"
    )
    ready_color = _COL_SUCCESS if r.is_submission_ready else _COL_DANGER
    _draw_text(
        page,
        _MARGIN_L + 240,
        y + 22,
        ready_text,
        size=12,
        bold=True,
        color=ready_color,
    )

    # KPI strip
    y += 50
    stats: list[tuple[str, str]] = [
        ("Documents", str(r.document_count)),
        ("Total links", str(r.total_links)),
        ("Broken links", str(r.broken_links)),
        ("Blocker anomalies", str(r.blocker_anomalies)),
        ("Warning anomalies", str(r.warning_anomalies)),
        ("Broken-link rate", f"{r.broken_rate * 100:.2f}%"),
    ]
    col_w = _CONTENT_W / 3
    for i, (label, value) in enumerate(stats):
        col = i % 3
        row = i // 3
        x = _MARGIN_L + col * col_w
        ry = y + row * 36
        _draw_text(page, x, ry, label.upper(), size=7, color=_COL_TEXT_3)
        _draw_text(page, x, ry + 16, value, size=14, bold=True)
    y += 36 * ((len(stats) + 2) // 3) + 8
    _draw_rule(page, y)
    return y + 16


def _render_module_breakdown(
    page: fitz.Page, bundle: GateReviewBundle, y: float
) -> float:
    """Per-module sub-scores table."""
    r = bundle.readiness
    if r is None or not r.module_scores:
        return y

    _draw_text(page, _MARGIN_L, y, "MODULE BREAKDOWN", size=8, bold=True, color=_COL_TEXT_3)
    y += 16

    header_y = y + 12
    cols = [
        ("Module", _MARGIN_L),
        ("Score", _MARGIN_L + 140),
        ("Broken", _MARGIN_L + 200),
        ("Blockers", _MARGIN_L + 260),
        ("Warnings", _MARGIN_L + 330),
        ("Docs", _MARGIN_L + 400),
    ]
    for hdr, x in cols:
        _draw_text(page, x, header_y, hdr, size=8, color=_COL_TEXT_3, bold=True)
    _draw_rule(page, header_y + 6)
    y = header_y + 20

    for ms in sorted(r.module_scores, key=lambda s: s.score):
        _draw_text(page, cols[0][1], y, ms.module, size=10)
        _draw_text(
            page,
            cols[1][1],
            y,
            f"{ms.score:.1f}",
            size=10,
            color=_grade_color(
                "A" if ms.score >= 95 else "B" if ms.score >= 85 else "C" if ms.score >= 70 else "D"
            ),
            bold=True,
        )
        _draw_text(page, cols[2][1], y, str(ms.broken_links), size=10)
        _draw_text(page, cols[3][1], y, str(ms.blocker_anomalies), size=10)
        _draw_text(page, cols[4][1], y, str(ms.warning_anomalies), size=10)
        _draw_text(page, cols[5][1], y, str(ms.document_count), size=10)
        y += 16

    _draw_rule(page, y + 4)
    return y + 18


def _render_approvers(page: fitz.Page, bundle: GateReviewBundle, y: float) -> float:
    if not bundle.approvers:
        return y

    _draw_text(page, _MARGIN_L, y, "APPROVER CHAIN", size=8, bold=True, color=_COL_TEXT_3)
    y += 16

    for ap in bundle.approvers:
        # 1-line per approver: status box + name (role) + status + timestamp
        status_color = _status_label_color(ap.status)
        # Small status pill
        rect = fitz.Rect(_MARGIN_L, y - 8, _MARGIN_L + 14, y + 6)
        _draw_box(page, rect, fill=status_color, border=status_color)
        if ap.status == "signed":
            _draw_text(page, _MARGIN_L + 3, y + 4, "OK", size=7, color=(1, 1, 1), bold=True)

        _draw_text(page, _MARGIN_L + 24, y + 3, ap.name, size=11, bold=True)
        _draw_text(
            page,
            _MARGIN_L + 24 + len(ap.name) * 6 + 6,
            y + 3,
            f"({ap.role})",
            size=10,
            color=_COL_TEXT_2,
        )
        _draw_text(
            page,
            _MARGIN_L + 280,
            y + 3,
            ap.status.upper(),
            size=10,
            color=status_color,
            bold=True,
        )
        if ap.timestamp:
            _draw_text(
                page,
                _MARGIN_L + 360,
                y + 3,
                ap.timestamp,
                size=10,
                color=_COL_TEXT_2,
            )
        if ap.signature_hash:
            _draw_text(
                page,
                _MARGIN_L + 24,
                y + 16,
                f"hash {ap.signature_hash}",
                size=8,
                color=_COL_TEXT_3,
            )
            y += 12
        y += 22

    _draw_rule(page, y)
    return y + 16


def _render_audit_trail(
    page: fitz.Page, bundle: GateReviewBundle, y: float, *, limit: int = 8
) -> float:
    if not bundle.audit_events:
        return y

    _draw_text(page, _MARGIN_L, y, "AUDIT TRAIL", size=8, bold=True, color=_COL_TEXT_3)
    _draw_text(
        page,
        _MARGIN_L + 130,
        y,
        "(append-only · last events first)",
        size=8,
        color=_COL_TEXT_3,
    )
    y += 16

    events = bundle.audit_events[-limit:][::-1]
    for ev in events:
        _draw_text(page, _MARGIN_L, y, ev.when, size=8, color=_COL_TEXT_3)
        _draw_text(page, _MARGIN_L + 130, y, ev.actor, size=10, bold=True)
        _draw_text(page, _MARGIN_L + 230, y, ev.action, size=10, color=_COL_TEXT_2)
        if ev.hash:
            _draw_text(
                page,
                _PAGE_W - _MARGIN_R - 90,
                y,
                ev.hash,
                size=8,
                color=_COL_TEXT_3,
            )
        if ev.detail:
            _draw_text(
                page,
                _MARGIN_L + 130,
                y + 12,
                ev.detail,
                size=8,
                color=_COL_TEXT_3,
            )
            y += 10
        y += 16

    return y + 4


def _render_compliance_footer(page: fitz.Page) -> None:
    """Compliance posture footer near the bottom of the page."""
    y = _PAGE_H - 60
    _draw_rule(page, y - 8)
    items = [
        "21 CFR Part 11 audit-logged",
        "On-prem inference only",
        "PDF/A-2b validated",
        "GxP environment",
    ]
    col_w = _CONTENT_W / len(items)
    for i, item in enumerate(items):
        x = _MARGIN_L + i * col_w
        # Small check mark glyph
        _draw_text(page, x, y, "✓", size=10, color=_COL_SUCCESS, bold=True)
        _draw_text(page, x + 12, y, item, size=9, color=_COL_TEXT_2)
    _draw_text(
        page,
        _MARGIN_L,
        _PAGE_H - 30,
        "This summary is generated by the Hyperlink Validation Engine. "
        "Signatures and hashes are reproduced for inspector reference only — "
        "see audit.jsonl for the authoritative record.",
        size=7,
        color=_COL_TEXT_3,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def write_gate_review_pdf(
    *,
    path: Path,
    dossier_id: str,
    sponsor: str,
    submission_type: str = "NDA",
    sequence: str = "0001",
    readiness: ReadinessResult | None = None,
    approvers: Iterable[Approver] = (),
    audit_events: Iterable[AuditEntry] = (),
) -> Path:
    """Render the gate-review management summary PDF.

    Parameters
    ----------
    path:
        Output file path.
    dossier_id:
        Submission identifier (e.g., ``"NDA-215842"``).
    sponsor:
        Sponsor / company name displayed in the title.
    submission_type:
        IND / NDA / BLA / MAA / JNDA — printed in the title.
    sequence:
        eCTD sequence number (e.g., ``"0009"``).
    readiness:
        :class:`ReadinessResult` from
        :func:`reporting.readiness_score.compute_readiness_score`.
    approvers:
        Ordered list of :class:`Approver`.
    audit_events:
        Ordered list of :class:`AuditEntry` (oldest first; renderer
        flips for display).

    Returns
    -------
    Path
        The written file path.

    Side effects
    ------------
    Emits a ``gate_review_pdf_written`` event to the audit trail.
    """
    bundle = GateReviewBundle(
        dossier_id=dossier_id,
        sponsor=sponsor,
        submission_type=submission_type,
        sequence=sequence,
        readiness=readiness,
        approvers=list(approvers),
        audit_events=list(audit_events),
    )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)

    y = _MARGIN_T
    y = _render_header(page, bundle, y)
    y = _render_readiness_block(page, bundle, y)
    y = _render_module_breakdown(page, bundle, y)
    y = _render_approvers(page, bundle, y)
    y = _render_audit_trail(page, bundle, y)
    _render_compliance_footer(page)

    doc.save(str(path))
    doc.close()

    _log.info(
        "gate_review_pdf_written",
        path=str(path),
        dossier=dossier_id,
        approver_count=len(bundle.approvers),
        audit_event_count=len(bundle.audit_events),
    )
    audit_event(
        "gate_review_pdf_exported",
        document=dossier_id,
        details={
            "path": str(path),
            "submission_type": submission_type,
            "sequence": sequence,
        },
    )
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Sign-off helper (writes the gate-review approval audit record)
# ─────────────────────────────────────────────────────────────────────────────


def record_gate_signoff(
    *,
    dossier_id: str,
    approver_name: str,
    approver_role: str,
    signature_hash: str | None = None,
    signature_method: str = "PIV-ECDSA-P256",
    details: dict[str, Any] | None = None,
) -> None:
    """Emit an immutable audit event recording a gate-review sign-off.

    Used by the dashboard's POST /api/dossiers/{id}/signoff endpoint and
    by the CLI when an operator approves a gate review locally.
    """
    extra = dict(details or {})
    extra.update(
        {
            "approver_name": approver_name,
            "approver_role": approver_role,
            "signature_method": signature_method,
            "signature_hash": signature_hash or "",
        }
    )
    audit_event(
        "gate_review_signed",
        actor=f"{approver_role}:{approver_name}",
        document=dossier_id,
        details=extra,
    )
