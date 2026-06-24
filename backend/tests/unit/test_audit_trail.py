"""Unit tests for audit/trail.py (W10.3)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hyperlink_engine.audit.trail import (
    AuditTrail,
    audit_event,
    get_audit_trail,
    reset_audit_trail,
)
from hyperlink_engine.models import AuditEvent


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_audit_trail()
    yield
    reset_audit_trail()


# ── AuditTrail.emit / emit_event ─────────────────────────────────────────────


def test_emit_writes_one_jsonl_line(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.emit_event(actor="tester", action="link_injected", document="x.docx")
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["actor"] == "tester"
    assert record["action"] == "link_injected"
    assert record["document"] == "x.docx"
    assert record["signature_id"] is None  # POC placeholder


def test_emit_appends_subsequent_records(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    for i in range(3):
        trail.emit_event(actor="tester", action=f"event-{i}")
    records = trail.read_all()
    assert len(records) == 3
    assert [r["action"] for r in records] == ["event-0", "event-1", "event-2"]


def test_emit_uses_iso8601_utc_timestamp(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.emit_event(actor="t", action="x")
    record = trail.read_all()[0]
    ts = record["timestamp"]
    # Format: YYYY-MM-DDTHH:MM:SSZ
    assert ts.endswith("Z")
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
    assert parsed.tzinfo is None  # strptime returns naive — but format implies UTC


def test_emit_carries_doc_hashes(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.emit_event(
        actor="t",
        action="link_injected",
        document="x.docx",
        doc_hash_before="a" * 64,
        doc_hash_after="b" * 64,
        links_added=12,
    )
    record = trail.read_all()[0]
    assert record["doc_hash_before"] == "a" * 64
    assert record["doc_hash_after"] == "b" * 64
    assert record["links_added"] == 12


def test_emit_details_dict_serialized(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    trail.emit_event(actor="t", action="x", details={"key": "value", "n": 5})
    record = trail.read_all()[0]
    assert record["details"]["key"] == "value"
    assert record["details"]["n"] == "5"  # forced to str for JSONL safety


def test_emit_direct_audit_event(tmp_path: Path) -> None:
    """Emitting via the lower-level emit(event) path also works."""
    trail = AuditTrail(tmp_path / "audit.jsonl")
    event = AuditEvent(
        timestamp=datetime.now(timezone.utc),
        actor="t",
        action="document_ingested",
        document="m2.docx",
        links_added=0,
    )
    trail.emit(event)
    record = trail.read_all()[0]
    assert record["action"] == "document_ingested"


# ── Thread safety ────────────────────────────────────────────────────────────


def test_concurrent_emits_produce_complete_lines(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")

    def _writer(i: int) -> None:
        for j in range(20):
            trail.emit_event(actor=f"w{i}", action=f"event-{i}-{j}")

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = trail.read_all()
    assert len(records) == 8 * 20
    # Every line must parse — no half-written / interleaved JSON
    actions = sorted(r["action"] for r in records)
    assert len(actions) == len(set(actions))


# ── read_all on missing file ─────────────────────────────────────────────────


def test_read_all_missing_file_returns_empty(tmp_path: Path) -> None:
    trail = AuditTrail(tmp_path / "audit.jsonl")
    assert trail.read_all() == []


def test_read_all_skips_malformed_line(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        '{"action": "ok"}\nthis is not json\n{"action": "ok2"}\n',
        encoding="utf-8",
    )
    trail = AuditTrail(audit_path)
    records = trail.read_all()
    assert [r["action"] for r in records] == ["ok", "ok2"]


# ── Singleton accessor ───────────────────────────────────────────────────────


def test_get_audit_trail_returns_singleton(tmp_path: Path) -> None:
    a = get_audit_trail(tmp_path / "audit.jsonl")
    b = get_audit_trail()
    assert a is b


def test_get_audit_trail_path_override_rebuilds_singleton(tmp_path: Path) -> None:
    a = get_audit_trail(tmp_path / "first.jsonl")
    b = get_audit_trail(tmp_path / "second.jsonl")
    assert a is not b
    assert b.path == tmp_path / "second.jsonl"


def test_reset_audit_trail_drops_singleton(tmp_path: Path) -> None:
    a = get_audit_trail(tmp_path / "audit.jsonl")
    reset_audit_trail()
    b = get_audit_trail(tmp_path / "audit.jsonl")
    assert a is not b


# ── Module-level audit_event helper ──────────────────────────────────────────


def test_module_level_audit_event(tmp_path: Path) -> None:
    get_audit_trail(tmp_path / "audit.jsonl")  # pin the singleton path
    audit_event("link_injected", document="x.docx", links_added=5)
    records = get_audit_trail().read_all()
    assert len(records) == 1
    assert records[0]["action"] == "link_injected"
