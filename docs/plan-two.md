# Plan Two — Hybrid LangGraph POC (Demo-First, 4-Doc Dossier)

> **Status:** Approved 2026-05-29 · **Re-prioritized 2026-05-29**
> **Builds on:** Phases 1–3 (already functionally complete)
> **Goal:** Demo-ready hybrid pipeline showcasing LangGraph orchestration + cross-document hyperlinks

## ⚡ Priority Split (re-prioritized)

| Track | Priority | Days | Deliverable |
|---|---|---|---|
| **Track A — Application Demo** | 🔴 **P1 (now)** | 3 days | Working end-to-end demo: 4 docs → 5 cross-doc clickable links → live LangGraph state in dashboard → CSV/XLSX reports |
| **Track B — Infra Enhancements** | 🟡 **P2 (later)** | 2 days | Redis SHA256 doc-cache + Neo4j `:Dossier`/`:Document`/`:Reference` schema extension |

**Rationale:** Demo must stand alone. The cache and extended Neo4j schema are nice-to-haves that improve repeat-run speed and graph queryability, but neither is required for the click-through demo. Track A ships first; Track B is layered on top once Track A is signed off.

---

## 0. Context

Phases 1–3 of the original plan are **functionally complete**: ingestion, parsing, three-layer detection (regex → spaCy NER → Ollama LLM), Word + PDF link injection, validation, anomaly detection, Neo4j adapter, Celery pipeline, FastAPI + Streamlit dashboards, and Dossplorer mock/live client are all working end-to-end.

**Plan Two is purely additive** — no refactor, no breaking changes. It addresses 5 concrete gaps that block a clean stakeholder demo:

| Gap | Why it matters for the demo |
|---|---|
| **No orchestration visibility** — pipeline runs as a Celery DAG; reviewers can't *see* the decision flow | LangGraph StateGraph turns the pipeline into a visible, conditional, recoverable state machine |
| **No cross-document demo asset** — synthetic data is per-doc, not a curated "container with 4 mutually-referencing docs" | A purpose-built 4× M5 study-report container shows clickable cross-doc hyperlinks live |
| **No parse-skip on repeat runs** — every demo run re-parses every doc (~30–60s wasted per re-run) | Redis SHA256 per-document cache: 2nd run skips already-parsed docs, demo loops in seconds |
| **Neo4j shows backbone only** — current schema persists eCTD structure but not *detected hyperlinks as first-class queryable entities* | New `:Dossier`, `:Document`, `:Reference` nodes + `DETECTED_IN` / `RESOLVES_TO` edges → reviewers can query "show every link from Doc A" in Neo4j Browser |
| **No live state in dashboard** — Streamlit shows final reports only, not which stage is currently executing | LangGraph state stream → Streamlit live node-status panel |

**Demo outcome:** In one terminal command, ingest a 4-document M5 container, watch the LangGraph state advance live in the dashboard, open the linked output `.docx`/`.pdf` files and click cross-document links that *actually navigate*, then query Neo4j Browser to inspect the persisted graph. Second run completes in seconds via cache.

**Out of scope for Plan Two (deferred):**
- Cross-dossier reference resolution (only scaffold + research notes)
- Production React dashboard (Streamlit only for demo)
- Auto-remediation (engine flags, doesn't auto-fix)
- Viewer compat regression (already covered in Phase 3 work)

---

## 1. Locked Scope Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Demo dossier composition | **4× M5 study reports in one module** | Simpler graph, cleaner cross-ref story, faster to generate |
| Cross-doc link count | **4–5 links total** (1 per doc, +1 extra in doc 4) | Minimal, easy walkthrough; forms a small cycle for demo of cycle detection |
| LangGraph state visibility | **Live state graph in Streamlit dashboard** | Demo wow-factor; reviewers see orchestration in real-time |
| Redis cache granularity | **Per-document SHA256** | Granular skip — partial dossier updates still cached for unchanged docs |
| Local LLM | **Keep Llama 3.1 8B** (already in `settings.py`) | Zero migration risk; already validated on regulatory text |
| Graph backend | **Neo4j** (already flipped in `settings.py` line 47) | Required for demo's "click leaf → see graph" story |

---

## 2. Action Sequence / Flow (LangGraph State Machine)

```
                           ┌──────────────────────┐
                           │  START               │
                           │  input: dossier_path │
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ load_dossier         │  ◄─── Dossplorer.get_metadata()
                           │ (DossplorerClient)   │       fixture: DOS-2026-DEMO
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ check_cache (Redis)  │  per-doc SHA256 lookup
                           └──────────┬───────────┘
                          cached?     │
                  ┌───────────────────┼───────────────────┐
                  ▼ all 4 cached      ▼ partial           ▼ none
       ┌──────────────────┐  ┌────────────────┐  ┌──────────────────┐
       │ skip_to_inject   │  │ parse_uncached │  │ parse_all        │
       └────────┬─────────┘  └───────┬────────┘  └────────┬─────────┘
                └────────────────────┴────────────────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ detect_references    │  regex → NER → (LLM if <0.7)
                           │ (entity_extractor)   │  fan-out: 1 task per doc
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ resolve_targets      │  leaf_resolver.py
                           │ (cross-doc mapping)  │  uses Neo4j backbone
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ inject_links         │  docx_linker + pdf_linker
                           │ (parallel per doc)   │  → output/{doc}_linked.{docx,pdf}
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ persist_to_neo4j     │  new: :Document + :Reference nodes
                           │ (enriched schema)    │
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ validate             │  existence + target + anomaly
                           └──────────┬───────────┘
                                      ▼
                           ┌──────────────────────┐
                           │ score_and_report     │  CSV + XLSX + readiness score
                           └──────────┬───────────┘
                              score ≥ 80?
                  ┌───────────────────┴───────────────────┐
                  ▼ yes                                   ▼ no
       ┌──────────────────┐                    ┌──────────────────┐
       │ push_dossplorer  │                    │ flag_for_review  │
       │ (mock client)    │                    │ (human-in-loop)  │
       └────────┬─────────┘                    └────────┬─────────┘
                └────────────────────┬───────────────────┘
                                     ▼
                           ┌──────────────────────┐
                           │  END                 │
                           │  emit state to UI    │
                           └──────────────────────┘
```

**Key state-graph properties:**
- **Conditional branches:** cache hit ratio, score threshold (`READINESS_FLOOR = 80`)
- **Parallel fan-out:** `detect_references` and `inject_links` run per-doc concurrently
- **Retry edges:** `inject_links` and `persist_to_neo4j` use exponential backoff (existing `pipeline_max_retries`)
- **State streamed:** Every node transition emits `LangGraphEvent` → Streamlit subscribes via FastAPI SSE endpoint

---

## 3. New Components (the only files to add)

| New file | Purpose | LOC est. |
|---|---|---|
| `src/hyperlink_engine/orchestration/__init__.py` | Module marker | 1 |
| `src/hyperlink_engine/orchestration/state.py` | `PipelineState` TypedDict (dossier_id, doc_hashes, cache_hits, references, anomalies, score, current_node, history) | ~60 |
| `src/hyperlink_engine/orchestration/graph.py` | LangGraph `StateGraph` build: nodes + conditional edges + checkpointer | ~150 |
| `src/hyperlink_engine/orchestration/nodes.py` | Node functions — thin wrappers over existing Celery tasks in `pipeline/tasks.py` | ~200 |
| `src/hyperlink_engine/orchestration/events.py` | `LangGraphEvent` + in-memory pub/sub for SSE | ~50 |
| `src/hyperlink_engine/cache/__init__.py` | Module marker | 1 |
| `src/hyperlink_engine/cache/redis_doc_cache.py` | `DocCache` class: `get(sha256)` / `put(sha256, parsed_doc)` with TTL | ~80 |
| `src/hyperlink_engine/graph/dossier_schema.py` | Extended Neo4j Cypher: `MERGE (:Dossier)`, `(:Document)`, `(:Reference)` + edges | ~120 |
| `scripts/generate_demo_dossier.py` | Generates 4× M5 study reports with 4–5 cross-refs (SP-2026-001..004) | ~150 |
| `scripts/run_demo.py` | One-command demo entry: orchestration + cache + Neo4j push, prints clickable URLs | ~80 |
| `data/synthetic/demo_dossier/` | Output of `generate_demo_dossier.py` — committed fixture | — |
| `tests/integration/test_langgraph_flow.py` | Walks the StateGraph; asserts conditional branches fire correctly | ~120 |
| `tests/integration/test_doc_cache.py` | Roundtrip: write → invalidate → re-read | ~40 |
| `tests/integration/test_dossier_schema.py` | Cypher assertions for new node/edge types | ~60 |

**Total new code:** ~1,100 LOC. **Zero refactors to existing modules** except light additions:
- `dashboard/streamlit_app.py` — add a "Live Pipeline State" tab subscribing to SSE (~80 LOC delta)
- `dashboard/api.py` — add `/api/orchestration/stream` SSE endpoint and `/api/orchestration/run` trigger (~60 LOC delta)
- `pyproject.toml` — add `langgraph = "^0.2"` and `langchain-core = "^0.3"` (optional extras group `[orchestration]`)

---

## 4. Neo4j Schema Extension

### Existing (keep as-is)
```cypher
(:Module {label})
(:Leaf {leaf_id, module, title, relative_path, operation})
(:Module)-[:CONTAINS]->(:Module|:Leaf)
(:Leaf)-[:REFERENCES {confidence}]->(:Leaf)
(:Leaf)-[:NEXT_SEQUENCE]->(:Leaf)
```

### New (`graph/dossier_schema.py`)
```cypher
(:Dossier {dossier_id, sponsor, submission_type, region, sequence_number, status})
(:Document {doc_id, sha256, filename, path, page_count, linked_path})
(:Reference {ref_id, text, source_layer, confidence_before, confidence_after,
             llm_reasoning, paragraph_index, run_index, char_offset, link_type})

(:Dossier)-[:HAS_DOCUMENT]->(:Document)
(:Document)-[:PUBLISHED_AS]->(:Leaf)                  // bridges Plan Two ↔ existing backbone
(:Reference)-[:DETECTED_IN]->(:Document)
(:Reference)-[:RESOLVES_TO]->(:Document|:Leaf)        // the click-through target
(:Document)-[:LINKS_TO {count}]->(:Document)          // aggregated edge for demo viz
```

### Demo Cypher queries (for stakeholders)
```cypher
// Show the demo dossier graph
MATCH (d:Dossier {dossier_id: 'DOS-2026-DEMO'})-[*1..3]-(n) RETURN d, n;

// Every link in Document 1 and where it points
MATCH (doc:Document {doc_id: 'M5-CSR-001'})<-[:DETECTED_IN]-(r:Reference)-[:RESOLVES_TO]->(target)
RETURN doc.filename, r.text, r.confidence_after, labels(target), target.filename;

// Aggregated cross-doc link counts (heatmap source)
MATCH (a:Document)-[l:LINKS_TO]->(b:Document) RETURN a.filename, b.filename, l.count;

// Which references needed the LLM (interesting for demo)
MATCH (r:Reference) WHERE r.source_layer = 'llm'
RETURN r.text, r.llm_reasoning, r.confidence_before, r.confidence_after;
```

---

## 5. Redis Doc Cache Design

**Key format:** `hle:doc:{sha256}` → JSON-serialized `ParsedDocument` (Pydantic model from existing `models.py`)
**TTL:** 7 days (configurable via `HYPERLINK_DOC_CACHE_TTL_SECONDS`, default 604800)
**Eviction:** Redis `MAXMEMORY` with `allkeys-lru` policy (set in `docker-compose.yml`)

**Cache check logic** (in `orchestration/nodes.py::check_cache`):
```python
for doc_path in dossier.documents:
    sha = sha256(doc_path)
    if cache.exists(sha):
        state["cache_hits"].append(doc_path)
        state["parsed_docs"][doc_path] = cache.get(sha)
    else:
        state["cache_misses"].append(doc_path)

if len(cache_hits) == len(documents):  →  edge "skip_to_inject"
elif len(cache_hits) > 0:              →  edge "parse_uncached"
else:                                   →  edge "parse_all"
```

**Demo guarantee:** Second run of the same 4-doc dossier shows `cache_hits = 4` in the live state panel and completes in <5 seconds (vs ~45s cold).

---

## 6. Demo Dossier (4× M5 Study Reports, 5 Cross-Doc Links)

`scripts/generate_demo_dossier.py` produces 4 mutually-referencing CSR documents under `data/synthetic/demo_dossier/m5/53-clin-stud-rep/`:

| Filename | Study ID | Cross-references (links injected) |
|---|---|---|
| `csr-sp-2026-001.docx` | SP-2026-001 (Phase 1 PK) | 1 link → SP-2026-002 |
| `csr-sp-2026-002.docx` | SP-2026-002 (Phase 2a efficacy) | 1 link → SP-2026-003 |
| `csr-sp-2026-003.docx` | SP-2026-003 (Phase 2b dose-finding) | 1 link → SP-2026-004 |
| `csr-sp-2026-004.docx` | SP-2026-004 (Phase 3 pivotal) | 2 links → SP-2026-001 and SP-2026-002 |

**Total cross-doc references:** 5. Forms a small cycle (1→2→3→4→1) → exercises the cycle detector in `anomaly_detector.py` for a demo "see, the engine caught the cycle" moment.

All detectable via existing regex patterns (no NER/LLM strictly needed; can seed one ambiguous case if we want to exercise the LLM branch).

**Rendered to PDF** via the existing `injection/pdf_linker.py` path so the demo can show clickable links in both Word and PDF.

---

## 7. Live Dashboard State Panel

**`dashboard/streamlit_app.py` additions:**
- New tab: **"🔄 Live Pipeline"**
- Uses Streamlit `st.empty()` container polling the new SSE endpoint
- Renders the state graph as a `streamlit-agraph` or `pyvis` interactive graph, highlighting the **currently executing node** in yellow, **completed** in green, **failed/retry** in red
- Side panel shows: `dossier_id`, `cache_hit_ratio`, `current_node`, `elapsed_seconds`, `score` (once available)
- Auto-refresh every 500ms during a run

**`dashboard/api.py` additions:**
```python
@app.post("/api/orchestration/run")
async def run_demo(dossier_path: str): ...   # triggers LangGraph compilation + invocation
@app.get("/api/orchestration/stream/{run_id}")
async def stream_state(run_id: str): ...      # SSE: yields LangGraphEvent on each transition
```

---

## 8. Cross-Dossier Reference Research (Scaffold Only)

Plan Two does **not** implement cross-dossier resolution but lays the foundation:

**Findings from exploration:**
- Current scope is single-dossier; no `external_ref` / `cross_dossier` code paths exist.
- Neo4j extension naturally supports it: multiple `:Dossier` nodes coexist in the same graph; a `:Reference` can `RESOLVES_TO` a `:Document` belonging to a different `:Dossier`.

**Research note to document in `docs/cross-dossier-references.md` (new):**
- **Intra-dossier refs (Plan Two scope):** docs in same `:Dossier` reference each other → resolved via Neo4j local query.
- **Inter-dossier refs (Phase 4):** doc references a prior submission's content → requires Dossplorer cross-submission lookup + Neo4j graph spanning multiple `:Dossier` nodes.
- **Recommended approach:** Maintain a global `:Reference` namespace; let `RESOLVES_TO` cross dossier boundaries naturally; let Cypher constraints (`UNIQUE(dossier_id, doc_id)`) prevent collisions.
- **Stub method** in `dossplorer_client.py`: `find_external_document(study_id) -> Optional[DossierMetadata]` (raises `NotImplementedError` for now; documented as Phase 4).

---

## 9. Reuse Map (what NOT to rebuild)

| Need | Already exists at | Plan Two action |
|---|---|---|
| docx parsing | `parsing/docx_parser.py` | **Reuse as-is** |
| pdf link injection | `injection/pdf_linker.py` | **Reuse as-is** |
| regex/NER/LLM detection | `detection/entity_extractor.py` | **Reuse as-is** |
| Ollama disambiguation | `detection/llm_disambiguator.py` | **Reuse as-is** |
| Neo4j connection | `graph/neo4j_adapter.py` | **Extend** with new node/edge writers in `graph/dossier_schema.py` |
| Backbone graph (NetworkX) | `graph/backbone_graph.py` | **Reuse as-is** (LangGraph orchestrates, doesn't replace) |
| Celery tasks | `pipeline/tasks.py` | **Wrap as LangGraph nodes** in `orchestration/nodes.py` — do not duplicate task logic |
| FastAPI app | `dashboard/api.py` | **Append** new SSE + trigger endpoints |
| Streamlit dashboard | `dashboard/streamlit_app.py` | **Append** new live-state tab |
| Dossplorer mock | `ingestion/dossplorer_client.py` | **Add** one fixture `DOS-2026-DEMO` to `config/fixtures/dossplorer_dossiers.json` |
| Anomaly + validation | `validation/*` | **Reuse as-is**, invoked from LangGraph `validate` node |
| CSV/XLSX export | `reporting/*` | **Reuse as-is**, invoked from LangGraph `score_and_report` node |
| Audit trail | `audit/trail.py` | **Reuse**: every LangGraph node transition logs to `audit.jsonl` |
| Settings | `config/settings.py` | **Add** 3 fields: `langgraph_checkpoint_dir`, `doc_cache_ttl_seconds`, `readiness_floor` |

---

## 10. Step-by-Step Demo Execution (4 Terminals, PowerShell)

### Terminal 1 — Services
```powershell
docker compose up -d ollama redis neo4j
docker exec hyperlink-ollama ollama pull llama3.1:8b   # one-time
```

### Terminal 2 — Generate demo dossier (one-time)
```powershell
poetry run python -m scripts.generate_demo_dossier `
  --out data/synthetic/demo_dossier `
  --study-ids SP-2026-001,SP-2026-002,SP-2026-003,SP-2026-004
```

### Terminal 3 — Dashboard + API
```powershell
poetry run uvicorn hyperlink_engine.dashboard.api:app --port 8000
# in a separate pane:
poetry run streamlit run src/hyperlink_engine/dashboard/streamlit_app.py --server.port 8501
```
Open browser → `http://localhost:8501` → click **"🔄 Live Pipeline"** tab.

### Terminal 4 — Trigger the demo run
```powershell
poetry run python -m scripts.run_demo `
  --dossier data/synthetic/demo_dossier `
  --dossier-id DOS-2026-DEMO `
  --output output/demo_run
```

**Watch the dashboard:** nodes light up in sequence. Final outputs:
- `output/demo_run/csr-sp-2026-001_linked.docx` (and `.pdf`) × 4 documents
- `output/demo_run/validation_report.csv`
- `output/demo_run/anomalies.xlsx`
- Readiness score printed to console

### Demo moments to highlight
1. Open `csr-sp-2026-001_linked.pdf` in Adobe → click "see CSR SP-2026-002" → PDF navigates to `csr-sp-2026-002_linked.pdf`
2. Open Neo4j Browser at `http://localhost:7474` → run the demo Cypher queries from §4
3. Re-run Terminal 4 → cache hits = 4/4 → pipeline completes in <5s, state graph shows the "skip_to_inject" branch firing
4. Show the cycle anomaly: 1→2→3→4→1 detected by `anomaly_detector.py`

---

## 11. Verification Plan

**Functional verification:**
```powershell
# Unit + integration suites
poetry run pytest tests/integration/test_langgraph_flow.py -v
poetry run pytest tests/integration/test_doc_cache.py -v
poetry run pytest tests/integration/test_dossier_schema.py -v

# Cold-run smoke (no cache)
poetry run python -m scripts.run_demo --dossier data/synthetic/demo_dossier --no-cache

# Warm-run smoke (cache hits expected)
poetry run python -m scripts.run_demo --dossier data/synthetic/demo_dossier
# Expect log line: "cache_hits=4/4, elapsed<5s"

# Click-through verification (manual)
# 1. Open output/demo_run/csr-sp-2026-001_linked.docx in Word → Ctrl+click each cross-ref → confirm navigation
# 2. Open output/demo_run/csr-sp-2026-001_linked.pdf in Adobe → click each → confirm cross-doc navigation
```

**Acceptance gates (Plan Two):**
- [ ] LangGraph state machine completes 4-doc dossier in <60s cold, <5s warm
- [ ] Live dashboard tab shows all 9 nodes transitioning in real-time
- [ ] All 5 cross-doc references detected; ≥90% resolve to correct target doc
- [ ] Clickable navigation works in both Word and Adobe Reader
- [ ] Neo4j Browser shows `:Dossier`, `:Document`, `:Reference` nodes for the demo run
- [ ] Cache invalidation: modify one doc's SHA256, re-run → exactly 1 cache miss + 3 hits
- [ ] Readiness score ≥80; cycle anomaly visible in report
- [ ] Cycle detected: 1→2→3→4→1 surfaced as anomaly

**Demo-day checklist:**
- [ ] Pre-pull Ollama model so first inference isn't slow
- [ ] Pre-run once to warm caches (in case demo machine is cold)
- [ ] Have Neo4j Browser tab pre-loaded with demo Cypher queries
- [ ] Have backup output files in case live run fails
- [ ] PDF viewer set to Adobe Reader (not Edge default) for reliable hyperlinks

---

## 12. Implementation Order (Re-Prioritized)

### 🔴 Track A — Demo (P1, ship first)

| Day | Deliverable | Files touched |
|---|---|---|
| **A1** | Generate 4-doc demo dossier (5 cross-doc links) + commit fixture | `scripts/generate_demo_dossier.py`, `data/synthetic/demo_dossier/` |
| **A2** | LangGraph state machine + node wrappers (no Redis cache, no extended Neo4j schema — only existing pipeline tasks) | `orchestration/{state,graph,nodes,events}.py`, `tests/integration/test_langgraph_flow.py` |
| **A3** | Live dashboard SSE + `run_demo.py` + end-to-end rehearsal | `dashboard/api.py`, `dashboard/streamlit_app.py`, `scripts/run_demo.py` |

**Track A LangGraph state machine (P1 — no cache nodes):**
```
load_dossier → parse_all → detect_references → resolve_targets
  → inject_links → validate → score_and_report
  → (score ≥ 80?) → push_dossplorer / flag_for_review → END
```
The `check_cache` / `skip_to_inject` / `parse_uncached` branches are deferred to Track B.

### 🟡 Track B — Infra Enhancements (P2, layer on after demo)

| Day | Deliverable | Files touched |
|---|---|---|
| **B1** | Redis SHA256 doc-cache + tests; add `check_cache` node + conditional edges to existing StateGraph | `cache/redis_doc_cache.py`, `orchestration/nodes.py` (extend), `tests/integration/test_doc_cache.py` |
| **B2** | Neo4j `:Dossier`/`:Document`/`:Reference` schema extension + `persist_to_neo4j` node + tests | `graph/dossier_schema.py`, `orchestration/nodes.py` (extend), `tests/integration/test_dossier_schema.py` |

**Net: 3 days to a demo-ready hybrid LangGraph POC. +2 days afterward for infra polish (cache + extended graph).**

---

## 13. Local Model Recommendation

**Recommendation: Stay with Llama 3.1 8B** (already configured in `settings.py`).

| Model | Why considered | Verdict |
|---|---|---|
| **Llama 3.1 8B** ✅ | Already integrated; validated on regulatory text; good 8K context | **Keep — zero migration risk** |
| Phi-3 Mini (3.8B) | Faster on POC hardware; smaller memory footprint | Skip — quality drop on long regulatory context |
| Mistral 7B Instruct | Strong reasoning, comparable size | Skip — marginal benefit, migration cost not justified |
| Qwen2.5 7B (multilingual) | Best for EU/JP regional variants | Skip — demo scope is US/EN; consider for Phase 4 |

**Embedding model:** `all-MiniLM-L6-v2` (already used in `target_validator.py`). Keep.

---

## 14. Hyperlinks That Actually Work (Click-Through Guarantee)

The demo's killer feature: **every injected link clicks through to its target document**.

**Word (.docx) links** — `injection/docx_linker.py`:
- Builds `w:hyperlink` XML element with `r:id` → `word/_rels/document.xml.rels`
- Anchor format: `bookmark://csr-sp-2026-002#Section-2.5` resolves via Word's bookmark engine
- Cross-doc: `external` relationship to sibling `.docx` file with `#bookmark` anchor

**PDF links** — `injection/pdf_linker.py`:
- pikepdf creates named destinations (one per heading) in each PDF
- PyMuPDF adds `Link` annotation with `URI` action pointing to sibling PDF + named destination
- Adobe Reader follows `file:///./csr-sp-2026-002_linked.pdf#nameddest=Section-2.5` reliably

**Demo guarantee:** All 5 cross-doc links navigate correctly in both Word and Adobe Reader on the demo machine.

---

## Summary

Plan Two is a **5-day, additive-only implementation** that ships a demo-ready hybrid POC built on top of the already-complete Phase 1–3 engine. It adds:
- **LangGraph** for visible orchestration with conditional branches
- **Redis doc cache** for sub-5-second warm reruns
- **Neo4j schema extension** for queryable hyperlink relationships
- **A curated 4-doc M5 dossier** with 5 click-through cross-references
- **A live dashboard panel** so reviewers see the pipeline state in real-time

**Demo command (single):** `poetry run python -m scripts.run_demo --dossier data/synthetic/demo_dossier`

Open browser, watch state graph, click links, query Neo4j. That's the demo.
