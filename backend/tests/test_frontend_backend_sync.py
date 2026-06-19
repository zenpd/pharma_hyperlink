"""Test frontend-backend API sync.

These tests exercise the FastAPI app directly via httpx ASGI transport,
verifying every endpoint the React frontend relies on.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

import httpx  # noqa: E402

from hyperlink_engine.api.app import create_app  # noqa: E402
from hyperlink_engine.audit.trail import get_audit_trail, reset_audit_trail  # noqa: E402

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_client():
    """Build a test client against the default app (with demo data)."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    def _sync(method: str, url: str, **kw) -> httpx.Response:
        async def _run():
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                return await client.request(method, url, **kw)

        return asyncio.run(_run())

    class _Client:
        get = staticmethod(lambda url, **kw: _sync("GET", url, **kw))
        post = staticmethod(lambda url, **kw: _sync("POST", url, **kw))

    return _Client()


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _audit(tmp_path):
    reset_audit_trail()
    get_audit_trail(tmp_path / "audit.jsonl")
    yield
    reset_audit_trail()


@pytest.fixture
def client():
    return _make_client()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestHealthEndpoints:
    """Verify both health routes respond."""

    def test_api_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.text == "ok"

    def test_legacy_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "ok"


class TestDossierScore:
    """GET /api/dossiers/{id}/score — frontend Overview panel."""

    def test_returns_json_with_score(self, client):
        resp = client.get("/api/dossiers/demo/score")
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert isinstance(data["score"], (int, float))
        assert "dossier_id" in data
        assert data["dossier_id"] == "demo"

    def test_includes_grade_and_readiness(self, client):
        data = client.get("/api/dossiers/demo/score").json()
        assert "grade" in data
        assert "is_submission_ready" in data

    def test_unknown_dossier_returns_404(self, client):
        resp = client.get("/api/dossiers/DOES_NOT_EXIST/score")
        assert resp.status_code == 404


class TestAnomaliesEndpoint:
    """GET /api/dossiers/{id}/anomalies — frontend Anomalies panel."""

    def test_returns_wrapped_list(self, client):
        resp = client.get("/api/dossiers/demo/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        assert "anomalies" in data
        assert isinstance(data["anomalies"], list)
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_severity_filter(self, client):
        resp = client.get("/api/dossiers/demo/anomalies?severity=warning")
        assert resp.status_code == 200


class TestLinksEndpoint:
    """GET /api/dossiers/{id}/links — frontend Links panel."""

    def test_returns_wrapped_list(self, client):
        resp = client.get("/api/dossiers/demo/links")
        assert resp.status_code == 200
        data = resp.json()
        assert "links" in data
        assert isinstance(data["links"], list)
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_link_status_filter(self, client):
        resp = client.get("/api/dossiers/demo/links?link_status=ok")
        assert resp.status_code == 200


class TestExportEndpoints:
    """GET /api/dossiers/{id}/export.csv and .xlsx — frontend Export panel."""

    def test_csv_export(self, client):
        resp = client.get("/api/dossiers/demo/export.csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_xlsx_export(self, client):
        resp = client.get("/api/dossiers/demo/export.xlsx")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers.get("content-type", "")


class TestDossierListing:
    """GET /api/dossiers — frontend sidebar."""

    def test_returns_dossier_list(self, client):
        resp = client.get("/api/dossiers")
        assert resp.status_code == 200
        data = resp.json()
        assert "dossiers" in data
        assert isinstance(data["dossiers"], list)
