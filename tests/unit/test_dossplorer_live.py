"""Unit tests for LiveDossplorerClient (W11.1)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from hyperlink_engine.audit.trail import get_audit_trail, reset_audit_trail
from hyperlink_engine.ingestion.dossplorer_client import (
    DossplorerError,
    LiveDossplorerClient,
    MockDossplorerClient,
    _OAuth2TokenCache,
    get_client,
)
from hyperlink_engine.models import AnomalySeverity


# ── Fake HTTP client ──────────────────────────────────────────────────────────


class _FakeResponse:
    """Mimics the httpx.Response surface the live client touches."""

    def __init__(
        self,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._json


class _FakeHttpClient:
    """Records every call; returns canned responses in order."""

    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [])
        self.fail_with: Exception | None = None

    def _next(self) -> _FakeResponse:
        if self.fail_with is not None:
            exc = self.fail_with
            self.fail_with = None
            raise exc
        if not self._responses:
            return _FakeResponse(status_code=500, text="unexpected call")
        return self._responses.pop(0)

    def post(self, url: str, *, data: dict | None = None, timeout: float | None = None) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "data": data})
        return self._next()

    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.calls.append(
            {"method": method, "url": url, "json": json, "headers": headers}
        )
        return self._next()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_client(responses: list[_FakeResponse]) -> tuple[LiveDossplorerClient, _FakeHttpClient]:
    http = _FakeHttpClient(responses)
    client = LiveDossplorerClient(
        base_url="https://dossplorer.example.com",
        client_id="cid",
        client_secret="csec",
        timeout=1.0,
        retries=3,
        http_client=http,
    )
    return client, http


_TOKEN_RESP = _FakeResponse(
    status_code=200,
    json_data={"access_token": "fake-token", "expires_in": 3600},
)


@pytest.fixture(autouse=True)
def _reset_audit(tmp_path) -> None:
    reset_audit_trail()
    get_audit_trail(tmp_path / "audit.jsonl")
    yield
    reset_audit_trail()


# ── _OAuth2TokenCache ─────────────────────────────────────────────────────────


def test_token_cache_returns_none_when_empty() -> None:
    cache = _OAuth2TokenCache()
    assert cache.get() is None


def test_token_cache_returns_token_when_fresh() -> None:
    cache = _OAuth2TokenCache()
    cache.set("t1", expires_in=3600)
    assert cache.get() == "t1"


def test_token_cache_expires(monkeypatch) -> None:
    cache = _OAuth2TokenCache()
    cache.set("t1", expires_in=60)  # nominal 60-second token
    # Advance the clock past expiry
    real_now = time.time()
    monkeypatch.setattr(time, "time", lambda: real_now + 120)
    assert cache.get() is None


def test_token_cache_clear() -> None:
    cache = _OAuth2TokenCache()
    cache.set("t1", expires_in=3600)
    cache.clear()
    assert cache.get() is None


# ── get_metadata ─────────────────────────────────────────────────────────────


def test_get_metadata_succeeds() -> None:
    metadata_resp = _FakeResponse(
        status_code=200,
        json_data={
            "dossier_id": "D-001",
            "sponsor": "SunPharma",
            "submission_type": "NDA",
            "sequence_number": "0001",
            "study_ids": ["SP-2024-001"],
        },
    )
    client, http = _make_client([_TOKEN_RESP, metadata_resp])
    meta = client.get_metadata("D-001")
    assert meta.dossier_id == "D-001"
    assert meta.submission_type == "NDA"
    # Token fetch + actual request
    assert len(http.calls) == 2


def test_get_metadata_uses_cached_token_on_second_call() -> None:
    meta_resp = _FakeResponse(
        status_code=200,
        json_data={
            "dossier_id": "D-001",
            "sponsor": "SunPharma",
            "submission_type": "NDA",
            "sequence_number": "0001",
        },
    )
    meta_resp2 = _FakeResponse(
        status_code=200,
        json_data={
            "dossier_id": "D-002",
            "sponsor": "SunPharma",
            "submission_type": "MAA",
            "sequence_number": "0001",
        },
    )
    client, http = _make_client([_TOKEN_RESP, meta_resp, meta_resp2])
    client.get_metadata("D-001")
    client.get_metadata("D-002")
    # Token request + 2 metadata requests = 3 calls
    assert len(http.calls) == 3
    assert http.calls[0]["url"].endswith("/oauth/token")


def test_get_metadata_404_raises() -> None:
    client, _ = _make_client([_TOKEN_RESP, _FakeResponse(status_code=404, text="not found")])
    with pytest.raises(DossplorerError):
        client.get_metadata("D-ghost")


def test_get_metadata_malformed_body_raises() -> None:
    client, _ = _make_client(
        [_TOKEN_RESP, _FakeResponse(status_code=200, json_data={"wrong": "shape"})]
    )
    with pytest.raises(DossplorerError):
        client.get_metadata("D-001")


# ── push_readiness_score ─────────────────────────────────────────────────────


def test_push_readiness_score_ok() -> None:
    client, http = _make_client(
        [_TOKEN_RESP, _FakeResponse(status_code=200, json_data={"ok": True})]
    )
    client.push_readiness_score("D-001", 92.5, sequence="0001")
    post_call = http.calls[-1]
    assert post_call["method"] == "POST"
    assert post_call["url"].endswith("/v1/dossiers/D-001/qc-reports")
    assert post_call["json"]["score"] == 92.5


def test_push_readiness_score_rejects_out_of_range() -> None:
    client, _ = _make_client([])
    with pytest.raises(DossplorerError):
        client.push_readiness_score("D-001", 150.0)


def test_push_readiness_score_writes_audit_event() -> None:
    client, _ = _make_client(
        [_TOKEN_RESP, _FakeResponse(status_code=200, json_data={"ok": True})]
    )
    client.push_readiness_score("D-001", 88.0, sequence="0001")
    records = get_audit_trail().read_all()
    assert any(r["action"] == "dossplorer_score_pushed" for r in records)


# ── push_anomaly_flag ────────────────────────────────────────────────────────


def test_push_anomaly_flag_ok() -> None:
    client, http = _make_client(
        [_TOKEN_RESP, _FakeResponse(status_code=200, json_data={"ok": True})]
    )
    client.push_anomaly_flag(
        "D-001",
        document="m2/2-5.docx",
        severity=AnomalySeverity.BLOCKER,
        message="broken link",
    )
    body = http.calls[-1]["json"]
    assert body["document"] == "m2/2-5.docx"
    assert body["severity"] == "blocker"


def test_push_anomaly_flag_writes_audit() -> None:
    client, _ = _make_client(
        [_TOKEN_RESP, _FakeResponse(status_code=200, json_data={"ok": True})]
    )
    client.push_anomaly_flag(
        "D-001",
        document="x.docx",
        severity=AnomalySeverity.WARNING,
        message="orphan",
    )
    records = get_audit_trail().read_all()
    assert any(r["action"] == "dossplorer_anomaly_pushed" for r in records)


# ── Retry logic ──────────────────────────────────────────────────────────────


def test_retry_on_5xx_then_success(monkeypatch) -> None:
    # Suppress real sleeps so the test stays fast
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client, _ = _make_client(
        [
            _TOKEN_RESP,
            _FakeResponse(status_code=503, text="upstream busy"),
            _FakeResponse(status_code=200, json_data={"ok": True}),
        ]
    )
    client.push_readiness_score("D-001", 90.0)
    # Successful after one 5xx retry


def test_retry_on_401_clears_token_and_retries(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    # 1st call: token, 2nd call: 401, 3rd call: token refresh, 4th call: 200
    client, http = _make_client(
        [
            _TOKEN_RESP,
            _FakeResponse(status_code=401, text="expired"),
            _TOKEN_RESP,
            _FakeResponse(status_code=200, json_data={"ok": True}),
        ]
    )
    client.push_readiness_score("D-001", 90.0)
    # Should have hit /oauth/token twice (once initial, once after 401)
    token_calls = [c for c in http.calls if c["url"].endswith("/oauth/token")]
    assert len(token_calls) == 2


def test_retry_exhausted_raises(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    client, _ = _make_client(
        [
            _TOKEN_RESP,
            _FakeResponse(status_code=503),
            _FakeResponse(status_code=503),
            _FakeResponse(status_code=503),
        ]
    )
    with pytest.raises(DossplorerError):
        client.push_readiness_score("D-001", 90.0)


def test_network_error_then_success(monkeypatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _: None)
    http = _FakeHttpClient(
        [
            _TOKEN_RESP,
            _FakeResponse(status_code=200, json_data={"ok": True}),
        ]
    )
    # First request raises before any response comes back
    original_request = http.request

    call_count = [0]

    def flaky_request(method, url, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise ConnectionError("transient")
        return original_request(method, url, **kw)

    http.request = flaky_request  # type: ignore[assignment]

    client = LiveDossplorerClient(
        base_url="https://dossplorer.example.com",
        client_id="cid",
        client_secret="csec",
        retries=3,
        http_client=http,
    )
    client.push_readiness_score("D-001", 90.0)


# ── Token fetch errors ──────────────────────────────────────────────────────


def test_token_fetch_non_200_raises() -> None:
    client, _ = _make_client([_FakeResponse(status_code=500, text="oops")])
    with pytest.raises(DossplorerError):
        client.get_metadata("D-001")


def test_token_fetch_missing_access_token_raises() -> None:
    client, _ = _make_client([_FakeResponse(status_code=200, json_data={})])
    with pytest.raises(DossplorerError):
        client.get_metadata("D-001")


# ── Factory ──────────────────────────────────────────────────────────────────


def test_get_client_defaults_to_mock(monkeypatch) -> None:
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_MODE", raising=False)
    client = get_client(override_mode="mock")
    assert isinstance(client, MockDossplorerClient)


def test_get_client_live_requires_credentials(monkeypatch) -> None:
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_BASE_URL", raising=False)
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_CLIENT_ID", raising=False)
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_CLIENT_SECRET", raising=False)
    with pytest.raises(DossplorerError):
        get_client(override_mode="live")


def test_get_client_live_with_credentials(monkeypatch) -> None:
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_BASE_URL", "https://x.test")
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_CLIENT_ID", "cid")
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_CLIENT_SECRET", "csec")
    client = get_client(override_mode="live")
    assert isinstance(client, LiveDossplorerClient)
