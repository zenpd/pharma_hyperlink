# Architecture — Hyperlink Engine

> **Status:** v1, Week 1 of POC
> **Owner:** Engineering Lead
> **Companion docs:** [pattern-catalog.md](pattern-catalog.md), [adr/](adr/)

---

## 1. System Overview

A six-layer batch pipeline that consumes regulatory dossier documents (.docx, PDF, eCTD XML), detects reference patterns, injects hyperlinks, validates link integrity, and exposes results through a QC dashboard.

```
Input → [Ingestion] → [Parsing] → [Detection] → [Injection] → [Validation] → [Dashboard]
                                       ↑                            ↓
                                   [eCTD Graph] ←──────────── [Audit Log]
```

Each layer is implemented as a Python package under `backend/src/hyperlink_engine/`. Stage-to-stage data flows through Pydantic models (typed contracts, validated at runtime). The pipeline orchestrator (Celery, Layer 6.5) schedules per-document tasks; the eCTD graph (graph/) is a cross-cutting service accessed by detection, injection, and validation.

---

## 2. Layer Responsibilities

### Layer 1 — Ingestion (`backend/src/hyperlink_engine/core/ingestion/`)

| Module | Responsibility | External lib |
|---|---|---|
| `docx_loader.py` | Read .docx; never mutate; return `DocxDocument` model | python-docx |
| `pdf_loader.py` | Read PDF; extract pages + bookmarks + existing links | PyMuPDF, pdfplumber |
| `ectd_loader.py` | Parse `index.xml`; emit `BackboneSnapshot` | lxml |
| `dossplorer_client.py` | Pull dossier metadata; mock in Phase 1, live in Phase 3 | httpx |

**Contract:** every loader returns a typed Pydantic model with provenance (source path, hash, ingest timestamp). Loaders are **stateless** and **side-effect-free** (except local-only metadata caching).

### Layer 2 — Parsing (`backend/src/hyperlink_engine/core/parsing/`)

| Module | Responsibility |
|---|---|
| `docx_parser.py` | Walk paragraphs + runs + tables; capture text + styling (font, color RGB, size) + location anchors |
| `pdf_parser.py` | Build page → block → span → token tree; capture text color + bbox |
| `xml_parser.py` | Walk eCTD XML; build leaf manifest |

**Contract:** parsers consume Layer-1 outputs and emit `ParsedDocument` with a location-addressable token stream. Every token carries enough context to inject a hyperlink at exactly that position later (paragraph index, run index, character offset).

### Layer 3 — Detection (`backend/src/hyperlink_engine/core/detection/`)

| Module | Responsibility |
|---|---|
| `regex_patterns.py` | `default_registry()` wires **17 active patterns / 9 reference types** (a subset of the design families catalogued in `docs/pattern-catalog.md`) — incl. document-type **`DOC_REF`** ("the protocol"/"the SAP"/"the CSR") that links real Protocol↔SAP↔CSR PDF pairs |
| `ner_model.py` | Custom spaCy NER (Week 3) — entity labels per pattern catalog |
| `llm_disambiguator.py` | Local Llama 3.1 via Ollama; only invoked on low-confidence or conflict |
| `entity_extractor.py` | Merge regex + NER outputs; apply conflict resolution (catalog §8) |

**Pipeline:** `regex → NER → conflict resolution → LLM (if needed) → List[Reference]`. Each `Reference` is location-anchored (so injection knows where to put the link) and carries candidate targets with confidence scores.

**Constraint:** LLM is **local-only** (Ollama / vLLM). No external API calls — required for 21 CFR Part 11 compliance.

### Layer 4 — Injection (`backend/src/hyperlink_engine/core/injection/`)

| Module | Responsibility |
|---|---|
| `docx_linker.py` | Build `w:hyperlink` XML; inject at exact run location; preserve styling |
| `pdf_linker.py` | Create PDF link annotations + named destinations; clickable rect sized to the matched phrase (parity with docx run-level links) |
| `ectd_xref.py` | Inject backbone XML cross-references (Phase 2+) |
| `style_preserver.py` | Whitelist Dosscriber-specific styles; diff-check post-injection |

**Invariant:** never mutate the input document. Always emit `_linked.docx` / `_linked.pdf` copies. Original file hash captured in audit log so QA can verify zero-mutation.

### Layer 5 — Validation (`backend/src/hyperlink_engine/core/validation/`)

| Module | Responsibility |
|---|---|
| `existence_checker.py` | Verify every link resolves (file + anchor + named destination) |
| `target_validator.py` | Semantic check: link text ↔ target heading (sentence-transformer similarity) |
| `viewer_compat.py` | Headless rendering via Adobe SDK / Playwright; per-viewer link test |
| `anomaly_detector.py` | Blue-text-no-link, orphaned, circular, deprecated Study IDs, suspicious patterns |

**Output:** `ValidationReport` with one record per link + one anomaly list per document. Feeds Layer 6 directly.

### Layer 6 — Dashboard & Reporting (`backend/src/hyperlink_engine/dashboard/`, `reporting/`)

| Module | Responsibility |
|---|---|
| `api/app.py` | FastAPI backend; pipeline, review, compliance, dossier and export endpoints |
| `api/middleware/` | Auth core: SuperTokens init, `auth_guard`, `Principal`, classified-access gate, Security toggle (PLAN SEVEN) |
| `../frontend/` (React + Vite, :5174) | The live dashboard SPA |
| `dashboard/react_frontend/` | Paused earlier React scaffold (kept for reference) |
| `reporting/readiness_score.py` | Configurable weighted scoring |
| `reporting/csv_exporter.py` | One-row-per-link export |
| `reporting/xlsx_exporter.py` | Conditional-formatted bulk export + pivot tab |

**Run Compare UI (React dashboard).** The before/after compare widget is a
**3-pane** layout — **BEFORE | AFTER | Linked-Documents viewer list**. Word **and
PDF** tables render as **real HTML grids** in both panels and in the focused
Reference View: the preview endpoints emit structured blocks via
`api/app.py::_read_doc_blocks` — `_read_docx_blocks` for `.docx` and
`_read_pdf_blocks` for `.pdf` (ruled tables via PyMuPDF's *lines* strategy) — as
`{type:"paragraph",text}` / `{type:"table",rows,text}` instead of flattened
`" | "` text. The viewer list and link routing are format-agnostic
(`_linked.(docx|pdf)`), so PDF runs populate the Linked-Documents pane too. Each link carries an authoritative **`link_kind`** (set by
`orchestration/nodes.py::node_validate`: `external_url` / `cross_doc` /
`internal_bookmark` / `cross_module`); a single shared frontend helper
(`externalUrl`/`isExternalLink`) guarantees **external web links always open in a
new tab** and never route into the Reference View, while cross-doc links open the
Reference View and internal refs scroll-and-flash in place.

---

## 3. Cross-Cutting Services

### Graph Service (`backend/src/hyperlink_engine/core/graph/`)

- **Phase 1:** NetworkX in-memory; suitable for ≤100 documents
- **Phase 2+:** Neo4j (persistent); query via Cypher for "find all docs referencing Study X"
- Nodes = leaves; edges = explicit refs + structural parent-child
- Consumers: detection (resolve targets), injection (cross-module routing), validation (cycle detection)

### Configuration (`backend/src/hyperlink_engine/config/`)

- `settings.py` — Pydantic Settings; reads env (`OLLAMA_HOST`, `NEO4J_URI`, `REDIS_URL`, log level)
- `ha_rules.yaml` — region-specific HA constraints (FDA, EMA, PMDA, Health Canada, ANVISA)

### Logging & Audit

- `structlog` JSON output; every link injection logged with `(timestamp, user, doc_hash_before, doc_hash_after, links_added)`
- Audit log appended to `audit.jsonl` per dossier — immutable, append-only
- Phase 3: ship to Splunk / Elastic for compliance retention

### Auth & Classified Access (`backend/src/hyperlink_engine/api/middleware/`) — PLAN SEVEN

- **Identity:** self-hosted **SuperTokens** (core container :3567 + its own Postgres);
  email+password login, httpOnly cookie sessions, `admin`/`user` roles. The SDK's ASGI
  middleware serves `/api/auth/*`; everything else passes through the global
  `auth_guard` dependency (gate ON + no session → 401).
- **Classification gate:** every run carries `classification` (`classified`/`unclassified`,
  deny-by-default `classified`) + `owner`, persisted on the Neo4j `Run` node. Non-cleared
  users get classified runs filtered from lists and **403** from all 22 run-scoped
  endpoints (`require_classified_access`).
- **Security toggle:** `GET/POST /api/security/mode` — an admin can flip the whole gate
  at runtime; the change is audit-logged and persisted across restarts.
- Auth is **OFF by default** (`HYPERLINK_AUTH_ENABLED=false`); the test suite never needs
  a live core. Full design + verification: `docs/auth-supertokens.md`.

### Pipeline Orchestration (`backend/src/hyperlink_engine/workers/`)

- Celery + Redis (broker + result backend); RabbitMQ as production alternative
- Queues: `ingestion`, `detection`, `injection`, `validation`, `reporting`
- Each task idempotent; exponential-backoff retry; failures pushed to dead-letter queue + dashboard

---

## 4. Data Flow (End-to-End)

```
                ┌──────────────────────────────────────────────┐
                │ User uploads dossier batch via dashboard or  │
                │ CLI: `batch_runner --input <dir>`            │
                └──────────────────────┬───────────────────────┘
                                       │
                                       ▼
              ┌─────────────────────────────────────────────┐
              │ Pipeline orchestrator splits into per-doc   │
              │ tasks; enqueues to Celery `ingestion` queue │
              └─────────────────────────┬───────────────────┘
                                        │
                ┌───────────────────────┴────────────────────────┐
                ▼                                                ▼
        ┌──────────────┐                                ┌──────────────┐
        │ docx_loader  │                                │ pdf_loader   │
        │ +docx_parser │                                │ +pdf_parser  │
        └──────┬───────┘                                └──────┬───────┘
               │                                               │
               └────────────────┬──────────────────────────────┘
                                ▼
                  ┌──────────────────────────┐
                  │ entity_extractor         │
                  │ (regex → NER → LLM)      │ ← graph_service (resolve targets)
                  └────────────┬─────────────┘
                               ▼
                  ┌──────────────────────────┐
                  │ docx_linker / pdf_linker │
                  │ (inject hyperlinks)      │
                  └────────────┬─────────────┘
                               ▼
                  ┌──────────────────────────┐
                  │ existence_checker        │
                  │ target_validator         │
                  │ anomaly_detector         │ ← graph_service (cycle detection)
                  └────────────┬─────────────┘
                               ▼
                  ┌──────────────────────────┐
                  │ readiness_score          │
                  │ csv/xlsx_exporter        │
                  └────────────┬─────────────┘
                               ▼
                  ┌──────────────────────────┐
                  │ Dashboard / Dossplorer   │
                  │ (results + drill-down)   │
                  └──────────────────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │ audit.jsonl (append-only)│
                  └──────────────────────────┘
```

---

## 5. Module Dependency Graph

```
config  ←──────────────────┐
   ↑                       │
   │                       │
ingestion ──→ parsing ──→ detection ←──→ graph
                              │              ↑
                              ▼              │
                          injection ─────────┘
                              │
                              ▼
                          validation
                              │
                              ▼
                          reporting ──→ dashboard
                              │
                              ▼
                          pipeline (orchestrates all)
```

**Rule:** lower layers must not import from higher layers. `injection` may not import `validation`. `parsing` may not import `detection`. Enforced via ruff + import-linter (Phase 2).

---

## 6. Key Design Decisions

ADRs in `docs/adr/`:

| ID | Title | Phase |
|---|---|---|
| 0001 | Use python-docx hyperlink XML injection (not docx2pdf round-trip) | 1 |
| 0002 | Dossplorer integration contract (POST /qc-reports, /anomaly-flags) | 1 (design); 3 (implement) |
| 0003 | NetworkX → Neo4j graph migration trigger | 2 |
| 0004 | Local-only LLM (Ollama/vLLM); no external APIs | 1 |
| 0005 | Audit log: append-only JSONL, hash chain in Phase 3 | 1 |
| 0006 | Pydantic models as inter-layer contracts | 1 |

---

## 7. Performance Targets

| Metric | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Throughput (docs/hour) | 5 (1 module) | 125+ (500 docs / 4h) | 500+ |
| Detection accuracy (F1) | ≥0.90 | ≥0.92 | ≥0.95 |
| Cold start (idle → first task) | <30 sec | <15 sec | <5 sec |
| Dashboard load (NDA dossier) | n/a | <10 sec | <5 sec |

---

## 8. Failure Modes & Recovery

| Failure | Behavior |
|---|---|
| Malformed input .docx | Log warning; skip document; surface in dashboard "Unprocessed" tab |
| LLM timeout / down | Fall back to highest-confidence regex/NER result; flag reference for human review |
| Neo4j unavailable | Fall back to NetworkX in-memory graph (loaded from last snapshot) |
| Celery worker crash | Task retried with exponential backoff (3 attempts); then dead-letter queue |
| Style mutation detected | Reject linked output; emit blocker-severity anomaly; do not write file |
| Audit log write failure | Halt pipeline (compliance-critical); page on-call |

---

## 9. Security & Compliance Notes

- All processing on-prem (POC machine → SunPharma VPC by Phase 3)
- Zero external API calls for any document content (LLM, embeddings, validation all local)
- Document hashes stored in audit log; original files never modified in-place
- Role-based access (Phase 3): publisher / reviewer / approver / admin
- 21 CFR Part 11: electronic signature hooks in Layer 6 (Phase 3+)
- GxP IQ/OQ/PQ skeletons in `docs/gxp/` (Phase 3)

See [adr/0004-local-llm-only.md](adr/0004-local-llm-only.md) and the parent plan §8.1 for full compliance posture.

---

## 10. What's NOT in this Architecture (Out of Scope for POC)

- Dosscriber **plugin** (write-time linking) — Phase 4
- Live FDA ESG / EMA ESPRE submission gateway integration — Phase 4
- Auto-remediation of anomalies (engine flags + suggests; humans fix) — Phase 4
- Multi-tenant deployment — Phase 4
- Mobile dashboard — Phase 4+

See parent plan §14 for full out-of-scope list.
