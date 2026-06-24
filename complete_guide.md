# Complete Guide — AI-Powered Hyperlink Automation Engine

A practical, end-to-end explanation of how the entire application works: the
architecture, the runtime flow, how references become hyperlinks, how
relationships are maintained, what files get created, and how to run it.

---

## 1. What the application does

Regulatory dossiers (eCTD submissions) contain thousands of cross-references —
"see Section 2.5", "CSR SP-2026-002", "Table 14.2.1.1", study registrations,
guidance URLs. Today these are hyperlinked **by hand** (~2,000 per dossier,
150–300 hours, 2–5% broken-link rejection risk).

This engine ingests the documents, **detects** every reference with an
AI cascade, **injects** real hyperlinks, **validates** them, and reports a
submission-readiness score — fully **on-prem** (no external LLM calls; GxP /
21 CFR Part 11).

---

## 2. The 6-layer architecture

```
Layer 1  Ingestion      load .docx / .pdf / eCTD XML            ingestion/
Layer 2  Parsing        extract paragraphs, runs, styling       parsing/
Layer 3  AI Detection   regex → spaCy NER → Ollama LLM          detection/
Layer 4  Injection      write hyperlinks into .docx / .pdf      injection/
Layer 5  Validation     existence + target + anomaly checks     validation/
Layer 6  Reporting      CSV / XLSX + readiness score            reporting/
```

Cross-cutting: `graph/` (eCTD backbone graph), `orchestration/` (LangGraph
pipeline + selectable agents), `dashboard/` (FastAPI + React), `config/`,
`audit/` (append-only GxP trail).

---

## 3. Runtime flow (what happens on a run)

The pipeline is a **real LangGraph state machine** (`orchestration/graph.py`).
A run streams through these nodes:

```
load_dossier → parse_all → detect_references → resolve_targets
   → inject_links → validate → score_and_report
                                     │ (conditional edge)
                         score ≥ 80 ─┴─ score < 80
                            ▼              ▼
                     push_dossplorer  flag_for_review → END
```

| Node | File / function | What it does |
|---|---|---|
| `load_dossier` | `nodes.node_load_dossier` | Reads uploaded files into state; copies them to the run's `input/` folder; computes SHA256. |
| `parse_all` | `nodes.node_parse_all` | python-docx extracts paragraphs + run-level styling and locations. |
| `detect_references` | `nodes.node_detect_references` **or** a selected detect agent | Runs the detection cascade (see §5). Produces `detections` per doc. |
| `resolve_targets` | `nodes.node_resolve_targets` | Maps each reference to a **target document** (see §6 — this is the relationship step). |
| `inject_links` | `nodes.node_inject_links` → `tasks.inject_links` | Writes `<stem>_linked.docx` with real hyperlinks (see §7). |
| `validate` | `nodes.node_validate` | Existence + anomaly checks; builds the link records for the dashboard. |
| `score_and_report` | `nodes.node_score_and_report` | Readiness score + CSV/XLSX. |
| `push_dossplorer` / `flag_for_review` | terminal | Score ≥ 80 → push (mock Dossplorer); else → human review queue. |

The runner (`orchestration/runner.py`) drives the compiled graph via
`graph.stream()`, syncing the in-memory run store after each node and emitting
SSE events so the dashboard stepper lights up live. If `langgraph` is not
installed, it falls back to an identical sequential loop.

**Selectable agents (Plan Three):** the detect/inject/etc. layers can be swapped
per run via a profile (Fast / Balanced / Max). `Max` = `detect_hybrid` (regex +
NER + Ollama LLM). The profile is chosen on the upload screen.

---

## 4. Where state lives

`orchestration/state.py` defines `PipelineState` (a dict) and an **in-memory**
`run_store` keyed by `run_id`. Each run holds: input files, output dir,
ingest/detection/injection records, links, anomalies, score, status, events.

> Runs are **in-memory only** — restarting the backend clears run history.
> (Persisting runs to a DB is future work.)

---

## 5. The AI detection cascade (Layer 3)

`detection/entity_extractor.py` orchestrates three stages:

```
text → regex patterns → spaCy NER → conflict resolution → LLM refinement → references
```

1. **Regex** (`detection/regex_patterns.py`) — deterministic catalog: study IDs
   (`SP-2026-001`, `NCT04827991`), section/table/figure/listing/appendix refs,
   CTD leaf paths, and **URLs** (`https://…`). Each match carries a confidence
   (mostly 0.95–0.99).
2. **spaCy NER** (`detection/ner_model.py`) — catches fuzzy/contextual refs the
   regex misses (only when the NER/`Balanced`+ profile is active).
3. **LLM disambiguation** (`detection/llm_disambiguator.py`) — local Ollama
   (`llama3.1:8b`). By default it only refines spans **below 0.7 confidence**.
   Because regex is so confident, the LLM rarely fires — so there is a switch:

   - `HYPERLINK_LLM_FORCE_REFINE=true` → **every** span is sent to the LLM.
   - The `Max` profile's hybrid agent uses the **real** Ollama (falls back to a
     deterministic stub only if Ollama is unreachable).

   This keeps the default path fast while letting you force a full LLM pass.

---

## 6. How relationships are maintained (your Q2)

There are **two** distinct "relationship" mechanisms in the codebase. It's
important to know which one the live pipeline actually uses.

### 6a. The live pipeline — in-memory dictionary matching (active now)

The running upload pipeline maintains reference→document relationships in
`nodes.node_resolve_targets` using a plain Python index — **no graph database**:

- It builds a `file_index` of every uploaded doc with a normalized **study key**
  (e.g. `csr-sp-2026-002-body` → `2026002`) and a doc-type hint (CSR / protocol
  / SAP / listings).
- `_resolve_one()` routes each reference to the most specific target:
  *"CSR SP-2026-002"* → study 002's CSR body; *"Protocol SP-2026-001"* → that
  protocol; a bare study ID → that study's CSR body.
- The result (`resolved_target_doc`) is what `inject_links` turns into a real
  cross-document hyperlink.

So **for the demo/MVP, relationships = in-memory token matching**, computed
fresh each run and discarded when the run ends.

### 6b. The eCTD backbone graph — NetworkX + Neo4j (Phase 2, present but dormant)

`graph/` contains a full graph model used by the **Phase-2 eCTD / cross-module**
work, not by the demo upload pipeline:

- `graph/backbone_graph.py` — **NetworkX** in-memory directed graph of the eCTD
  backbone (modules, leaves, references, sequence edges). Used for fast
  traversal during cross-module analysis. Consumed by `graph/leaf_resolver.py`,
  `graph/sequence_history.py`, `injection/ectd_xref.py`, and
  `validation/cross_module_integrity.py`.
- `graph/neo4j_adapter.py` — **Neo4j** persistence layer (Bolt). Stores the
  backbone as queryable nodes/edges for cross-run / cross-submission queries.

**Status:** these exist and are tested, but are **not invoked by the current
upload pipeline** — `nodes.py` does not import them, and `neo4j_adapter` is not
called anywhere at runtime. `graph_backend` defaults to `"neo4j"` in settings,
but nothing in the demo path persists to it. So:

| | NetworkX | Neo4j |
|---|---|---|
| What | In-memory graph library | Persistent graph database |
| Lifetime | Gone when the process ends | Survives across runs |
| Used by | Phase-2 eCTD/cross-module modules | Phase-2 persistence (deferred) |
| In the demo pipeline? | **No** | **No** (dormant) |

> **Bottom line:** NetworkX and Neo4j are **Phase 2** components. The MVP keeps
> relationships in a simple in-memory index for speed and zero infra. Wiring the
> backbone graph (and Neo4j persistence) into the live pipeline is the planned
> Phase-2 step (tasks #62/#63).

---

## 7. How references become hyperlinks (Layer 4) — three link types

`pipeline/tasks.inject_links` + `injection/docx_linker.py` produce real Word
hyperlink relationships. Three kinds coexist in the same document:

| Type | When | What gets written |
|---|---|---|
| **External website** | label `URL` (`https://…`) or NCT study ID | External hyperlink to the website (e.g. clinicaltrials.gov, fda.gov). |
| **Cross-document** | `resolve_targets` matched a *different* uploaded doc | External hyperlink to `<target>_linked.docx` (relative path) → Ctrl+click opens that file in Word. |
| **Internal bookmark** | section/table/figure refs within the same doc | `w:hyperlink` + `w:bookmark` anchor → jumps inside the doc. |

The change is additive: if no cross-doc target resolves, the link stays an
internal bookmark / external URL exactly as before.

> For cross-document Ctrl+click to work in Word, keep all `_linked.docx` files
> in the **same folder** (the pipeline writes them together).

---

## 8. Document creation at runtime (your Q3) — confirmed: YES

**Documents are created while the program runs.** During `inject_links`, for
every input `.docx` the engine writes a new linked copy — the originals are
never modified:

```
output/runs/<run_id>/
  input/                      ← copies of the uploaded originals
    csr-sp-2026-001-body.docx
  output/                     ← GENERATED at runtime
    csr-sp-2026-001-body_linked.docx   ← new file with hyperlinks injected
    ...
    validation_report.csv              ← generated by score_and_report
```

- Naming: `<original-stem>_linked<.docx|.pdf>`.
- These files are produced fresh on each run, served by
  `GET /api/pipeline/run/{run_id}/download/{filename}`, and previewed in
  Run Compare.
- The synthetic **demo dataset** is created by a separate script
  (`scripts/generate_csr_dossier.py`) — that's input generation, run on demand,
  not part of the pipeline.

---

## 9. The dashboard (FastAPI + React)

- **Backend:** `backend/src/hyperlink_engine/api/app.py` (FastAPI). Key endpoints:
  - `POST /api/pipeline/upload` (files + optional agent profile + classification) → `run_id`
  - `POST /api/pipeline/run/{run_id}` → starts the LangGraph run in a thread
  - `GET  /api/pipeline/stream/{run_id}` → SSE live node events
  - `GET  /api/pipeline/runs`, `/run/{id}/results`, `/run/{id}/download/{file}`,
    `/run/{id}/csv`, `/run/{id}/document-preview`
  - `GET  /api/agents` → agent catalog + presets
  - `GET  /api/dossiers/{id}/score|anomalies|links` (demo store)
  - `/api/review/*`, `/api/compliance/*`
  - `/api/auth/*` (SuperTokens middleware: signin/signup/signout/refresh),
    `GET /api/me`, `GET/POST /api/security/mode` — see `docs/auth-supertokens.md`
- **Frontend:** the active SPA is `hyperlink-engine/frontend/` (React + Vite, port 5174).
  Screens: Login (when auth is ON), Run Pipeline, Run Compare, Review Queue,
  Compliance Gate, Overview, Module Matrix, Link Inspector, Issues, Export,
  Comparison, Detection Trace.
- The original Streamlit POC dashboard and the `simple_frontend` SPA have been
  **removed**; `dashboard/` now only holds the paused `react_frontend/` scaffold.

### 9.1 Run Compare — 3-pane view + link routing

Run Compare shows **BEFORE | AFTER | Linked Documents** for a selected run +
document:
- **Real tables.** The preview endpoints emit structured blocks
  (`api/app.py::_read_docx_blocks` → `{type:"paragraph"|"table", …}`), so Word
  tables render as real HTML grids in both panels **and** the Reference View —
  not flattened `Cell | Cell` text. Caption links still highlight; bare numbers
  in data cells don't.
- **Linked Documents (viewer list).** A client-side projection of the preview's
  links — the other run documents this one points to, with counts + chips. Click
  a card to switch the compare to that document.
- **Link routing (authoritative `link_kind`).** `node_validate` tags each link
  `external_url` / `cross_doc` / `internal_bookmark` / `cross_module`. A shared
  helper (`externalUrl`/`isExternalLink` in `BeforeAfter.tsx`, reused by
  `RunCompare` and `ReferenceView`) guarantees **external web links always open in
  a new tab** (never Reference View / scroll), cross-doc links open the Reference
  View, and internal refs scroll-and-flash in place.

---

## 10. Orchestration tracing (LangGraph)

- The pipeline is a real compiled `StateGraph` — node execution and the
  conditional push/flag branch are genuine graph edges.
- **LangSmith tracing** (`orchestration/tracing.py`) is opt-in and OFF by
  default. It is GxP-guarded: a non-local endpoint is refused unless
  `langsmith_allow_cloud=true` (a dev-only escape hatch). See
  `docs/langsmith-dev.md`.
- The **audit trail** (`audit/trail.py` → `audit.jsonl`) is the on-prem,
  append-only record of every run — the compliance source of truth.

---

## 11. Configuration (key env vars, prefix `HYPERLINK_`)

| Var | Default | Purpose |
|---|---|---|
| `HYPERLINK_OLLAMA_HOST` | `http://localhost:11434` | Local Ollama daemon |
| `HYPERLINK_OLLAMA_MODEL` | `llama3.1:8b` | Local LLM model |
| `HYPERLINK_LLM_CONFIDENCE_THRESHOLD` | `0.7` | Below this → LLM refines |
| `HYPERLINK_LLM_FORCE_REFINE` | `false` | Send **every** span to the LLM |
| `HYPERLINK_DEFAULT_AGENT_PROFILE` | `balanced` | fast / balanced / max |
| `HYPERLINK_GRAPH_BACKEND` | `neo4j` | `networkx` or `neo4j` (Phase-2 graph) |
| `HYPERLINK_ENFORCE_LOCAL_LLM_ONLY` | `true` | Refuse non-local LLM/trace endpoints |
| `HYPERLINK_LANGSMITH_TRACING` | `false` | Enable LangGraph tracing (dev) |
| `HYPERLINK_AUTH_ENABLED` | `false` | Master auth switch (runtime-togglable by an admin) |
| `HYPERLINK_DEFAULT_CLASSIFICATION` | `classified` | Default classification stamped on new runs |

---

## 12. How to run (local)

```powershell
# 1) (optional) local LLM
docker exec hyperlink-ollama ollama pull llama3.1:8b

# 2) generate the demo dataset (4 study folders, 16 docs)
.venv\Scripts\python scripts\generate_csr_dossier.py

# 3) backend — run from backend/ (set the flag if you want the LLM exercised on every span)
$env:HYPERLINK_LLM_FORCE_REFINE = "true"
cd backend
..\.venv\Scripts\python -m uvicorn hyperlink_engine.api.app:app --port 8000

# 4) frontend
cd ..\frontend
npm run dev        # http://localhost:5174
```

**Demo flow:** Run Pipeline → drop a study folder (or all 16) → pick **Max** →
watch the LangGraph stepper → open Run Compare → click a link to follow it →
download the `_linked.docx` and Ctrl+click in Word → Export CSV (readiness).

---

## 13. Mental model in one paragraph

You upload Word docs. A **LangGraph** state machine walks them through six
layers. The **detection cascade** (regex → NER → local LLM) finds every
reference. **`resolve_targets`** decides what each reference points to using an
in-memory study-id index (the relationship logic — the NetworkX/Neo4j graph is
Phase-2 and not yet in this path). **`inject_links`** writes brand-new
`_linked.docx` files containing three kinds of real hyperlinks (website,
cross-document, internal). **Validation** scores submission readiness, and the
dashboard shows it all — entirely on-prem.
