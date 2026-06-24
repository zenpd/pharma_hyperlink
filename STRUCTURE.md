# Project Structure

This document explains the repository layout so there is no ambiguity about
which folder is the real project and where each piece lives.

## The real project root

```
C:/Zensar/Hyperlink automation/hyperlink-engine/      ← THE PROJECT (git repo lives here)
```

The git repository is at `hyperlink-engine/.git`. All commits, history, and work
happen here.

## Monorepo top level

The project is an **enterprise monorepo** — three independently-deployable units
plus shared infrastructure and documentation:

```
hyperlink-engine/
├── backend/     Python engine + FastAPI API + Celery workers + LangGraph orchestration
├── frontend/    React + Vite dashboard SPA (the live UI)
├── infra/       Docker Compose + Neo4j / Redis / nginx configs
├── docs/        architecture, pattern catalog, ADRs, run guides
├── .github/     CI workflows (backend-ci, frontend-ci)
├── Makefile     top-level task runner
└── .venv/       shared Python virtualenv (gitignored, editable-installs backend/src)
```

## Related folders (NOT the project)

| Path | What it is | Status |
|------|-----------|--------|
| `C:/Zensar/Hyperlink automation - Copy/` | Manual backup snapshot | Backup only — do not edit |
| `C:/Zensar/Hyperlink automation*.zip` | Zipped backups | Archive only |
| `C:/hyperlink_old_react_frontend/` | Static design mockup (1440×900 canvas) | Reference for design tokens; not runnable |

The **live, working frontend** is `hyperlink-engine/frontend/` (extracted to the
monorepo root). The mockup at `C:/hyperlink_old_react_frontend/` is only a visual
reference — its design tokens were ported into the live app's `styles/app.css`.

## Backend source tree (`backend/src/hyperlink_engine/`)

```
core/             pure engine library (no framework deps)
  ingestion/      Layer 1 — load .docx / .pdf / eCTD XML / Dossplorer metadata
  parsing/        Layer 2 — extract paragraphs, runs, styling
  detection/      Layer 3 — regex → spaCy NER → Ollama LLM cascade
  injection/      Layer 4 — write hyperlinks into .docx / .pdf
  validation/     Layer 5 — existence, target-correctness, anomalies
  reporting/      Layer 6 — CSV / XLSX exports + readiness score
  graph/          eCTD backbone graph (NetworkX in-memory, Neo4j persistent)
api/              FastAPI application
  app.py            the REST API + dashboard backend (uvicorn entrypoint)
  routes/ middleware/   placeholders for a future route split
workers/          Celery tasks + extractor cache + batch runner
  celery_app.py · tasks.py · batch_runner.py · cache.py
orchestration/    pipeline runner + LangGraph StateGraph + selectable agents
  graph.py          real LangGraph StateGraph (nodes + conditional edges)
  runner.py         drives the graph (sequential fallback if langgraph absent)
  nodes.py          the node functions (one per pipeline step)
  state.py          PipelineState + in-memory run store
  agents/           selectable per-layer agents (fast/balanced/max)
adapters/         thin aliases re-exporting Neo4j + Dossplorer clients from core
dashboard/        react_frontend (paused — the live UI is the top-level frontend/)
config/           Pydantic settings + structlog setup + fixtures
audit/            append-only GxP audit trail
lifecycle/        stage transforms
models.py         shared Pydantic data contracts
```

> Imports follow the layout: `hyperlink_engine.core.detection.…`,
> `hyperlink_engine.workers.tasks`, `hyperlink_engine.api.app`, etc.

## Frontend tree (`frontend/`)

```
src/
  App.tsx · main.tsx · api.ts · types.ts
  screens/      page-level components (Dashboard, Pipeline, RunCompare, …)
  components/   shared UI (BeforeAfter, RunSelector)
  contexts/     React contexts (ActiveRun)
  styles/       app.css (design tokens ported from the mockup)
```

## Two compare screens (intentional)

* **Run Compare** (`frontend/src/screens/RunCompare.tsx`) — before/after for documents
  YOU uploaded and ran through the pipeline. Use this for real runs.
* **Comparison** (`frontend/src/screens/Comparison.tsx`) — static demo data only. Kept
  for the canned demo; it will not show your uploaded runs.
