# GxP & 21 CFR Part 11 Compliance Posture — Phase 3 W10.3

> The engine processes pharmaceutical regulatory dossiers. This document
> records how each Part 11 / GxP requirement is met (or planned to be
> met) by the Phase 2 / Phase 3 deliverables.

This is a **compliance posture statement**, not a formal qualification
package. The full IQ/OQ/PQ qualification effort is deferred to Phase 4
once the POC graduates to a validated production environment.

---

## 1. Scope

The hyperlink-engine modifies regulatory submission documents
(.docx, .pdf, eCTD index.xml). Because those documents are **GxP records**
under 21 CFR Part 11 § 11.10, the engine inherits Part 11 obligations
for the changes it makes.

In scope: every link injection, anomaly flag, HA-rule evaluation, and
file write.

Out of scope (POC): user-account management, training records,
network-time-protocol sync, OS-level access control. These remain the
responsibility of the hosting environment (SunPharma VPC / Celegence
infra).

---

## 2. Part 11 § 11.10 — Controls for closed systems

| Sub-section | Requirement | Engine implementation |
|-------------|-------------|------------------------|
| (a) Validation | "Validation of systems to ensure accuracy, reliability, consistent intended performance…" | Phase 2 acceptance gate (`scripts/phase2_acceptance.py`) and unit-test coverage gate (≥85%) provide ongoing evidence. Full IQ/OQ/PQ in Phase 4. |
| (b) Record copies | "Generation of accurate and complete copies of records…" | The pipeline always writes `<doc>.linked.docx` / `<doc>.linked.pdf` **copies**; source files are never mutated (`tests/unit/test_pipeline_tasks.py::test_inject_links_never_mutates_source`). |
| (c) Protection | "Protection of records to enable accurate and ready retrieval throughout the records retention period…" | `audit.jsonl` is append-only; operators rotate it via OS scheduler (recommended: daily). Output directories are never deleted by the engine. |
| (d) Access | "Limiting system access to authorized individuals…" | OS-level; engine logs `actor` field per event but does not enforce auth. |
| (e) **Audit trail** | "Use of secure, computer-generated, time-stamped audit trails to independently record the date and time of operator entries and actions that create, modify, or delete electronic records…" | Implemented in `audit/trail.py`. See § 4 below. |
| (f) Sequencing | "Use of operational system checks to enforce permitted sequencing of steps and events…" | The Celery + threaded batch runner enforces stage order (ingestion → detection → injection → validation → reporting). Out-of-sequence calls raise `KeyError` from `get_task()`. |
| (g) Authority checks | "Use of authority checks to ensure that only authorized individuals can use the system…" | Phase 4 (OAuth/SAML hookup). POC uses env-based credentials only. |
| (h) Device checks | "Use of device checks to determine, as appropriate, the validity of the source of data input or operational instruction…" | Inputs go through Pydantic validators (`models.py`); malformed payloads raise `ValidationError` before any side effect. |
| (i) Training | "Determination that persons who develop, maintain, or use electronic record/electronic signature systems have the education, training, and experience to perform their assigned tasks…" | Operator responsibility — outside engine scope. |
| (j) Written policies | "Establishment of, and adherence to, written policies that hold individuals accountable…" | Customer SOP scope (SunPharma). |
| (k) Documentation controls | "Use of appropriate controls over systems documentation including… revision and change control procedures to maintain an audit trail…" | This repository is git-tracked. Every code change has a commit. ADRs (`docs/adr/`) record material design decisions. |

---

## 3. Part 11 § 11.50 — Signature manifestations

Not yet implemented. Every audit-trail line carries a `signature_id: null`
placeholder; Phase 4 wires this to the live SunPharma e-signature
system. The audit-record schema is designed to be back-compatible — when
e-sig is live, existing records remain valid and new ones include the
signature reference.

---

## 4. Audit trail — `audit/trail.py`

### Properties
* **Append-only.** Writer opens with `"a"` mode every emit; no truncation.
* **Thread-safe.** `threading.Lock` serializes writes from concurrent
  workers in the threaded batch runner.
* **Tamper-evident (Phase 4).** A hash-chain field will link each event
  to its predecessor; for the POC the OS file ACL is the integrity
  mechanism.
* **UTC, ISO-8601, second precision** timestamps per § 11.10(e).
* **Self-contained JSON-Lines** so the file is readable with stock tools
  (`jq`, `grep`) and forwardable to Splunk / Elastic without parsing.

### What is recorded
Every event with a side effect:

| Action                  | Trigger                                   |
|-------------------------|-------------------------------------------|
| `document_ingested`     | DocX/PDF/eCTD loaded into the pipeline   |
| `link_injected`         | A hyperlink was written to a document    |
| `link_validation_run`   | Existence/target checks ran               |
| `anomaly_detected`      | Anomaly detector emitted a record         |
| `ha_rule_violation`     | HA rule engine emitted a violation        |
| `report_written`        | CSV / XLSX report was persisted           |
| `readiness_scored`      | Readiness score computed                  |

Each line carries the actor, action, target document, before/after
sha256 hashes (when relevant), and a `details` dict for action-specific
context.

### Storage / retention
Default location: `<project_root>/audit.jsonl` (configurable via
`HYPERLINK_AUDIT_LOG_PATH`). Recommended rotation: 1 file/day under
`audit/YYYY/MM/audit-YYYY-MM-DD.jsonl`. Retention: per the SunPharma
records-management SOP (typically ≥5 years post-submission).

---

## 5. Data integrity (ALCOA+)

| Principle      | Engine implementation |
|----------------|------------------------|
| **A**ttributable | Every audit line carries `actor` (system or user). |
| **L**egible | JSON-Lines + structured logging — human and machine readable. |
| **C**ontemporaneous | Audit timestamp is set at emit time, not at batch-flush. |
| **O**riginal | Sources are never mutated; outputs are explicit copies. |
| **A**ccurate | Pydantic validation on every model boundary; coverage gate ≥85%. |
| **+ Complete** | Every link injection emits an audit record; gaps would be visible in the trail. |
| **+ Consistent** | Pipeline stages run in fixed order via `PIPELINE_STAGES`. |
| **+ Enduring** | Append-only file; OS-level retention. |
| **+ Available** | Plain JSONL; no proprietary format. |

---

## 6. Validation strategy

### Continuous evidence
* `pytest` unit + integration suite (≥85% coverage gate).
* `scripts/phase1_acceptance.py` and `scripts/phase2_acceptance.py`
  acceptance gates produce dated `ACCEPTANCE_REPORT.txt` for each tag.
* `scripts/benchmark_throughput.py` evidence for performance claims.

### IQ (Installation Qualification) — Phase 4
* Confirm Python 3.11+, Poetry, OS, and dependency versions match the
  approved baseline.
* Confirm directory layout, file permissions, audit-log path writable.

### OQ (Operational Qualification) — Phase 4
* Execute the full unit + integration test suite.
* Execute Phase 1 + Phase 2 + Phase 3 acceptance scripts.
* Confirm audit-trail records appear with correct schema for each
  action category.

### PQ (Performance Qualification) — Phase 4
* Process the gold-standard NDA dossier through the live pipeline.
* Compare engine output to the manually-linked baseline (publishing SME
  signs off on a sample of 100 links).
* Confirm broken-link rate < 0.5%, readiness score ≥ 90.

---

## 7. Change-control

* Every code change is a git commit with a clear message.
* Material design decisions live in `docs/adr/`.
* New audit-event types or schema bumps are recorded as ADRs.
* No `--no-verify` / `--no-gpg-sign` commits — pre-commit hooks
  (ruff + black + mypy + pytest) gate every change.

---

## 8. Known gaps (Phase 4 backlog)

1. Live electronic-signature wiring (currently `signature_id: null`).
2. Hash-chain field on audit lines (currently relies on OS file integrity).
3. Real PDF/A verifier (currently the `is_pdf_a` flag is a heuristic).
4. Live SAML/OAuth authentication for the dashboard.
5. Full IQ/OQ/PQ qualification package.
6. Per-user training records integration.
