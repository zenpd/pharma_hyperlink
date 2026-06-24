"""PLAN SEVEN Phase 2 — Security toggle (Feature C) + identity binding.

These exercise the auth wiring *without* a live SuperTokens core: the
``login_as`` helper (conftest) overrides the gate + principal so we can assert
role enforcement and identity binding deterministically.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

import httpx  # noqa: E402

from hyperlink_engine.api import middleware as mw  # noqa: E402
from hyperlink_engine.api.app import create_app  # noqa: E402


class _Client:
    """Tiny sync wrapper over httpx.ASGITransport (httpx>=0.28 compatible)."""

    def __init__(self, app) -> None:
        self._t = httpx.ASGITransport(app=app)

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        async def _run() -> httpx.Response:
            async with httpx.AsyncClient(transport=self._t, base_url="http://test") as c:
                return await c.request(method, url, **kw)

        return asyncio.run(_run())

    def get(self, url: str, **kw) -> httpx.Response:
        return self._req("GET", url, **kw)

    def post(self, url: str, **kw) -> httpx.Response:
        return self._req("POST", url, **kw)


# ── Security toggle ─────────────────────────────────────────────────────────


def test_security_mode_default_off() -> None:
    c = _Client(create_app())
    r = c.get("/api/security/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["source"] == "settings"


def test_enabling_fails_closed_without_sdk(monkeypatch) -> None:
    """Turning the gate on while the SDK is absent must fail *closed* (503),
    never silently open. Simulated via the availability flag so the test is
    deterministic whether or not supertokens-python is installed."""
    monkeypatch.setattr(mw, "_SUPERTOKENS_AVAILABLE", False)
    app = create_app()
    c = _Client(app)
    enabled = c.post("/api/security/mode", json={"enabled": True})
    assert enabled.status_code == 200 and enabled.json()["enabled"] is True
    # A protected route now requires a session; SDK missing → 503 (fail closed).
    assert c.get("/api/dossiers").status_code == 503


def test_disable_requires_admin_when_active(make_principal, login_as_fixture) -> None:
    app = create_app()
    c = _Client(app)
    # Enable while off — the open SYSTEM principal is an admin, so allowed.
    assert c.post("/api/security/mode", json={"enabled": True}).json()["enabled"] is True

    # Now active: a non-admin user may NOT disable it.
    login_as_fixture(app, make_principal(roles=("user",)))
    assert c.post("/api/security/mode", json={"enabled": False}).status_code == 403

    # An admin may.
    login_as_fixture(app, make_principal(roles=("admin",)))
    r = c.post("/api/security/mode", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False


def test_security_mode_get_public_but_post_protected(monkeypatch) -> None:
    """Pre-login the SPA must be able to READ the gate status (GET public),
    but an anonymous caller must never be able to FLIP it (POST protected —
    a public POST would inherit the open SYSTEM principal)."""
    monkeypatch.setattr(mw, "_SUPERTOKENS_AVAILABLE", False)
    app = create_app()
    c = _Client(app)
    mw.set_auth_override(True)
    r = c.get("/api/security/mode")
    assert r.status_code == 200 and r.json()["enabled"] is True
    # Anonymous flip attempt: the guard rejects it before the handler runs
    # (503 here because the SDK is simulated absent; 401 with it installed).
    assert c.post("/api/security/mode", json={"enabled": False}).status_code in (401, 503)
    # And the gate is still on.
    assert c.get("/api/security/mode").json()["enabled"] is True


# ── /api/me session probe (PLAN SEVEN Phase 4 SPA support) ──────────────────


def test_me_returns_system_principal_when_off() -> None:
    body = _Client(create_app()).get("/api/me").json()
    assert body["user_id"] == "system:hyperlink-engine"
    assert body["is_admin"] is True
    assert body["can_read_classified"] is True
    assert body["security_enabled"] is False


def test_me_returns_logged_in_identity(make_principal, login_as_fixture) -> None:
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(user_id="u-1", email="x@example.com", roles=("user",)))
    mw.set_auth_override(True)
    body = c.get("/api/me").json()
    assert body["user_id"] == "u-1"
    assert body["email"] == "x@example.com"
    assert body["is_admin"] is False
    assert body["security_enabled"] is True


# ── Identity binding ────────────────────────────────────────────────────────


def test_review_approve_binds_logged_in_identity(make_principal, login_as_fixture) -> None:
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(user_id="u-officer", email="officer@example.com"))
    mw.set_auth_override(True)  # gate active → identity wins over body
    r = c.post("/api/review/run-xyz/approve", json={"comment": "looks good"})
    assert r.status_code == 200
    assert r.json()["reviewer"] == "officer@example.com"


def test_review_reject_requires_comment_and_binds_identity(make_principal, login_as_fixture) -> None:
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(user_id="u-officer", email="officer@example.com"))
    mw.set_auth_override(True)
    # Missing comment → 400.
    assert c.post("/api/review/run-xyz/reject", json={}).status_code == 400
    r = c.post("/api/review/run-xyz/reject", json={"comment": "broken link"})
    assert r.status_code == 200
    assert r.json()["reviewer"] == "officer@example.com"


def test_review_reviewer_falls_back_to_body_when_auth_off() -> None:
    """With the gate off, the demo body-supplied reviewer is preserved."""
    app = create_app()
    c = _Client(app)
    r = c.post("/api/review/run-xyz/approve", json={"reviewer": "Dr. Demo", "comment": "ok"})
    assert r.status_code == 200
    assert r.json()["reviewer"] == "Dr. Demo"
