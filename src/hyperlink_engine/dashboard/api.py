"""W11.2 + W12.1 — FastAPI backend for the production dashboard.

Exposes the JSON endpoints the React frontend (Phase 3) will consume:

    GET   /api/health
    GET   /api/dossiers
    GET   /api/dossiers/{id}/score
    GET   /api/dossiers/{id}/anomalies
    GET   /api/dossiers/{id}/links
    POST  /api/dossiers/{id}/push              — push the latest QC report to Dossplorer
    POST  /api/dossiers/{id}/webhook           — Dossplorer-initiated webhook entrypoint

Also includes a tiny polling loop (:func:`poll_dossplorer_status_once`) used
by the operations runbook when the operator chooses *polling* over webhook
for the review workflow.

The app is created via :func:`create_app` so tests can construct it with
injected dependencies (custom Dossplorer client, custom report store).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False
    FastAPI = object  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]
    UploadFile = object  # type: ignore[assignment, misc]

from hyperlink_engine.audit.trail import audit_event
from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.ingestion.dossplorer_client import (
    DossplorerClient,
    DossplorerError,
    MockDossplorerClient,
    get_client,
)
from hyperlink_engine.models import AnomalySeverity

_log = get_logger("dashboard.api")


# ─────────────────────────────────────────────────────────────────────────────
# In-memory report store (replace with DB in production)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _ReportStore:
    """Holds the most recent per-dossier reports the engine has produced."""

    scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    anomalies: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    links: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    webhook_events: list[dict[str, Any]] = field(default_factory=list)

    def upsert_score(self, dossier_id: str, payload: dict[str, Any]) -> None:
        self.scores[dossier_id] = payload

    def get_score(self, dossier_id: str) -> dict[str, Any] | None:
        return self.scores.get(dossier_id)

    def append_anomalies(
        self, dossier_id: str, anomalies: list[dict[str, Any]]
    ) -> None:
        self.anomalies.setdefault(dossier_id, []).extend(anomalies)

    def get_anomalies(self, dossier_id: str) -> list[dict[str, Any]]:
        return self.anomalies.get(dossier_id, [])

    def set_links(self, dossier_id: str, links: list[dict[str, Any]]) -> None:
        self.links[dossier_id] = links

    def get_links(self, dossier_id: str) -> list[dict[str, Any]]:
        return self.links.get(dossier_id, [])

    def record_webhook(self, payload: dict[str, Any]) -> None:
        self.webhook_events.append(payload)

    def get_detection_trace(self, dossier_id: str) -> dict[str, Any] | None:
        """Summarize detection layer distribution across all links."""
        links = self.get_links(dossier_id)
        if not links:
            return None

        # Group links by source document
        by_doc: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            doc = link.get("source_doc", "unknown")
            by_doc.setdefault(doc, []).append(link)

        # Per-document breakdown
        per_doc = []
        total_links_count = 0
        for doc_name in sorted(by_doc.keys()):
            doc_links = by_doc[doc_name]
            total = len(doc_links)
            regex_only = sum(1 for l in doc_links if l.get("detected_by") == "regex")
            ner_triggered = sum(1 for l in doc_links if l.get("detected_by") == "ner")
            llm_triggered = sum(1 for l in doc_links if l.get("detected_by") == "llm")
            mixed = total - regex_only - ner_triggered - llm_triggered
            per_doc.append({
                "doc_name": doc_name,
                "total_links": total,
                "regex_only": regex_only,
                "ner_triggered": ner_triggered,
                "llm_triggered": llm_triggered,
                "mixed": mixed,
            })
            total_links_count += total

        return {
            "total_docs": len(by_doc),
            "total_links": total_links_count,
            "per_doc": per_doc,
        }


def _find_csv_path() -> "Path":
    """Resolve the batch-output CSV path robustly regardless of CWD.

    Tries (in order):
      1. Project-root-relative path resolved from this file's location.
      2. CWD-relative path as fallback (e.g. when running tests from project root).
    """
    # api.py lives at: <project>/src/hyperlink_engine/dashboard/api.py
    # Project root is 4 levels up: dashboard → hyperlink_engine → src → <project>
    project_root = Path(__file__).resolve().parent.parent.parent.parent

    # ── 30-doc run (active) ──────────────────────────────────────────────
    absolute = project_root / "output" / "run30" / "dossier_links.csv"
    if absolute.exists():
        return absolute
    # Fallback: CWD-relative (works if uvicorn is launched from project root)
    fallback = Path("output") / "run30" / "dossier_links.csv"
    if fallback.exists():
        return fallback

    # ── 20-doc run (previous — kept for reference, commented out) ────────
    # absolute = project_root / "output" / "run1" / "dossier_links.csv"
    # if absolute.exists():
    #     return absolute
    # fallback = Path("output") / "run1" / "dossier_links.csv"
    return fallback  # return run30 fallback path even if not found yet


def _load_store_from_csv(store: "_ReportStore", csv_path: "Path | None" = None) -> bool:
    """Auto-load batch results from CSV into the store on startup.
    Returns True if data was loaded, False if CSV not found."""
    import csv as _csv

    path = csv_path if csv_path is not None else _find_csv_path()
    path = Path(path)
    if not path.exists():
        _log.info("csv_not_found_using_demo_data", path=str(path))
        return False

    rows: list[dict[str, Any]] = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            rows = list(reader)
    except Exception as exc:
        _log.warning("csv_load_error", path=str(path), error=str(exc))
        return False

    if not rows:
        return False

    total = len(rows)
    broken = sum(1 for r in rows if r.get("status", "").lower() == "broken")
    unverified = sum(1 for r in rows if r.get("status", "").lower() == "unverified")
    ok = total - broken - unverified
    # unverified = external URLs (clinicaltrials.gov etc) — proportional small penalty only
    score = max(0.0, min(100.0, 100.0 - broken * 5 - (unverified / total * 5 if total else 0)))
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "F"

    store.upsert_score("demo", {
        "score": round(score, 1),
        "grade": grade,
        "broken_links": broken,
        "blocker_anomalies": broken,
        "total_links": total,
        "ok_links": ok,
        "unverified_links": unverified,
        "is_submission_ready": score >= 85 and broken == 0,
    })

    anomalies: list[dict[str, Any]] = []
    for r in rows:
        st = r.get("status", "").lower()
        if st == "broken":
            anomalies.append({
                "kind": "broken_link", "severity": "blocker",
                "document": r.get("source_doc", ""), "text": r.get("link_text", ""),
                "suggested_fix": f"Check target: {r.get('target_doc', '')}",
                "confidence": float(r.get("confidence", 0.9)),
            })
        elif st == "unverified":
            anomalies.append({
                "kind": "unverified_link", "severity": "warning",
                "document": r.get("source_doc", ""), "text": r.get("link_text", ""),
                "suggested_fix": "Manually verify target exists in submission package",
                "confidence": float(r.get("confidence", 0.7)),
            })
    store.anomalies["demo"] = []
    if anomalies:
        store.append_anomalies("demo", anomalies)

    links = [{
        "source_doc": r.get("source_doc", ""),
        "link_text": r.get("link_text", ""),
        # CSV column is "link_location"; keep both names for compatibility
        "link_location_descriptor": r.get("link_location") or r.get("link_location_descriptor", ""),
        "target_doc": r.get("target_doc", ""),
        "target_anchor": r.get("target_anchor", ""),
        "status": r.get("status", "ok").lower(),
        "confidence": float(r.get("confidence", 1.0)),
        "error_msg": r.get("error_msg") or None,
    } for r in rows]
    store.set_links("demo", links)
    _log.info("csv_loaded_into_store", path=str(path), total=total, broken=broken,
              unverified=unverified, score=round(score, 1))
    return True


_DEFAULT_STORE = _ReportStore()

# Try to load real batch results first; fall back to demo data if not found
_loaded = _load_store_from_csv(_DEFAULT_STORE)
if not _loaded:
    # Fallback: hardcoded demo data (used before any batch run)
    _DEFAULT_STORE.upsert_score("demo", {
        "score": 85.0,
        "grade": "B",
        "broken_links": 0,
        "blocker_anomalies": 0,
        "is_submission_ready": True
    })
    _DEFAULT_STORE.append_anomalies("demo", [
        {
            "kind": "blue_text_no_link",
            "severity": "warning",
            "document": "doc1.docx",
            "text": "Section 2.5",
            "suggested_fix": "Add link",
            "confidence": 0.85
        }
    ])
    _DEFAULT_STORE.set_links("demo", [
        {
            "source_doc": "doc1.docx",
            "link_text": "Section 2.5",
            "link_location_descriptor": "p12.r3:c45-56",
            "target_doc": "doc2.docx",
            "target_anchor": "sec_2_5",
            "status": "ok",
            "confidence": 1.0,
            "error_msg": None
        }
    ])


def get_report_store() -> _ReportStore:
    """Return the process-wide :class:`_ReportStore` instance."""
    return _DEFAULT_STORE


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic request / response schemas
# ─────────────────────────────────────────────────────────────────────────────


if _FASTAPI_AVAILABLE:

    class ScoreResponse(BaseModel):
        dossier_id: str
        score: float
        grade: str | None = None
        broken_links: int = 0
        blocker_anomalies: int = 0
        is_submission_ready: bool = False

    class PushRequest(BaseModel):
        score: float
        sequence: str | None = None
        anomalies: list[dict[str, Any]] = []

    class WebhookPayload(BaseModel):
        event: str
        dossier_id: str
        timestamp: str
        details: dict[str, Any] = {}

    class SignoffRequest(BaseModel):
        approver_name: str
        approver_role: str
        signature_hash: str | None = None
        signature_method: str = "PIV-ECDSA-P256"
        notes: str | None = None

    class GateReviewExportRequest(BaseModel):
        submission_type: str = "NDA"
        sequence: str = "0001"
        sponsor: str = "SunPharma"
        approvers: list[dict[str, Any]] = []
        audit_events: list[dict[str, Any]] = []

    class DetectionTracePerDoc(BaseModel):
        doc_name: str
        total_links: int
        regex_only: int
        ner_triggered: int
        llm_triggered: int
        mixed: int

    class DetectionTraceResponse(BaseModel):
        total_docs: int
        total_links: int
        per_doc: list[DetectionTracePerDoc]


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────


def create_app(
    *,
    dossplorer_client_factory: Callable[[], DossplorerClient] | None = None,
    report_store: _ReportStore | None = None,
) -> "FastAPI":
    """Build the FastAPI app with injectable deps."""
    if not _FASTAPI_AVAILABLE:  # pragma: no cover
        raise ImportError(
            "fastapi is required for the dashboard API. "
            "Install it with: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="hyperlink-engine — QC Dashboard API",
        version="0.3.0-phase3",
        description=(
            "On-prem dashboard backend for the hyperlink-engine. "
            "All data stays inside the SunPharma VPC."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",   # original react_frontend
            "http://localhost:5174",   # simple_frontend (two-screen UI)
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = report_store or _DEFAULT_STORE
    client_factory = dossplorer_client_factory or get_client

    # ── Health ────────────────────────────────────────────────────────────

    @app.get("/api/health", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    @app.get("/health", response_class=PlainTextResponse)
    def health_legacy() -> str:
        return "ok"

    # ── Dossier listing (proxies the Dossplorer client) ────────────────────

    @app.get("/api/dossiers")
    def list_dossiers() -> dict[str, Any]:
        client = client_factory()
        if isinstance(client, MockDossplorerClient):
            ids = client.list_dossier_ids()
        else:
            # The live API doesn't expose a list endpoint; return what we have
            # buffered locally instead.
            ids = sorted(store.scores.keys())
        return {"dossiers": ids}

    # ── Score endpoints ────────────────────────────────────────────────────

    @app.get("/api/dossiers/{dossier_id}/score", response_model=ScoreResponse)
    def get_dossier_score(dossier_id: str) -> ScoreResponse:
        payload = store.get_score(dossier_id)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no score recorded for dossier {dossier_id!r}",
            )
        return ScoreResponse(dossier_id=dossier_id, **payload)

    # ── Anomalies ──────────────────────────────────────────────────────────

    @app.get("/api/dossiers/{dossier_id}/anomalies")
    def get_dossier_anomalies(
        dossier_id: str,
        severity: str | None = None,
    ) -> dict[str, Any]:
        items = store.get_anomalies(dossier_id)
        if severity:
            items = [a for a in items if a.get("severity") == severity]
        return {"dossier_id": dossier_id, "anomalies": items, "count": len(items)}

    # ── Links ──────────────────────────────────────────────────────────────

    @app.get("/api/dossiers/{dossier_id}/links")
    def get_dossier_links(
        dossier_id: str,
        link_status: str | None = None,
    ) -> dict[str, Any]:
        items = store.get_links(dossier_id)
        if link_status:
            items = [l for l in items if l.get("status") == link_status]
        return {"dossier_id": dossier_id, "links": items, "count": len(items)}

    # ── Detection Trace (Layer breakdown) ───────────────────────────────

    @app.get("/api/dossiers/{dossier_id}/detection-trace", response_model=DetectionTraceResponse)
    def get_detection_trace(dossier_id: str) -> DetectionTraceResponse:
        trace_data = store.get_detection_trace(dossier_id)
        if trace_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"no links recorded for dossier {dossier_id!r}",
            )
        return DetectionTraceResponse(**trace_data)

    # ── Push to Dossplorer ─────────────────────────────────────────────────

    @app.post("/api/dossiers/{dossier_id}/push")
    def push_to_dossplorer(dossier_id: str, body: PushRequest) -> dict[str, Any]:
        client = client_factory()
        try:
            client.push_readiness_score(
                dossier_id, body.score, sequence=body.sequence
            )
            for anomaly in body.anomalies:
                client.push_anomaly_flag(
                    dossier_id,
                    document=anomaly.get("document", ""),
                    severity=AnomalySeverity(anomaly.get("severity", "warning")),
                    message=anomaly.get("message", ""),
                )
        except DossplorerError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        audit_event(
            "dashboard_push_dispatched",
            document=dossier_id,
            details={"score": body.score, "anomaly_count": len(body.anomalies)},
        )
        return {"status": "pushed", "dossier_id": dossier_id}

    # ── Direct store update (used by push_results_to_dashboard.py) ───────

    @app.post("/api/dossiers/{dossier_id}/update-store")
    def update_store(dossier_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Directly update the in-memory store with batch pipeline results.

        Called by scripts/push_results_to_dashboard.py after a batch run
        completes. Replaces score + links; appends anomalies.
        """
        score_payload = body.get("score")
        if score_payload:
            store.upsert_score(dossier_id, {
                "score": score_payload.get("score", 0.0),
                "grade": score_payload.get("grade", "F"),
                "broken_links": score_payload.get("broken_links", 0),
                "blocker_anomalies": score_payload.get("blocker_anomalies", 0),
                "is_submission_ready": score_payload.get("is_submission_ready", False),
            })

        anomalies = body.get("anomalies", [])
        if anomalies:
            # Clear old anomalies and replace with fresh results
            store.anomalies[dossier_id] = []
            store.append_anomalies(dossier_id, anomalies)

        links = body.get("links", [])
        if links:
            store.set_links(dossier_id, links)

        audit_event(
            "store_updated_from_batch",
            document=dossier_id,
            details={
                "links": len(links),
                "anomalies": len(anomalies),
            },
        )
        return {
            "status": "updated",
            "dossier_id": dossier_id,
            "links_loaded": len(links),
            "anomalies_loaded": len(anomalies),
        }

    # ── Gate review: sign-off ─────────────────────────────────────────────

    @app.post("/api/dossiers/{dossier_id}/signoff")
    def signoff(dossier_id: str, body: SignoffRequest) -> dict[str, Any]:
        """Record an immutable gate-review sign-off in the audit trail.

        Phase 4 will wire this to the live PIV smartcard signer; for the
        POC we accept a pre-computed signature_hash from the client (or
        leave it null, indicating the sign-off was performed in the UI
        without a hardware key).
        """
        from hyperlink_engine.reporting.gate_review_pdf import record_gate_signoff

        record_gate_signoff(
            dossier_id=dossier_id,
            approver_name=body.approver_name,
            approver_role=body.approver_role,
            signature_hash=body.signature_hash,
            signature_method=body.signature_method,
            details={"notes": body.notes or ""},
        )
        return {
            "status": "signed",
            "dossier_id": dossier_id,
            "approver": body.approver_name,
            "role": body.approver_role,
        }

    # ── Gate review: export PDF ───────────────────────────────────────────

    @app.post("/api/dossiers/{dossier_id}/gate-review.pdf")
    def export_gate_review(
        dossier_id: str, body: GateReviewExportRequest
    ) -> dict[str, Any]:
        """Render the gate-review PDF for ``dossier_id`` and return its path.

        The PDF lands under ``output/gate_reviews/{dossier_id}_{timestamp}.pdf``
        and the action is audit-logged.
        """
        from hyperlink_engine.config.settings import get_settings
        from hyperlink_engine.reporting.gate_review_pdf import (
            Approver,
            AuditEntry,
            write_gate_review_pdf,
        )

        settings = get_settings()
        output_dir = Path(settings.output_dir) / "gate_reviews"
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        output_path = output_dir / f"{dossier_id}_{ts}.pdf"

        approvers = [
            Approver(
                name=a.get("name", ""),
                role=a.get("role", ""),
                status=a.get("status", "pending"),
                timestamp=a.get("timestamp"),
                initials=a.get("initials"),
                signature_hash=a.get("signature_hash"),
            )
            for a in body.approvers
        ]
        audit_entries = [
            AuditEntry(
                when=e.get("when", ""),
                actor=e.get("actor", ""),
                action=e.get("action", ""),
                hash=e.get("hash"),
                detail=e.get("detail"),
            )
            for e in body.audit_events
        ]

        score_payload = store.get_score(dossier_id)
        readiness = None
        if score_payload:
            try:
                from hyperlink_engine.reporting.readiness_score import ReadinessResult

                readiness = ReadinessResult.model_validate(
                    {"dossier_id": dossier_id, **score_payload}
                )
            except Exception:  # pragma: no cover - tolerate missing score
                readiness = None

        write_gate_review_pdf(
            path=output_path,
            dossier_id=dossier_id,
            sponsor=body.sponsor,
            submission_type=body.submission_type,
            sequence=body.sequence,
            readiness=readiness,
            approvers=approvers,
            audit_events=audit_entries,
        )
        return {
            "status": "exported",
            "dossier_id": dossier_id,
            "path": str(output_path),
        }

    # ── Webhook entrypoint ─────────────────────────────────────────────────

    @app.post("/api/dossiers/{dossier_id}/webhook")
    def webhook(dossier_id: str, payload: WebhookPayload) -> dict[str, Any]:
        if payload.dossier_id != dossier_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="payload.dossier_id does not match URL",
            )
        store.record_webhook(payload.model_dump())
        audit_event(
            "dashboard_webhook_received",
            document=dossier_id,
            details={"event": payload.event},
        )
        return {"received": True, "event": payload.event}

    # ── Export endpoints ──────────────────────────────────────────────────

    # ── Document preview (for in-UI before/after comparison) ─────────────

    @app.get("/api/dossiers/{dossier_id}/document-preview")
    def document_preview(dossier_id: str, doc_name: str) -> dict[str, Any]:
        """Return paragraph text + injected links for a document.

        Used by the React comparison screen to render before/after view.
        Paragraphs come from the original .docx; links come from the store.
        """
        # Locate the original .docx (search data/synthetic recursively)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        synthetic_root = project_root / "data" / "synthetic"
        matches = list(synthetic_root.rglob(doc_name))
        if not matches:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Original document {doc_name!r} not found under data/synthetic/",
            )
        orig_path = matches[0]

        # Read paragraphs via python-docx
        try:
            from docx import Document as _DocxDocument  # type: ignore[import-not-found]
            docx = _DocxDocument(str(orig_path))
            paragraphs = []
            for idx, para in enumerate(docx.paragraphs):
                text = para.text.strip()
                if text:
                    paragraphs.append({"index": idx, "text": text})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read document: {exc}",
            ) from exc

        # Get links for this document from the store
        all_links = store.get_links(dossier_id)
        doc_links = [lnk for lnk in all_links if lnk.get("source_doc") == doc_name]

        return {
            "doc_name": doc_name,
            "orig_path": str(orig_path.relative_to(project_root)),
            "paragraphs": paragraphs,
            "links": doc_links,
            "total_links": len(doc_links),
            "ok_links": sum(1 for l in doc_links if l.get("status") == "ok"),
            "unverified_links": sum(1 for l in doc_links if l.get("status") == "unverified"),
            "broken_links": sum(1 for l in doc_links if l.get("status") == "broken"),
        }

    @app.get("/api/reload-store")
    def reload_store() -> dict[str, Any]:
        """Re-read the batch CSV from disk and refresh the in-memory store.

        Useful when a new batch run has completed but FastAPI is already
        running — call this instead of restarting the server.
        """
        loaded = _load_store_from_csv(store)
        score_payload = store.get_score("demo") or {}
        return {
            "reloaded": loaded,
            "score": score_payload.get("score"),
            "total_links": score_payload.get("total_links"),
            "broken_links": score_payload.get("broken_links"),
            "anomalies": len(store.get_anomalies("demo")),
            "links": len(store.get_links("demo")),
        }

    @app.get("/api/dossiers/{dossier_id}/export.csv")
    def export_csv(dossier_id: str) -> Response:
        import csv as _csv
        import io

        items = store.get_links(dossier_id)
        headers_dict = {
            "Content-Disposition": f"attachment; filename={dossier_id}_links.csv"
        }
        output = io.StringIO()
        fieldnames = [
            "source_doc", "link_text", "link_location_descriptor",
            "target_doc", "target_anchor", "status", "confidence", "error_msg",
        ]
        writer = _csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore",
                                 lineterminator="\r\n")
        writer.writeheader()
        for row in items:
            writer.writerow(row)
        return Response(content=output.getvalue(), media_type="text/csv", headers=headers_dict)

    @app.get("/api/dossiers/{dossier_id}/export.xlsx")
    def export_xlsx(dossier_id: str) -> Response:
        headers = {
            "Content-Disposition": f"attachment; filename={dossier_id}_report.xlsx"
        }
        dummy_excel = b"mock excel content"
        return Response(
            content=dummy_excel,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    # ══════════════════════════════════════════════════════════════════════
    # PLAN TWO — Pipeline orchestration endpoints
    # POST /api/pipeline/upload       Upload documents → run_id
    # POST /api/pipeline/run/{run_id} Trigger pipeline in background
    # GET  /api/pipeline/stream/{run_id} SSE live state
    # GET  /api/pipeline/status/{run_id} Current status JSON
    # GET  /api/pipeline/runs         List all runs
    # GET  /api/pipeline/run/{run_id}/results  Final results JSON
    # GET  /api/pipeline/run/{run_id}/download/{filename} Download linked file
    # ══════════════════════════════════════════════════════════════════════

    if _FASTAPI_AVAILABLE:

        @app.post("/api/pipeline/upload")
        async def pipeline_upload(
            files: list[UploadFile] = File(...),
            dossier_id: str = Form(default=""),
        ) -> dict[str, Any]:
            """Accept uploaded .docx/.pdf files and stage them for a pipeline run."""
            from hyperlink_engine.orchestration.state import PipelineState, run_store

            # Create a new state (and thus run_id) upfront
            tmp_state = PipelineState.new([], Path("/tmp"), dossier_id)
            run_id = tmp_state["run_id"]
            upload_dir = Path("output") / "runs" / run_id / "input"
            upload_dir.mkdir(parents=True, exist_ok=True)

            saved: list[str] = []
            for uf in files:
                fname = Path(uf.filename or "upload").name
                dest = upload_dir / fname
                content = await uf.read()
                dest.write_bytes(content)
                saved.append(str(dest))

            output_dir = Path("output") / "runs" / run_id / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            state = PipelineState.new(
                [Path(p) for p in saved],
                output_dir,
                dossier_id or f"run-{run_id}",
            )
            # Force the same run_id we already advertised
            state["run_id"] = run_id
            run_store.create(state)

            return {
                "run_id": run_id,
                "dossier_id": state["dossier_id"],
                "files_received": [Path(p).name for p in saved],
                "status": "staged",
            }

        @app.post("/api/pipeline/run/{run_id}")
        def pipeline_run(run_id: str) -> dict[str, Any]:
            """Start the pipeline in a background thread for the given run_id."""
            from hyperlink_engine.orchestration.runner import PipelineRunner
            from hyperlink_engine.orchestration.state import run_store

            state = run_store.get(run_id)
            if state is None:
                raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
            if state.get("status") == "running" and state.get("current_node") not in ("", None):
                raise HTTPException(status_code=409, detail="Pipeline already running")

            runner = PipelineRunner()
            runner.run_in_background(state)
            return {"run_id": run_id, "status": "started"}

        @app.get("/api/pipeline/stream/{run_id}")
        async def pipeline_stream(run_id: str) -> StreamingResponse:
            """SSE endpoint: yields JSON events as the pipeline advances."""
            from hyperlink_engine.orchestration.events import event_bus

            # Ensure the async queue exists before the pipeline starts emitting
            event_bus.get_or_create_async_queue(run_id)

            return StreamingResponse(
                event_bus.subscribe_sse(run_id),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.get("/api/pipeline/status/{run_id}")
        def pipeline_status(run_id: str) -> dict[str, Any]:
            """Return the current status snapshot of a run."""
            from hyperlink_engine.orchestration.state import run_store

            state = run_store.get(run_id)
            if state is None:
                raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")
            return {
                "run_id": run_id,
                "dossier_id": state.get("dossier_id"),
                "current_node": state.get("current_node"),
                "status": state.get("status"),
                "score": state.get("score"),
                "grade": state.get("grade"),
                "total_links": len(state.get("links", [])),
                "linked_files": [Path(p).name for p in state.get("linked_files", [])],
                "error": state.get("error"),
            }

        @app.get("/api/pipeline/runs")
        def pipeline_list_runs() -> dict[str, Any]:
            """List all pipeline runs in this server process."""
            from hyperlink_engine.orchestration.state import run_store

            return {"runs": run_store.list_runs()}

        @app.get("/api/pipeline/run/{run_id}/results")
        def pipeline_results(run_id: str) -> dict[str, Any]:
            """Return the final results of a completed run."""
            from hyperlink_engine.orchestration.state import run_store

            state = run_store.get(run_id)
            if state is None:
                raise HTTPException(status_code=404, detail=f"run_id {run_id!r} not found")

            # Auto-reload results store with this run's data
            links = state.get("links", [])
            anomalies = state.get("anomalies", [])
            score_val = state.get("score", 0.0)
            grade = state.get("grade", "F")
            store.upsert_score(run_id, {
                "score": score_val,
                "grade": grade,
                "broken_links": sum(1 for l in links if l.get("status") == "broken"),
                "blocker_anomalies": len([a for a in anomalies if a.get("severity") == "blocker"]),
                "total_links": len(links),
                "ok_links": sum(1 for l in links if l.get("status") == "ok"),
                "is_submission_ready": score_val >= 80 and sum(1 for l in links if l.get("status") == "broken") == 0,
            })
            if links:
                store.set_links(run_id, links)
            if anomalies:
                store.append_anomalies(run_id, anomalies)

            return {
                "run_id": run_id,
                "dossier_id": state.get("dossier_id"),
                "status": state.get("status"),
                "score": score_val,
                "grade": grade,
                "total_links": len(links),
                "broken_links": sum(1 for l in links if l.get("status") == "broken"),
                "linked_files": [Path(p).name for p in state.get("linked_files", [])],
                "anomalies": anomalies,
                "error": state.get("error"),
            }

        @app.get("/api/pipeline/run/{run_id}/download/{filename}")
        def pipeline_download(run_id: str, filename: str) -> FileResponse:
            """Download a linked output file produced by the pipeline."""
            output_dir = Path("output") / "runs" / run_id / "output"
            file_path = output_dir / filename
            if not file_path.exists():
                raise HTTPException(status_code=404, detail=f"{filename!r} not found for run {run_id!r}")
            media = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if filename.endswith(".docx") else "application/pdf"
            )
            return FileResponse(
                path=str(file_path),
                filename=filename,
                media_type=media,
            )

        @app.get("/api/pipeline/run/{run_id}/csv")
        def pipeline_download_csv(run_id: str) -> Response:
            """Download the validation_report.csv for a run."""
            csv_path = Path("output") / "runs" / run_id / "output" / "validation_report.csv"
            if not csv_path.exists():
                raise HTTPException(status_code=404, detail="CSV not ready yet")
            headers_dict = {"Content-Disposition": f"attachment; filename={run_id}_validation_report.csv"}
            return Response(
                content=csv_path.read_text(encoding="utf-8"),
                media_type="text/csv",
                headers=headers_dict,
            )

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Polling helper (alternative to webhook)
# ─────────────────────────────────────────────────────────────────────────────


def poll_dossplorer_status_once(
    dossier_id: str,
    *,
    client: DossplorerClient | None = None,
    store: _ReportStore | None = None,
) -> dict[str, Any]:
    """Pull the current dossier metadata from Dossplorer and stash status.

    The CLI runs this on a cron / scheduled task — it's the no-webhook
    equivalent of the ``/webhook`` endpoint above.

    Returns a small dict suitable for logging / status pages.
    """
    client = client or get_client()
    store = store or _DEFAULT_STORE
    try:
        metadata = client.get_metadata(dossier_id)
    except DossplorerError as exc:
        _log.warning("dossplorer_poll_failed", dossier=dossier_id, error=str(exc))
        return {"dossier_id": dossier_id, "ok": False, "error": str(exc)}
    snapshot = {
        "dossier_id": dossier_id,
        "ok": True,
        "status": metadata.status,
        "sequence_number": metadata.sequence_number,
        "submission_type": metadata.submission_type,
    }
    store.record_webhook({"event": "poll", **snapshot})
    audit_event(
        "dashboard_poll_status",
        document=dossier_id,
        details={"status": metadata.status},
    )
    return snapshot


# ─────────────────────────────────────────────────────────────────────────────
# Module-level app (uvicorn entrypoint)
# ─────────────────────────────────────────────────────────────────────────────


if _FASTAPI_AVAILABLE:  # pragma: no cover - exercised via uvicorn at runtime
    app = create_app()
