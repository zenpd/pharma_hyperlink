"""Unit tests for dashboard/api.py (W11.2 + W12.1)."""

from __future__ import annotations

from typing import Any

import pytest

# fastapi is optional — skip the module if not installed
pytest.importorskip("fastapi")

import asyncio  # noqa: E402

import httpx  # noqa: E402


class _DashboardTestClient:
    """Sync wrapper around httpx.AsyncClient + ASGITransport.

    starlette's bundled _DashboardTestClient is incompatible with httpx>=0.28
    (Client no longer accepts an `app=` kwarg) and ASGITransport is
    async-only.  We drive the async client through `asyncio.run` so
    the tests stay synchronous.
    """

    def __init__(self, app) -> None:
        self._app = app
        self._transport = httpx.ASGITransport(app=app)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        async def _run() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=self._transport, base_url="http://test"
            ) as client:
                return await client.request(method, url, **kw)

        return asyncio.run(_run())

    def get(self, url: str, **kw) -> httpx.Response:
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self._request("POST", url, **kw)

from hyperlink_engine.audit.trail import get_audit_trail, reset_audit_trail
from hyperlink_engine.dashboard.api import (  # noqa: E402
    _ReportStore,
    create_app,
    poll_dossplorer_status_once,
)
from hyperlink_engine.ingestion.dossplorer_client import (
    DossplorerError,
    MockDossplorerClient,
)
from hyperlink_engine.models import AnomalySeverity


# ── Fixtures ──────────────────────────────────────────────────────────────────


class _StubClient:
    """Records pushes; allows tests to inject failures."""

    def __init__(self) -> None:
        self.scores: list[tuple[str, float, str | None]] = []
        self.anomalies: list[dict[str, Any]] = []
        self.fail_with: Exception | None = None
        self._metadata: dict[str, Any] = {}

    def set_metadata(self, dossier_id: str, payload: dict[str, Any]) -> None:
        self._metadata[dossier_id] = payload

    def get_metadata(self, dossier_id: str):
        from hyperlink_engine.models import DossierMetadata

        if dossier_id not in self._metadata:
            raise DossplorerError(f"no such dossier {dossier_id}")
        return DossierMetadata.model_validate(self._metadata[dossier_id])

    def push_readiness_score(self, dossier_id, score, *, sequence=None):
        if self.fail_with is not None:
            exc = self.fail_with
            self.fail_with = None
            raise exc
        self.scores.append((dossier_id, score, sequence))

    def push_anomaly_flag(self, dossier_id, *, document, severity, message):
        self.anomalies.append(
            {
                "dossier_id": dossier_id,
                "document": document,
                "severity": severity.value,
                "message": message,
            }
        )


@pytest.fixture(autouse=True)
def _reset_audit(tmp_path) -> None:
    reset_audit_trail()
    get_audit_trail(tmp_path / "audit.jsonl")
    yield
    reset_audit_trail()


@pytest.fixture
def stub_client() -> _StubClient:
    return _StubClient()


@pytest.fixture
def store() -> _ReportStore:
    return _ReportStore()


@pytest.fixture
def client(stub_client: _StubClient, store: _ReportStore) -> _DashboardTestClient:
    app = create_app(
        dossplorer_client_factory=lambda: stub_client,
        report_store=store,
    )
    return _DashboardTestClient(app)


# ── /api/health ──────────────────────────────────────────────────────────────


def test_health_returns_ok(client: _DashboardTestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.text == "ok"


# ── /api/dossiers ────────────────────────────────────────────────────────────


def test_list_dossiers_empty_store_returns_empty_list(client: _DashboardTestClient) -> None:
    """When the injected client doesn't expose list_dossier_ids, the store is used."""
    resp = client.get("/api/dossiers")
    assert resp.status_code == 200
    assert resp.json()["dossiers"] == []


def test_list_dossiers_with_mock_client(store: _ReportStore) -> None:
    mock_client = MockDossplorerClient()
    app = create_app(
        dossplorer_client_factory=lambda: mock_client,
        report_store=store,
    )
    test_client = _DashboardTestClient(app)
    resp = test_client.get("/api/dossiers")
    assert resp.status_code == 200
    # MockDossplorerClient returns IDs from its fixture (may be empty)
    assert "dossiers" in resp.json()


# ── /api/dossiers/{id}/score ─────────────────────────────────────────────────


def test_get_score_404_when_missing(client: _DashboardTestClient) -> None:
    resp = client.get("/api/dossiers/UNKNOWN/score")
    assert resp.status_code == 404


def test_get_score_returns_stored_payload(
    client: _DashboardTestClient, store: _ReportStore
) -> None:
    store.upsert_score(
        "D-001",
        {
            "score": 92.5,
            "grade": "B",
            "broken_links": 2,
            "blocker_anomalies": 0,
            "is_submission_ready": True,
        },
    )
    resp = client.get("/api/dossiers/D-001/score")
    assert resp.status_code == 200
    data = resp.json()
    assert data["dossier_id"] == "D-001"
    assert data["score"] == 92.5
    assert data["grade"] == "B"
    assert data["is_submission_ready"] is True


# ── /api/dossiers/{id}/anomalies ─────────────────────────────────────────────


def test_get_anomalies_empty(client: _DashboardTestClient) -> None:
    resp = client.get("/api/dossiers/D-001/anomalies")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_get_anomalies_with_data(client: _DashboardTestClient, store: _ReportStore) -> None:
    store.append_anomalies(
        "D-001",
        [
            {"severity": "blocker", "document": "a.docx", "message": "broken"},
            {"severity": "warning", "document": "b.docx", "message": "orphan"},
        ],
    )
    resp = client.get("/api/dossiers/D-001/anomalies")
    assert resp.json()["count"] == 2


def test_get_anomalies_filtered_by_severity(
    client: _DashboardTestClient, store: _ReportStore
) -> None:
    store.append_anomalies(
        "D-001",
        [
            {"severity": "blocker", "document": "a.docx", "message": "x"},
            {"severity": "warning", "document": "b.docx", "message": "y"},
            {"severity": "blocker", "document": "c.docx", "message": "z"},
        ],
    )
    resp = client.get("/api/dossiers/D-001/anomalies?severity=blocker")
    assert resp.json()["count"] == 2


# ── /api/dossiers/{id}/links ─────────────────────────────────────────────────


def test_get_links_empty(client: _DashboardTestClient) -> None:
    resp = client.get("/api/dossiers/D-001/links")
    assert resp.json()["count"] == 0


def test_get_links_filtered(client: _DashboardTestClient, store: _ReportStore) -> None:
    store.set_links(
        "D-001",
        [
            {"status": "ok", "link_text": "Section 1"},
            {"status": "broken", "link_text": "Section 2"},
        ],
    )
    resp = client.get("/api/dossiers/D-001/links?link_status=broken")
    assert resp.json()["count"] == 1


# ── /api/dossiers/{id}/push ──────────────────────────────────────────────────


def test_push_dispatches_to_dossplorer(
    client: _DashboardTestClient, stub_client: _StubClient
) -> None:
    resp = client.post(
        "/api/dossiers/D-001/push",
        json={
            "score": 88.0,
            "sequence": "0001",
            "anomalies": [
                {
                    "document": "m2.docx",
                    "severity": "warning",
                    "message": "orphan ref",
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pushed"
    assert stub_client.scores == [("D-001", 88.0, "0001")]
    assert len(stub_client.anomalies) == 1


def test_push_502_when_dossplorer_errors(
    client: _DashboardTestClient, stub_client: _StubClient
) -> None:
    stub_client.fail_with = DossplorerError("network down")
    resp = client.post(
        "/api/dossiers/D-001/push",
        json={"score": 90.0, "anomalies": []},
    )
    assert resp.status_code == 502


def test_push_writes_audit_event(
    client: _DashboardTestClient, stub_client: _StubClient
) -> None:
    client.post("/api/dossiers/D-001/push", json={"score": 90.0, "anomalies": []})
    records = get_audit_trail().read_all()
    assert any(r["action"] == "dashboard_push_dispatched" for r in records)


# ── /api/dossiers/{id}/webhook ───────────────────────────────────────────────


def test_webhook_accepts_matching_dossier_id(
    client: _DashboardTestClient, store: _ReportStore
) -> None:
    resp = client.post(
        "/api/dossiers/D-001/webhook",
        json={
            "event": "review_started",
            "dossier_id": "D-001",
            "timestamp": "2026-05-27T10:00:00Z",
            "details": {"reviewer": "ops"},
        },
    )
    assert resp.status_code == 200
    assert store.webhook_events[-1]["event"] == "review_started"


def test_webhook_rejects_mismatched_dossier_id(client: _DashboardTestClient) -> None:
    resp = client.post(
        "/api/dossiers/D-001/webhook",
        json={
            "event": "x",
            "dossier_id": "D-OTHER",
            "timestamp": "2026-05-27T10:00:00Z",
        },
    )
    assert resp.status_code == 400


# ── poll_dossplorer_status_once ──────────────────────────────────────────────


def test_poll_returns_status_when_dossier_exists(
    stub_client: _StubClient, store: _ReportStore
) -> None:
    stub_client.set_metadata(
        "D-001",
        {
            "dossier_id": "D-001",
            "sponsor": "SunPharma",
            "submission_type": "NDA",
            "sequence_number": "0001",
            "status": "in_review",
        },
    )
    result = poll_dossplorer_status_once("D-001", client=stub_client, store=store)
    assert result["ok"] is True
    assert result["status"] == "in_review"
    assert any(e["event"] == "poll" for e in store.webhook_events)


def test_poll_returns_error_on_failure(
    stub_client: _StubClient, store: _ReportStore
) -> None:
    result = poll_dossplorer_status_once("D-GHOST", client=stub_client, store=store)
    assert result["ok"] is False
    assert "no such dossier" in result["error"]
