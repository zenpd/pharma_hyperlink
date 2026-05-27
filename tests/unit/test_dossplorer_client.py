"""Unit tests for ingestion/dossplorer_client.py."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hyperlink_engine.ingestion.dossplorer_client import (
    DossplorerError,
    LiveDossplorerClient,
    MockDossplorerClient,
    get_client,
)
from hyperlink_engine.models import AnomalySeverity


@pytest.fixture
def fixture_path(tmp_path: Path) -> Path:
    path = tmp_path / "dossiers.json"
    path.write_text(
        json.dumps(
            [
                {
                    "dossier_id": "DOS-TEST-001",
                    "sponsor": "TestPharma",
                    "submission_type": "NDA",
                    "region": "US",
                    "sequence_number": "0001",
                    "study_ids": ["TST-2024-001"],
                    "status": "draft",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_mock_loads_fixture(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    meta = client.get_metadata("DOS-TEST-001")
    assert meta.sponsor == "TestPharma"
    assert meta.submission_type == "NDA"


def test_mock_unknown_dossier_raises(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    with pytest.raises(DossplorerError, match="not found"):
        client.get_metadata("DOS-NOPE")


def test_mock_push_score_buffers(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    client.push_readiness_score("DOS-TEST-001", 87.5, sequence="0001")
    assert client.pushed_scores == [
        {"dossier_id": "DOS-TEST-001", "score": 87.5, "sequence": "0001"}
    ]


def test_mock_push_score_rejects_out_of_range(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    with pytest.raises(DossplorerError, match="out of range"):
        client.push_readiness_score("DOS-TEST-001", 200.0)


def test_mock_push_score_rejects_unknown(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    with pytest.raises(DossplorerError, match="unknown dossier"):
        client.push_readiness_score("DOS-UNKNOWN", 50.0)


def test_mock_push_anomaly_buffers(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    client.push_anomaly_flag(
        "DOS-TEST-001",
        document="m2/sample.docx",
        severity=AnomalySeverity.WARNING,
        message="Blue text without link",
    )
    assert len(client.pushed_anomalies) == 1
    assert client.pushed_anomalies[0]["severity"] == "warning"


def test_default_factory_returns_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_MODE", raising=False)
    client = get_client()
    assert isinstance(client, MockDossplorerClient)


def test_live_mode_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_MODE", "live")
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_BASE_URL", raising=False)
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_CLIENT_ID", raising=False)
    monkeypatch.delenv("HYPERLINK_DOSSPLORER_CLIENT_SECRET", raising=False)
    with pytest.raises(DossplorerError, match="requires"):
        get_client()


def test_live_client_constructs_when_env_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live mode now constructs a LiveDossplorerClient (W11.1)."""
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_MODE", "live")
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_BASE_URL", "https://example.local")
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_CLIENT_ID", "cid")
    monkeypatch.setenv("HYPERLINK_DOSSPLORER_CLIENT_SECRET", "csec")
    client = get_client()
    assert isinstance(client, LiveDossplorerClient)


def test_default_fixture_loads() -> None:
    """The shipped JSON fixture must be valid and contain SunPharma dossiers."""
    client = MockDossplorerClient()
    ids = client.list_dossier_ids()
    assert ids, "shipped fixture is empty — config/fixtures/dossplorer_dossiers.json"
    for did in ids:
        meta = client.get_metadata(did)
        assert meta.sponsor


def test_invalid_json_fixture_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(DossplorerError, match="not valid JSON"):
        MockDossplorerClient(fixture_path=bad)


def test_non_list_fixture_raises(tmp_path: Path) -> None:
    bad = tmp_path / "wrong_shape.json"
    bad.write_text('{"dossiers": []}', encoding="utf-8")
    with pytest.raises(DossplorerError, match="JSON list"):
        MockDossplorerClient(fixture_path=bad)


def test_invalid_entry_in_fixture_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad_entry.json"
    bad.write_text('[{"dossier_id": "X"}]', encoding="utf-8")
    with pytest.raises(DossplorerError, match="invalid dossier entry"):
        MockDossplorerClient(fixture_path=bad)


def test_missing_fixture_falls_back_to_empty(tmp_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=tmp_path / "missing.json")
    assert client.list_dossier_ids() == []


def test_push_anomaly_rejects_unknown_dossier(fixture_path: Path) -> None:
    client = MockDossplorerClient(fixture_path=fixture_path)
    with pytest.raises(DossplorerError, match="unknown dossier"):
        client.push_anomaly_flag(
            "DOS-MISSING",
            document="m1/x.docx",
            severity=AnomalySeverity.INFO,
            message="ignored",
        )


def test_live_client_direct_init_succeeds() -> None:
    """Direct construction now works (W11.1)."""
    client = LiveDossplorerClient(
        base_url="https://example.local/",
        client_id="cid",
        client_secret="csec",
    )
    assert client is not None
