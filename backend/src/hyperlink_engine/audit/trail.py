"""W10.3 — GxP / 21 CFR Part 11 audit-trail writer.

Append-only ``audit.jsonl`` ledger.  Every link-injection, anomaly-flag,
HA-violation, and pipeline-stage event passes through here so we can
prove "what changed, when, by whom" during an FDA audit.

Design rules
------------

* **Append-only.**  The writer opens the file with ``"a"`` mode every time;
  on-disk rotation is the operator's responsibility (a daily-rotated logger
  via logrotate / Windows Task Scheduler is the recommended pattern).
* **JSON-Lines.**  One self-contained JSON object per line so the file is
  searchable with stock tools (``jq``, ``grep``, Splunk forwarders).
* **Thread-safe.**  Writes are protected by an internal ``threading.Lock``
  so the threaded batch runner cannot interleave half-lines.
* **Timestamps are UTC, ISO-8601, second precision.**  21 CFR Part 11 §
  11.10(e) requires this for the audit trail.
* **Electronic-signature placeholder.**  Every event carries an optional
  ``signature_id`` field; in POC we leave it ``None``.  Phase 4 wires in
  the SunPharma e-sig system.

Schema (per line)
-----------------

.. code-block:: json

    {
      "timestamp": "2026-05-27T06:30:12Z",
      "actor": "system:hyperlink-engine",
      "action": "link_injected",
      "document": "m2/2-5-clin-overview.docx",
      "details": { "links_added": 12, "doc_hash_after": "<sha256>" },
      "doc_hash_before": "<sha256>",
      "doc_hash_after": "<sha256>",
      "signature_id": null
    }
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.models import AuditEvent

_log = get_logger("audit.trail")


# ─────────────────────────────────────────────────────────────────────────────
# AuditTrail — singleton writer
# ─────────────────────────────────────────────────────────────────────────────


class AuditTrail:
    """Append-only audit-trail writer."""

    def __init__(self, audit_log_path: Path) -> None:
        self.path = Path(audit_log_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # The default factory does not open or touch the file — the first
    # write creates it.

    def emit(self, event: AuditEvent) -> None:
        """Persist a single :class:`models.AuditEvent` as one JSONL line."""
        line = json.dumps(self._serialize(event), separators=(",", ":"), default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        _log.debug("audit_event_written", action=event.action, document=event.document)

    def emit_event(
        self,
        *,
        actor: str,
        action: str,
        document: str | None = None,
        doc_hash_before: str | None = None,
        doc_hash_after: str | None = None,
        links_added: int = 0,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Convenience wrapper that builds + emits an :class:`AuditEvent`.

        The event uses an explicit UTC timestamp (overrides the model's
        default factory which still uses :func:`datetime.utcnow`).
        """
        clean_details = {k: str(v) for k, v in (details or {}).items()}
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc),
            actor=actor,
            action=action,
            document=document,
            doc_hash_before=doc_hash_before,
            doc_hash_after=doc_hash_after,
            links_added=links_added,
            details=clean_details,
        )
        self.emit(event)
        return event

    # Internal --------------------------------------------------------------

    def _serialize(self, event: AuditEvent) -> dict[str, Any]:
        ts = event.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        iso = ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "timestamp": iso,
            "actor": event.actor,
            "action": event.action,
            "document": event.document,
            "doc_hash_before": event.doc_hash_before,
            "doc_hash_after": event.doc_hash_after,
            "links_added": event.links_added,
            "details": event.details,
            "signature_id": None,  # Phase 4: live e-sig integration
        }

    # Read-side helpers -----------------------------------------------------

    def read_all(self) -> list[dict[str, Any]]:
        """Return every audit record currently on disk (for QC / tests)."""
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    _log.warning("audit_trail_malformed_line", line=line[:80])
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────


_singleton_lock = threading.Lock()
_singleton: AuditTrail | None = None


def get_audit_trail(path: Path | None = None) -> AuditTrail:
    """Return the process-wide :class:`AuditTrail` instance.

    Pass ``path`` to override the configured audit-log location (used by
    tests).  Once created the singleton is sticky; call
    :func:`reset_audit_trail` to point it elsewhere.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None or (path is not None and Path(path) != _singleton.path):
            target = Path(path) if path else _resolve_default_audit_path()
            _singleton = AuditTrail(target)
        return _singleton


def reset_audit_trail() -> None:
    """Drop the singleton — the next :func:`get_audit_trail` call rebuilds it."""
    global _singleton
    with _singleton_lock:
        _singleton = None


def _resolve_default_audit_path() -> Path:
    """Default audit-log path from settings, resolved to absolute."""
    settings = get_settings()
    p = Path(settings.audit_log_path)
    if not p.is_absolute():
        p = Path(settings.project_root) / p
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Convenience module-level helper
# ─────────────────────────────────────────────────────────────────────────────


def audit_event(
    action: str,
    *,
    actor: str = "system:hyperlink-engine",
    document: str | None = None,
    doc_hash_before: str | None = None,
    doc_hash_after: str | None = None,
    links_added: int = 0,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Module-level shortcut that emits via the singleton trail.

    Use this in pipeline code where injecting an ``AuditTrail`` instance
    would be noise:

        >>> audit_event("link_injected", document="m2/2.5.docx", links_added=12)
    """
    trail = get_audit_trail()
    return trail.emit_event(
        actor=actor,
        action=action,
        document=document,
        doc_hash_before=doc_hash_before,
        doc_hash_after=doc_hash_after,
        links_added=links_added,
        details=details,
    )
