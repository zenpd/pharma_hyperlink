# Hyperlink Engine — Monorepo

> AI-Powered Hyperlink Automation & Validation Engine for regulatory dossier submissions.
> Detects reference patterns across thousands of CTD documents, injects hyperlinks into Word and PDF
> renditions, validates link integrity, and reports submission readiness — all on-prem, GxP-aligned.

This repository is an **enterprise monorepo** with independently-deployable units plus shared infra and docs:

```
hyperlink-engine/
├── backend/     # Python engine + FastAPI API + Celery workers + LangGraph orchestration
├── frontend/    # React + Vite dashboard SPA
├── infra/       # Docker Compose + Neo4j / Redis / nginx configs
├── docs/        # architecture, pattern catalog, ADRs, run guides
├── .github/     # CI workflows (backend-ci, frontend-ci)
└── .venv/       # shared Python virtualenv (gitignored)
```

- **Backend** → `backend/` — Python engine + FastAPI API + Celery workers + LangGraph orchestration (layout in [Repository layout](#repository-layout), commands in [Developer workflow](#developer-workflow-top-level-makefile))
- **Frontend** → `frontend/` (Vite dev server on :5174)
- **Infra** → `infra/docker/docker-compose.yml`

---

## Status

**Phases 1–3 functionally complete.** The engine runs end-to-end through a real
LangGraph state machine with a live React dashboard.

What works today:
- **Layer 1 — Ingestion:** Word, PDF, eCTD backbone, Dossplorer (mock + live client).
- **Layer 2 — Parsing:** run-level styling, PDF spans/blocks/links, leaf manifest, location anchors.
- **Layer 3 — Detection cascade:** **17 regex patterns across 9 reference types** — Study-ID, Section, Table, Figure, Listing, Appendix (numbered **and** letter-suffixed), CTD-leaf, URL, plus **document-type `DOC_REF`** cross-references ("the protocol" / "the SAP" / "the CSR") that make real clinical Protocol↔SAP↔CSR PDF pairs link to each other — then spaCy NER (rule fallback) + local-only LLM disambiguation (Ollama / deterministic stub).
- **Layer 4 — Injection:** Word hyperlinks **and** bookmarks, real cross-document links, PDF link annotations (sized to the matched phrase, at parity with Word run-level links), Dosscriber-aware style preservation, eCTD xref. **Word and PDF are at full feature parity** — detect → same-study cross-doc resolve → inject → preview (real tables + highlighting) → snippet/Reference View → viewer list → inline edit.
- **Layer 5 — Validation:** existence checker, target-correctness (token-Jaccard / sentence-transformers), anomaly detection (blue-text-no-link, orphans, circular refs, deprecated IDs).
- **Layer 6 — Reporting:** CSV + XLSX exporters, readiness score + grade, gate-review PDF.
- **Orchestration:** real LangGraph `StateGraph` (conditional push/flag edge) with a sequential fallback; in-memory run store with **write-through persistence to Neo4j** and **hydrate-on-startup** so runs survive a restart.
- **Selectable agents:** Fast / Balanced / Max-Accuracy presets + per-layer Advanced override, chosen per run from the UI.
- **Dashboard:** React + Vite SPA with live SSE pipeline status, a **3-pane Run Compare** (BEFORE | AFTER | **Linked-Documents viewer list**) with **real HTML-table rendering**, click-to-navigate snippets, inline link editing, a focused Reference View, Detection Layer Trace, review queue, and export center.
- **Link routing:** every link carries an authoritative `link_kind` (`external_url` / `cross_doc` / `internal_bookmark` / `cross_module`); a single shared helper guarantees **external web links always open in a new tab** (e.g. `NCT…` → `clinicaltrials.gov`) and never get routed into Reference View, while cross-doc links open Reference View and internal refs scroll-and-flash in place.
- **Auth & classified-document access (PLAN SEVEN):** self-hosted **SuperTokens** (core + its own Postgres, both in Docker — no identity data leaves the box) with email+password login, httpOnly **cookie sessions**, and `admin`/`user` roles. Every pipeline run is `classified` or `unclassified` (deny-by-default: `classified`); non-cleared users never see classified runs in lists and get **403** on all 22 run-scoped endpoints. A runtime **Security toggle** (admin-only) flips the whole gate on/off live, audit-logged. Auth is **OFF by default** (`HYPERLINK_AUTH_ENABLED=false`) so the app and test suite run without a SuperTokens core. Full deep-dive: [docs/auth-supertokens.md](docs/auth-supertokens.md).

---

## Quickstart

> All Python commands assume the shared virtualenv at `./.venv` is **activated** and
> are run **from `backend/`**. All frontend commands run **from `frontend/`**.

### 1. Activate the environment (once per shell)

```powershell
# from the repo root
.\.venv\Scripts\Activate.ps1
```

To rebuild the environment from scratch:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".\backend[all]"
```

> **Poetry (optional, used by CI):** `cd backend; poetry install --all-extras`.

### 2. (Optional) Start local services

```powershell
docker compose -f infra/docker/docker-compose.yml up -d redis neo4j ollama
docker exec hyperlink-ollama ollama pull llama3.2:3b   # one-time: the local LLM model (~2 GB)

# only needed when auth is enabled (HYPERLINK_AUTH_ENABLED=true):
docker compose -f infra/docker/docker-compose.yml up -d supertokens-db supertokens-core
```

Neo4j enables run-persistence (write-through + hydrate-on-startup). If it isn't
running the engine degrades gracefully — the in-memory run store stays the live
source of truth. (None of Redis / Neo4j / Ollama are required for a basic run.
The SuperTokens pair is only required when the auth gate is ON.)

### 3. Generate synthetic test data

```powershell
cd backend
python -m scripts.bootstrap_synthetic_data --out data/synthetic --docs 20
```

### 4. Run the full app (backend + dashboard)

```powershell
# Terminal A — FastAPI backend on http://localhost:8000   (from backend/)
cd backend
python -m uvicorn hyperlink_engine.api.app:app --reload --port 8000 --host 0.0.0.0

# Terminal B — React/Vite dashboard on http://localhost:5174   (from frontend/)
cd frontend
npm install        # first time only
npm run dev
```

Open **http://localhost:5174**, upload documents on the **Pipeline** screen
(pick a Fast/Balanced/Max agent profile), watch the LangGraph nodes advance live,
then open **Run Compare** to see the before/after with clickable injected links.

> A full 30-document walkthrough — including copy-paste command sets and a
> Windows/PowerShell appendix — lives in `RUN-GUIDE-30-DOCS.md`.

### 5. Headless batch run (no UI)

```powershell
cd backend
python -m hyperlink_engine.workers.batch_runner `
  --input data/synthetic --output output/run30 --mode threaded --workers 4 --verbose
```

### 6. Run the test suite

```powershell
cd backend
python -m pytest                 # full suite + 85% coverage gate
python -m pytest -q --no-cov     # fast (no coverage)
```

---

## Repository layout

```
hyperlink-engine/
├── backend/                          # Python backend (its own deployable unit)
│   ├── pyproject.toml · poetry.lock · .env(.example)
│   ├── src/hyperlink_engine/
│   │   ├── core/                     # pure engine library
│   │   │   ├── ingestion/            # Layer 1 — .docx, PDF, eCTD XML, Dossplorer loaders
│   │   │   ├── parsing/              # Layer 2 — token streams with location anchors
│   │   │   ├── detection/            # Layer 3 — regex + NER + LLM disambiguation
│   │   │   ├── injection/            # Layer 4 — Word/PDF hyperlink + bookmark writers
│   │   │   ├── validation/           # Layer 5 — existence, target, viewer, anomaly
│   │   │   ├── reporting/            # Layer 6 — CSV, XLSX, readiness score, gate PDF
│   │   │   └── graph/                # eCTD backbone + dossier graph (NetworkX + Neo4j)
│   │   ├── api/                      # FastAPI application (app.py)
│   │   ├── workers/                  # Celery app, tasks, batch_runner, cache
│   │   ├── orchestration/            # LangGraph StateGraph, runner, nodes, state, agents/
│   │   ├── adapters/                 # thin aliases for external clients (Neo4j, Dossplorer)
│   │   ├── audit/ · lifecycle/ · config/
│   │   ├── dashboard/                # react_frontend (paused; live React UI is /frontend)
│   │   └── models.py
│   ├── tests/                        # unit/{core,api,workers,adapters} + integration
│   ├── scripts/                      # bootstrap_synthetic_data, benchmark, push_results, …
│   └── data/                         # synthetic/ · samples/ · training/
├── frontend/                         # React + Vite SPA (src/{screens,components,contexts,styles})
├── infra/                            # docker/ · neo4j/ · redis/ · nginx/
├── docs/                             # pattern-catalog, architecture, ADRs, guides
├── .github/workflows/                # backend-ci.yml · frontend-ci.yml
├── Makefile                          # top-level task runner
└── README.md
```

See [docs/architecture.md](docs/architecture.md) and [docs/pattern-catalog.md](docs/pattern-catalog.md).

---

## Configuration

Settings live in `backend/src/hyperlink_engine/config/settings.py`, overridable via env
vars (prefix `HYPERLINK_`) or a `.env` file. Copy `backend/.env.example` to `backend/.env`.

Key knobs:
- `HYPERLINK_OLLAMA_HOST` — local LLM endpoint (default `http://localhost:11434`)
- `HYPERLINK_OLLAMA_MODEL` — local model tag (default `llama3.2:3b`; pull once with `ollama pull llama3.2:3b`)
- `HYPERLINK_ENFORCE_LOCAL_LLM_ONLY=true` — refuses any non-localhost LLM call (GxP / 21 CFR Part 11)
- `HYPERLINK_GRAPH_BACKEND` — `neo4j` (default) or `networkx`
- `HYPERLINK_NEO4J_URI` / `HYPERLINK_NEO4J_USER` / `HYPERLINK_NEO4J_PASSWORD` — Neo4j connection
- `HYPERLINK_LOG_FORMAT=console` — colored console logs during dev
- `HYPERLINK_AUTH_ENABLED` — master auth switch (default `false`; also flippable at runtime by an admin via the Security toggle)
- `HYPERLINK_SUPERTOKENS_CONNECTION_URI` / `HYPERLINK_SUPERTOKENS_API_KEY` — SuperTokens core (`http://localhost:3567`)
- `HYPERLINK_API_DOMAIN` / `HYPERLINK_WEBSITE_DOMAIN` — `http://localhost:8000` / `http://localhost:5174` in dev
- `HYPERLINK_DEFAULT_CLASSIFICATION` — `classified` (deny-by-default) or `unclassified` for new runs

---

## Developer workflow (top-level Makefile)

```bash
make install       # editable install of backend[all] + pre-commit
make test          # backend pytest with coverage gate
make lint          # ruff + black --check + mypy (backend)
make format        # black + ruff --fix (backend)
make backend       # run FastAPI on :8000
make frontend      # run Vite dev server on :5174
make synthetic     # generate a 20-doc synthetic dossier
make services-up   # docker compose up Ollama / Redis / Neo4j (infra/docker)
make services-down
```

> The `make` targets assume the `./.venv` is activated. On Windows without GNU Make,
> use the explicit commands from the Quickstart above, plus the backend lint/type-check below.

### Backend lint / type-check (without `make`, run from `backend/`)

```bash
../.venv/Scripts/python -m ruff check src tests scripts
../.venv/Scripts/python -m mypy src/hyperlink_engine
```

> To (re)install the backend package with all optional extras:
> `../.venv/Scripts/python -m pip install -e ".[all]"` (or, in CI, `poetry install --extras all`).

---

## Compliance posture

- All AI inference is **local-only** (Ollama + sentence-transformers). No external API calls.
- Documents are never mutated in place — every output is a new `*_linked` file.
- Every link injection appends an immutable audit record to `audit.jsonl`; with auth ON,
  the `actor` field carries the real logged-in user (review approvals and compliance
  sign-offs bind the session identity, not a free-text name).
- Identity is **self-hosted** too: SuperTokens core + Postgres run in-VPC ([docs/auth-supertokens.md](docs/auth-supertokens.md)).
- Source-of-truth for design decisions: [`docs/adr/`](docs/adr/).

---

## License

Proprietary — Celegence. Internal use only.
