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
    from fastapi import Depends, FastAPI, HTTPException, status
    from fastapi.responses import PlainTextResponse
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FASTAPI_AVAILABLE = False
    FastAPI = object  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

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


_DEFAULT_STORE = _ReportStore()


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

    store = report_store or _DEFAULT_STORE
    client_factory = dossplorer_client_factory or get_client

    # ── Health ────────────────────────────────────────────────────────────

    @app.get("/api/health", response_class=PlainTextResponse)
    def health() -> str:
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
