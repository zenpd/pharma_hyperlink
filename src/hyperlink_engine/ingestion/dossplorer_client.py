"""Layer 1 — Dossplorer API client (mock in Phase 1).

Phase 1 has no live Dossplorer connection — Celegence will wire authentication
and endpoint access during Phase 3 (Week 11). To unblock everything upstream
right now, this module exposes the **same interface** the live client will
satisfy, but backs it with a local JSON fixture.

The real API contract is documented in docs/adr/0002-dossplorer-integration.md
and gets implemented in `LiveDossplorerClient` (placeholder below) without
touching downstream callers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from hyperlink_engine.config.logging_setup import get_logger
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

    def push_readiness_score(self, dossier_id: str, score: float, *, sequence: str | None = None) -> None: ...

    def push_anomaly_flag(
        self,
        dossier_id: str,
        *,
        document: str,
        severity: AnomalySeverity,
        message: str,
    ) -> None: ...


class MockDossplorerClient:
    """A file-backed Dossplorer stand-in.

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
            raise DossplorerError(f"fixture {self._fixture_path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, list):
            raise DossplorerError(f"fixture {self._fixture_path} must be a JSON list of dossiers")
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

    def push_readiness_score(self, dossier_id: str, score: float, *, sequence: str | None = None) -> None:
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


class LiveDossplorerClient:  # pragma: no cover — wired in Phase 3 (Week 11)
    """Placeholder for the live HTTP client implemented per ADR-0002.

    Constructor will read base URL + token from settings; methods will hit:
        GET  /v1/dossiers/{id}
        POST /v1/dossiers/{id}/qc-reports
        POST /v1/dossiers/{id}/anomaly-flags
    """

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        raise NotImplementedError("LiveDossplorerClient is implemented in Phase 3 (Week 11)")


def get_client() -> DossplorerClient:
    """Factory: return whichever client backend is currently active.

    Selection rule:
      * if ``HYPERLINK_DOSSPLORER_MODE`` env var is unset or 'mock' → mock client
      * if it is 'live' → live client (currently raises NotImplementedError)
    """
    mode = (os.environ.get("HYPERLINK_DOSSPLORER_MODE") or "mock").lower()
    if mode == "live":
        base_url = os.environ.get("HYPERLINK_DOSSPLORER_BASE_URL", "")
        token = os.environ.get("HYPERLINK_DOSSPLORER_TOKEN", "")
        if not base_url or not token:
            raise DossplorerError(
                "live Dossplorer mode requires HYPERLINK_DOSSPLORER_BASE_URL and "
                "HYPERLINK_DOSSPLORER_TOKEN environment variables"
            )
        return LiveDossplorerClient(base_url=base_url, token=token)
    return MockDossplorerClient()
