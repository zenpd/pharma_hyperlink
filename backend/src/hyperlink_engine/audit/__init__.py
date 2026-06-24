"""Cross-cutting audit-trail subsystem (W10.3).

Exposes the :class:`AuditTrail` writer and helpers for emitting append-only
``audit.jsonl`` records that satisfy 21 CFR Part 11 § 11.10(e) (computer-
generated time-stamped audit trail) for every link injection or anomaly
flagging step the engine performs.
"""

from hyperlink_engine.audit.trail import (
    AuditTrail,
    audit_event,
    get_audit_trail,
    reset_audit_trail,
)

__all__ = [
    "AuditTrail",
    "audit_event",
    "get_audit_trail",
    "reset_audit_trail",
]
