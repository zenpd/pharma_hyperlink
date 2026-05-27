"""Layer 1 — Dossplorer API client.

Two implementations behind the same :class:`DossplorerClient` protocol:

* :class:`MockDossplorerClient` — file-backed stub used by Phase 1 / Phase 2
  tests and demos.  Pushes are stored in an in-memory buffer.
* :class:`LiveDossplorerClient` — HTTP client used in Phase 3 once
  Dossplorer credentials are available.  Speaks the OAuth2 client-credentials
  flow per ADR-0002 and posts to:

      GET   /v1/dossiers/{id}
      POST  /v1/dossiers/{id}/qc-reports
      POST  /v1/dossiers/{id}/anomaly-flags

The factory :func:`get_client` returns whichever backend the environment
selects (``HYPERLINK_DOSSPLORER_MODE``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Protocol

try:  # httpx is a hard dep but guard for clean imports during scaffolding
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from hyperlink_engine.audit.trail import audit_event
from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.models import (
    AnomalySeverity,
    DossierMetadata,
)

_log = get_logger("ingestion.dossplorer")

_DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "fixtures" / "dossplorer_dossiers.json"
)


class DossplorerError(RuntimeError):
    """Raised when Dossplorer (mock or live) cannot satisfy a request."""


class DossplorerClient(Protocol):
    """The interface Phase 3's live client must satisfy."""

    def get_metadata(self, dossier_id: str) -> DossierMetadata: ...

    def push_readiness_score(
        self, dossier_id: str, score: float, *, sequence: str | None = None
    ) -> None: ...

    def push_anomaly_flag(
        self,
        dossier_id: str,
        *,
        document: str,
        severity: AnomalySeverity,
        message: str,
    ) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Mock client (Phase 1 / Phase 2)
# ─────────────────────────────────────────────────────────────────────────────


class MockDossplorerClient:
    """File-backed Dossplorer stand-in.

    Reads dossier metadata from a JSON fixture; collects every push call in
    an in-memory buffer that tests and the dashboard can inspect.
    """

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = Path(fixture_path) if fixture_path else _DEFAULT_FIXTURE_PATH
        self._dossiers: dict[str, DossierMetadata] = {}
        self.pushed_scores: list[dict[str, object]] = []
        self.pushed_anomalies: list[dict[str, object]] = []
        self._load_fixture()

    def _load_fixture(self) -> None:
        if not self._fixture_path.exists():
            _log.warning("dossplorer_fixture_missing", path=str(self._fixture_path))
            return
        try:
            raw = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DossplorerError(
                f"fixture {self._fixture_path} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(raw, list):
            raise DossplorerError(
                f"fixture {self._fixture_path} must be a JSON list of dossiers"
            )
        for entry in raw:
            try:
                meta = DossierMetadata.model_validate(entry)
            except Exception as exc:
                raise DossplorerError(f"invalid dossier entry in fixture: {exc}") from exc
            self._dossiers[meta.dossier_id] = meta

    # ---- Read API ------------------------------------------------------------

    def get_metadata(self, dossier_id: str) -> DossierMetadata:
        try:
            return self._dossiers[dossier_id]
        except KeyError as exc:
            raise DossplorerError(f"dossier {dossier_id!r} not found in fixture") from exc

    def list_dossier_ids(self) -> list[str]:
        return sorted(self._dossiers.keys())

    # ---- Write API (buffer-only in mock mode) -------------------------------

    def push_readiness_score(
        self, dossier_id: str, score: float, *, sequence: str | None = None
    ) -> None:
        if dossier_id not in self._dossiers:
            raise DossplorerError(f"cannot push score for unknown dossier {dossier_id!r}")
        if not 0.0 <= score <= 100.0:
            raise DossplorerError(f"score {score} out of range [0,100]")
        record = {"dossier_id": dossier_id, "score": score, "sequence": sequence}
        self.pushed_scores.append(record)
        _log.info("dossplorer_push_score_mock", **record)

    def push_anomaly_flag(
        self,
        dossier_id: str,
        *,
        document: str,
        severity: AnomalySeverity,
        message: str,
    ) -> None:
        if dossier_id not in self._dossiers:
            raise DossplorerError(f"cannot push anomaly for unknown dossier {dossier_id!r}")
        record = {
            "dossier_id": dossier_id,
            "document": document,
            "severity": severity.value,
            "message": message,
        }
        self.pushed_anomalies.append(record)
        _log.info("dossplorer_push_anomaly_mock", **record)


# ─────────────────────────────────────────────────────────────────────────────
# Live HTTP client (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────


class _OAuth2TokenCache:
    """Threadsafe cache for an OAuth2 client-credentials access token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str | None:
        with self._lock:
            if self._token and time.time() < self._expires_at - 5.0:
                return self._token
            return None

    def set(self, token: str, expires_in: float) -> None:
        with self._lock:
            self._token = token
            self._expires_at = time.time() + max(expires_in, 30.0)

    def clear(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0


class LiveDossplorerClient:
    """HTTP client speaking the contract from ADR-0002.

    Authentication: OAuth2 client-credentials.  The client fetches a bearer
    token from ``{base_url}/oauth/token`` and caches it until expiry.
    All POSTs carry the token in an ``Authorization: Bearer`` header.

    Retries: every request is retried on connection errors / 5xx with
    exponential backoff (max ``retries`` attempts).

    Compliance: every successful POST emits an audit event so the GxP
    trail records what was pushed externally.
    """

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        timeout: float = 10.0,
        retries: int = 3,
        http_client: Any = None,
    ) -> None:
        if httpx is None and http_client is None:  # pragma: no cover
            raise DossplorerError(
                "httpx is required for LiveDossplorerClient. "
                "Install with: pip install httpx"
            )
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._retries = max(1, retries)
        self._token_cache = _OAuth2TokenCache()
        # Allow callers (tests) to inject a fake httpx-shaped client.
        self._http = http_client or (httpx.Client(timeout=timeout) if httpx else None)

    # ---- internals -----------------------------------------------------------

    def _fetch_token(self) -> str:
        if self._http is None:  # pragma: no cover - defensive
            raise DossplorerError("HTTP client is not configured")
        url = f"{self._base_url}/oauth/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        try:
            resp = self._http.post(url, data=payload, timeout=self._timeout)
        except Exception as exc:  # network failure
            raise DossplorerError(f"OAuth2 token request failed: {exc}") from exc
        if resp.status_code != 200:
            raise DossplorerError(
                f"OAuth2 token request returned {resp.status_code}: {getattr(resp, 'text', '')[:200]}"
            )
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise DossplorerError("OAuth2 response did not include access_token")
        self._token_cache.set(token, float(body.get("expires_in", 3600.0)))
        return token

    def _auth_header(self) -> dict[str, str]:
        token = self._token_cache.get() or self._fetch_token()
        return {"Authorization": f"Bearer {token}"}

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None
        backoff = 1.0
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._http.request(
                    method,
                    url,
                    json=json_body,
                    headers=self._auth_header(),
                    timeout=self._timeout,
                )
            except Exception as exc:  # network error → retry
                last_exc = exc
                _log.warning(
                    "dossplorer_http_error",
                    attempt=attempt,
                    error=str(exc),
                    method=method,
                    path=path,
                )
                time.sleep(backoff)
                backoff *= 2.0
                continue

            if 200 <= resp.status_code < 300:
                return resp
            if resp.status_code == 401:
                # Token likely expired between cache lookup and request — clear and retry once.
                self._token_cache.clear()
                if attempt < self._retries:
                    continue
            if resp.status_code >= 500 and attempt < self._retries:
                _log.warning(
                    "dossplorer_5xx_retry",
                    attempt=attempt,
                    status=resp.status_code,
                    method=method,
                    path=path,
                )
                time.sleep(backoff)
                backoff *= 2.0
                continue
            raise DossplorerError(
                f"{method} {url} returned {resp.status_code}: "
                f"{getattr(resp, 'text', '')[:300]}"
            )
        raise DossplorerError(
            f"{method} {url} failed after {self._retries} attempts: {last_exc}"
        )

    # ---- public API ----------------------------------------------------------

    def get_metadata(self, dossier_id: str) -> DossierMetadata:
        resp = self._request_with_retry("GET", f"/v1/dossiers/{dossier_id}")
        try:
            return DossierMetadata.model_validate(resp.json())
        except Exception as exc:
            raise DossplorerError(
                f"unable to parse dossier {dossier_id!r}: {exc}"
            ) from exc

    def push_readiness_score(
        self, dossier_id: str, score: float, *, sequence: str | None = None
    ) -> None:
        if not 0.0 <= score <= 100.0:
            raise DossplorerError(f"score {score} out of range [0,100]")
        body = {"score": score, "sequence": sequence}
        self._request_with_retry(
            "POST", f"/v1/dossiers/{dossier_id}/qc-reports", json_body=body
        )
        audit_event(
            "dossplorer_score_pushed",
            document=dossier_id,
            details={"score": score, "sequence": sequence or ""},
        )

    def push_anomaly_flag(
        self,
        dossier_id: str,
        *,
        document: str,
        severity: AnomalySeverity,
        message: str,
    ) -> None:
        body = {
            "document": document,
            "severity": severity.value,
            "message": message,
        }
        self._request_with_retry(
            "POST", f"/v1/dossiers/{dossier_id}/anomaly-flags", json_body=body
        )
        audit_event(
            "dossplorer_anomaly_pushed",
            document=dossier_id,
            details={"target_doc": document, "severity": severity.value},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


def get_client(*, override_mode: str | None = None) -> DossplorerClient:
    """Return the configured client backend.

    Selection rule (checked in this order):
      1. ``override_mode`` argument
      2. ``HYPERLINK_DOSSPLORER_MODE`` env var
      3. settings.dossplorer_mock_mode → mock or live
    """
    if override_mode:
        mode = override_mode.lower()
    elif "HYPERLINK_DOSSPLORER_MODE" in os.environ:
        mode = os.environ["HYPERLINK_DOSSPLORER_MODE"].lower()
    else:
        mode = "mock" if get_settings().dossplorer_mock_mode else "live"

    if mode == "live":
        settings = get_settings()
        base_url = os.environ.get(
            "HYPERLINK_DOSSPLORER_BASE_URL", settings.dossplorer_base_url
        )
        client_id = os.environ.get("HYPERLINK_DOSSPLORER_CLIENT_ID", "")
        client_secret = os.environ.get(
            "HYPERLINK_DOSSPLORER_CLIENT_SECRET",
            settings.dossplorer_oauth_token,
        )
        if not base_url or not client_id or not client_secret:
            raise DossplorerError(
                "live Dossplorer mode requires HYPERLINK_DOSSPLORER_BASE_URL, "
                "HYPERLINK_DOSSPLORER_CLIENT_ID, and HYPERLINK_DOSSPLORER_CLIENT_SECRET"
            )
        return LiveDossplorerClient(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
        )
    return MockDossplorerClient()
