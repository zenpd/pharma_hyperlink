"""PLAN SEVEN Phase 3 — document classification gate (Feature B).

Covers the four enforcement points without a live SuperTokens core:

* run state carries ``classification`` + ``owner`` (default from settings);
* list endpoints (``/api/pipeline/runs``, ``/api/review/queue``) hide
  classified runs from non-cleared callers while the gate is active;
* run-scoped content reads 403 on classified runs for non-cleared callers;
* the upload endpoint only lets admins produce classified runs.

The ``login_as`` helper (conftest) overrides the auth gate + principal, and
``mw.set_auth_override(True)`` activates enforcement for a single test (the
autouse ``_reset_security_mode`` fixture clears it again).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

import httpx  # noqa: E402

from hyperlink_engine.api import middleware as mw  # noqa: E402
from hyperlink_engine.api.app import create_app  # noqa: E402
from hyperlink_engine.config.settings import get_settings  # noqa: E402
from hyperlink_engine.orchestration.state import PipelineState, run_store  # noqa: E402


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


def _make_run(classification: str, status: str = "done") -> str:
    """Stage a finished run with the given classification in the run store."""
    state = PipelineState.new(
        [], Path("output"), dossier_id=f"cls-{classification}", classification=classification
    )
    state["status"] = status
    run_store.create(state)
    return state["run_id"]


# ── State model ─────────────────────────────────────────────────────────────


def test_new_run_takes_settings_default_classification() -> None:
    state = PipelineState.new([], Path("output"))
    assert state["classification"] == get_settings().default_classification
    assert state["classification"] in ("classified", "unclassified")
    assert state["owner"] == "system:hyperlink-engine"


def test_explicit_classification_and_owner_win() -> None:
    state = PipelineState.new(
        [], Path("output"), classification="unclassified", owner="u-alice"
    )
    assert state["classification"] == "unclassified"
    assert state["owner"] == "u-alice"


def test_list_runs_summary_includes_classification() -> None:
    rid = _make_run("classified")
    summary = next(s for s in run_store.list_runs() if s["run_id"] == rid)
    assert summary["classification"] == "classified"
    assert "owner" in summary


# ── List filtering ──────────────────────────────────────────────────────────


def test_lists_hide_classified_for_non_cleared_user(make_principal, login_as_fixture) -> None:
    classified = _make_run("classified")
    unclassified = _make_run("unclassified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)

    ids = {r["run_id"] for r in c.get("/api/pipeline/runs?include_all=true").json()["runs"]}
    assert unclassified in ids
    assert classified not in ids

    queue_ids = {r["run_id"] for r in c.get("/api/review/queue").json()["runs"]}
    assert unclassified in queue_ids
    assert classified not in queue_ids


def test_lists_show_classified_to_admin(make_principal, login_as_fixture) -> None:
    classified = _make_run("classified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("admin",)))
    mw.set_auth_override(True)

    ids = {r["run_id"] for r in c.get("/api/pipeline/runs?include_all=true").json()["runs"]}
    assert classified in ids
    queue_ids = {r["run_id"] for r in c.get("/api/review/queue").json()["runs"]}
    assert classified in queue_ids


def test_lists_open_when_auth_off() -> None:
    classified = _make_run("classified")
    c = _Client(create_app())
    ids = {r["run_id"] for r in c.get("/api/pipeline/runs?include_all=true").json()["runs"]}
    assert classified in ids


# ── Run-scoped content reads ────────────────────────────────────────────────


def test_classified_content_403_for_non_cleared_user(make_principal, login_as_fixture) -> None:
    classified = _make_run("classified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)

    for url in (
        f"/api/pipeline/run/{classified}/links",
        f"/api/pipeline/run/{classified}/results",
        f"/api/pipeline/run/{classified}/export.csv",
        f"/api/pipeline/status/{classified}",
    ):
        assert c.get(url).status_code == 403, url


def test_unclassified_content_readable_by_user(make_principal, login_as_fixture) -> None:
    unclassified = _make_run("unclassified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)
    assert c.get(f"/api/pipeline/run/{unclassified}/links").status_code == 200


def test_classified_content_readable_by_admin(make_principal, login_as_fixture) -> None:
    classified = _make_run("classified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("admin",)))
    mw.set_auth_override(True)
    assert c.get(f"/api/pipeline/run/{classified}/links").status_code == 200


def test_classified_content_open_when_auth_off() -> None:
    classified = _make_run("classified")
    c = _Client(create_app())
    assert c.get(f"/api/pipeline/run/{classified}/links").status_code == 200


def test_missing_run_still_404s_not_403(make_principal, login_as_fixture) -> None:
    """The gate must leave the endpoint's own 404 authoritative."""
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)
    assert c.get("/api/pipeline/run/no-such-run/links").status_code == 404


# ── Review signoff + Compliance Gate endpoints ──────────────────────────────
# Regression for a live finding (2026-06-10): /api/compliance/{run_id}
# answered 200 with the full eCTD checklist for a non-cleared user on a
# classified run, and a non-admin could approve/reject a classified run that
# was hidden from their review queue.


def test_review_and_compliance_403_on_classified_for_non_cleared_user(
    make_principal, login_as_fixture
) -> None:
    classified = _make_run("classified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)

    assert c.get(f"/api/compliance/{classified}").status_code == 403
    assert c.post(f"/api/compliance/{classified}/submit", json={}).status_code == 403
    assert c.post(f"/api/review/{classified}/approve", json={}).status_code == 403
    assert c.post(f"/api/review/{classified}/reject", json={"comment": "x"}).status_code == 403


def test_review_and_compliance_allowed_for_admin_on_classified(
    make_principal, login_as_fixture
) -> None:
    classified = _make_run("classified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("admin",)))
    mw.set_auth_override(True)

    assert c.get(f"/api/compliance/{classified}").status_code == 200
    assert c.post(f"/api/review/{classified}/approve", json={}).status_code == 200


def test_review_and_compliance_open_on_unclassified_for_user(
    make_principal, login_as_fixture
) -> None:
    unclassified = _make_run("unclassified")
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)

    assert c.get(f"/api/compliance/{unclassified}").status_code == 200


# ── Upload gating ───────────────────────────────────────────────────────────

_DOCX = [("files", ("doc.docx", b"stub-docx-bytes", "application/octet-stream"))]


def test_upload_classified_requires_admin(make_principal, login_as_fixture) -> None:
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("user",)))
    mw.set_auth_override(True)
    r = c.post("/api/pipeline/upload", files=_DOCX, data={"classification": "classified"})
    assert r.status_code == 403


def test_non_admin_uploads_forced_unclassified(make_principal, login_as_fixture) -> None:
    """A user's default upload must not inherit the 'classified' default —
    they would lock themselves out of their own run."""
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(user_id="u-bob", roles=("user",)))
    mw.set_auth_override(True)
    r = c.post("/api/pipeline/upload", files=_DOCX)
    assert r.status_code == 200
    assert r.json()["classification"] == "unclassified"
    state = run_store.get(r.json()["run_id"])
    assert state is not None and state["owner"] == "u-bob"


def test_admin_can_mark_upload_classified(make_principal, login_as_fixture) -> None:
    app = create_app()
    c = _Client(app)
    login_as_fixture(app, make_principal(roles=("admin",)))
    mw.set_auth_override(True)
    r = c.post("/api/pipeline/upload", files=_DOCX, data={"classification": "classified"})
    assert r.status_code == 200
    assert r.json()["classification"] == "classified"


def test_upload_rejects_bogus_classification() -> None:
    c = _Client(create_app())
    r = c.post("/api/pipeline/upload", files=_DOCX, data={"classification": "top-secret"})
    assert r.status_code == 400
