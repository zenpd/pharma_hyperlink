# Pharma Hyperlink Engine — Technical Design Document

**Project:** `pharma-hyperlink`  
**Stack:** FastAPI · LangGraph · PyMuPDF · spaCy · Tesseract · React/Vite  
**Purpose:** Automated hyperlink detection and injection into pharmaceutical regulatory dossier documents (CTD/eCTD submissions)

---

## 1. High-Level Design

### 1.1 Problem Statement

Regulatory submissions (IND, NDA, MAA) consist of hundreds of cross-referencing documents—CSRs reference protocols, summaries reference appendices, tables reference analyses. These cross-references are authored as plain text ("see Section 6.1 of Protocol TMX-67_301") with no actual hyperlink. Navigating a submission manually is error-prone and slow.

The engine automatically:
1. Detects every reference in every document (section, table, figure, appendix, study ID, citation)
2. Resolves each reference to its exact definition location in the dossier (which document, which anchor)
3. Injects live hyperlinks into the output PDFs and Word files
4. Scores and validates the result for regulatory readiness

### 1.2 System Boundaries

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Machine                           │
│                                                                 │
│  ┌─────────────────┐         ┌──────────────────────────────┐  │
│  │  React Frontend │  HTTP   │  FastAPI Backend (port 8088) │  │
│  │   (port 5174)   │◄───────►│                              │  │
│  └─────────────────┘         │  ┌────────────────────────┐  │  │
│                              │  │  Pipeline Orchestrator  │  │  │
│  ┌─────────────────┐         │  │  (LangGraph / sequential│  │  │
│  │  Input files    │ upload  │  │   fallback)             │  │  │
│  │  .pdf / .docx   │────────►│  └────────────┬───────────┘  │  │
│  └─────────────────┘         │               │              │  │
│                              │  ┌────────────▼───────────┐  │  │
│  ┌─────────────────┐         │  │  Core Engine Layers:   │  │  │
│  │  Output files   │◄────────│  │  Ingest→Parse→Detect   │  │  │
│  │  *_linked.pdf   │         │  │  →AnchorIndex→Inject   │  │  │
│  │  *_linked.docx  │         │  │  →Validate→Score       │  │  │
│  └─────────────────┘         │  └────────────┬───────────┘  │  │
│                              │               │              │  │
│                              │  ┌────────────▼───────────┐  │  │
│                              │  │  Optional: Neo4j graph │  │  │
│                              │  │  Tesseract OCR         │  │  │
│                              │  │  Ollama LLM (local)    │  │  │
│                              │  └────────────────────────┘  │  │
│                              └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Key design constraints:**
- **Air-gapped / on-prem** — no data leaves the machine. All LLM calls go to a local Ollama daemon. `enforce_local_llm_only=True` hard-blocks any non-localhost LLM endpoint (21 CFR Part 11 compliance posture).
- **Non-destructive** — input files are never mutated. Every run produces a parallel `*_linked.*` output copy.
- **Progressive degradation** — OCR optional, LLM optional, NER optional. The engine produces output even with only regex detection.

---

## 2. Repository Structure

```
pharma-hyperlink/
├── backend/
│   └── src/hyperlink_engine/
│       ├── api/app.py              # FastAPI application — all routes
│       ├── config/settings.py      # Pydantic settings (HYPERLINK_* env vars)
│       ├── orchestration/
│       │   ├── state.py            # PipelineState TypedDict + RunStore
│       │   ├── runner.py           # PipelineRunner — thread + cancel support
│       │   ├── nodes.py            # Node functions (load_dossier, parse_all, …)
│       │   ├── events.py           # SSE event bus
│       │   └── agents/
│       │       ├── registry.py     # fast / balanced / max presets
│       │       ├── detect_agents.py
│       │       ├── inject_agents.py
│       │       └── passthrough_agents.py
│       ├── core/
│       │   ├── ingestion/
│       │   │   ├── pdf_loader.py   # PyMuPDF wrapper; page_text_via_ocr()
│       │   │   ├── docx_loader.py
│       │   │   └── ocr_processor.py  # Tesseract / EasyOCR engines
│       │   ├── parsing/
│       │   │   ├── pdf_parser.py   # PdfDocument model builder
│       │   │   └── docx_parser.py
│       │   ├── detection/
│       │   │   ├── regex_patterns.py  # PatternRegistry + Match
│       │   │   ├── entity_extractor.py # Cascade: regex→NER→LLM
│       │   │   ├── ner_model.py    # spaCy EntityRuler / trained model
│       │   │   └── llm_disambiguator.py # Ollama/NVIDIA refinement
│       │   ├── injection/
│       │   │   ├── anchor_index.py # Definition-location index (PLAN TEN)
│       │   │   ├── pdf_linker.py   # PyMuPDF annotation writer
│       │   │   ├── docx_linker.py  # python-docx hyperlink writer
│       │   │   └── ref_index.py    # Cross-doc reference vocabulary
│       │   ├── validation/
│       │   │   ├── anomaly_detector.py  # 5 anomaly classes
│       │   │   ├── existence_checker.py
│       │   │   └── ha_rule_engine.py   # Health authority rules
│       │   ├── reporting/
│       │   │   ├── readiness_score.py  # 0–100 submission score
│       │   │   ├── csv_exporter.py
│       │   │   └── xlsx_exporter.py
│       │   └── graph/
│       │       ├── dossier_schema.py   # Neo4j v1/v2/v3 schema
│       │       └── backbone_graph.py
│       └── workers/
│           ├── tasks.py            # detect_references(), inject_links()
│           └── cache.py            # ExtractorConfig
├── frontend/src/
│   ├── App.tsx                     # Shell + sidebar routing
│   ├── api.ts                      # All fetch calls
│   ├── types.ts                    # Shared TypeScript interfaces
│   ├── screens/
│   │   ├── Pipeline.tsx            # Upload + run + cancel + progress SSE
│   │   ├── RunCompare.tsx          # Before/After doc comparison
│   │   ├── Comparison.tsx          # Single-doc before/after with links
│   │   ├── Dashboard.tsx           # Score cards
│   │   ├── LinksTable.tsx          # Filterable link table
│   │   ├── Issues.tsx              # Anomaly list
│   │   ├── ModuleMatrix.tsx        # CTD module breakdown
│   │   ├── ComplianceGate.tsx      # Gate review PDF export
│   │   ├── ReviewQueue.tsx         # Manual link approval
│   │   ├── DetectionTrace.tsx      # Per-link detection provenance
│   │   └── ExportCenter.tsx        # CSV / XLSX export
│   └── refMatch.ts                 # Scroll-to-reference matching logic
└── data/                           # Sample dossier documents
```

---

## 3. Processing Pipeline — End to End

### 3.1 Node Sequence

The pipeline executes as an ordered sequence of **nodes**. Each node takes a `PipelineState` dict, mutates it, and returns it. LangGraph is used when available; otherwise the runner falls back to a plain sequential loop.

```
Upload files (API)
       │
       ▼
┌─────────────────┐
│ 1. load_dossier │  Hash each file (SHA-256), stat size, build ingest_records[]
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ 2. parse_all     │  Count pages/paragraphs; route images through OCR
└────────┬─────────┘
         │
         ▼
┌──────────────────────┐
│ 3. detect_references │  Per-document: regex → NER → LLM cascade
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 4. build_anchor_idx  │  Build definition-location index from detections
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 5. inject_links      │  Write annotations into *_linked.pdf / *_linked.docx
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 6. validate          │  Existence check + anomaly detection
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 7. score             │  Compute 0–100 readiness score + grade
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ 8. push_to_store     │  Persist to Neo4j (best-effort)
└──────────────────────┘
```

Each node emits `{run_id, node, status, …}` events to an in-process **SSE event bus** (`orchestration/events.py`) so the frontend can stream live progress without polling.

### 3.2 State Object

`PipelineState` is a plain Python dict subclass (compatible with LangGraph's state schema):

| Key | Type | Description |
|---|---|---|
| `run_id` | str | 8-char UUID prefix — primary key throughout |
| `dossier_id` | str | Human label (e.g. "DOS-2026-DEMO") |
| `input_files` | List[Path] | Uploaded source files |
| `output_dir` | Path | `output/runs/{run_id}/output/` |
| `ingest_records` | List[dict] | Per-file: sha256, size, suffix |
| `detection_records` | List[dict] | Per-file: list of detections |
| `injection_records` | List[dict] | Per-file: links injected count |
| `links` | List[dict] | Final LinkRecord list |
| `anomalies` | List[dict] | Anomaly list |
| `score` | float | 0–100 |
| `grade` | str | "A"/"B"/"C"/"F" |
| `agent_profile` | dict | {layer: agent_id} overrides |
| `classification` | str | "classified" / "unclassified" |

---

## 4. Layer-by-Layer Technical Implementation

### 4.1 Ingestion Layer — PDF

**File:** `core/ingestion/pdf_loader.py`  
**Engine:** PyMuPDF (`fitz`)

PDF ingestion has three tiers that run in sequence until text is found:

```
page.get_text("dict")        ← Tier 1: native text layer
    ↓ empty?
page_text_via_pdfplumber()   ← Tier 2: pdfplumber (better with some encodings)
    ↓ empty?
page_text_via_ocr()          ← Tier 3: rasterise + Tesseract/EasyOCR
```

**OCR trigger logic (tasks.py / pipeline path):**
```python
_text_blocks = [b for b in page_dict.get("blocks", []) if b.get("type", 0) == 0]
if not _text_blocks and ocr_enabled and ocr_fallback_on_empty_page:
    # fire OCR
```

**OCR trigger logic (pdf_parser.py / compare-view path) — includes vector-path fix:**
```python
has_image_blocks = any(b["type"] == 1 for b in blocks)
has_drawings = bool(page.get_drawings())   # ← added for vector-path PDFs
if not blocks_out and (has_image_blocks or has_drawings):
    # fire OCR
```

**Why two trigger paths?** The pipeline detection path (`tasks.py`) calls OCR per-page during link extraction. The compare-view path (`pdf_parser.py`) calls OCR to populate the Before/After panel text. They serve different consumers so they maintain independent fallback logic.

**Vector-path PDFs** (e.g. Afatinib CSR) render text as bezier curve drawings via PDF path operators — no text extraction layer exists. `page.get_text()` returns empty; `page.get_images()` returns empty; but `page.get_drawings()` returns 927+ path objects. Checking `get_drawings()` correctly identifies these pages as needing OCR.

**Image detection (compare view):**

Old code used `get_text("blocks")` type=1, which only returns inline image markers in the PDF content stream. Clinical PDFs embed figures as form XObjects, which this never returns.

```python
# Correct: get_images() + get_image_rects()
for img_info in page.get_images(full=False):
    xref = img_info[0]
    for rect in page.get_image_rects(xref):
        if rect.width > 4 and rect.height > 4:
            raw_image_boxes.append((rect.x0, rect.y0, rect.x1, rect.y1))
```

Images above a minimum size (4×4 pt) are collected, clustered by proximity (`_cluster_image_rects`), rasterised as PNG at 2× scale, and base64-encoded into `data:image/png;base64,…` URIs embedded in the preview response.

### 4.2 Detection Layer — Reference Extraction

**File:** `core/detection/entity_extractor.py`  
**Cascade:** regex → NER → LLM

#### 4.2.1 Regex Engine (`regex_patterns.py`)

A `PatternRegistry` holds compiled `Pattern` objects. Each pattern has:
- A compiled `regex` (using the `regex` library for Unicode lookaheads)
- A `confidence` score (0.0–1.0)
- An optional `Validator` function for false-positive suppression
- A `label` (e.g., `SECTION_REF`, `TABLE_REF`, `STUDY_ID`)

Key pattern families:
- **SECTION_REF** — `Section 6.1`, `§ 2.3.4`, `Sections 4 through 7`
- **TABLE_REF** — `Table 14.2.1.1`, `Tables 3–5`
- **FIGURE_REF** — `Figure A`, `Figures 1 and 2`
- **APPENDIX_REF** — `Appendix B`, `Appendix III`
- **STUDY_ID** — `Protocol TMX-67_301`, `Study SP-2024-001`
- **CITATION** — author-year `(Helget et al., 2022)`, numbered `[7]`
- **LISTING_REF** — `Listing 16.2.1`
- **EXTERNAL_URL** — `https://clinicaltrials.gov/…`

Overlapping matches are resolved by `resolve_overlaps`: longer match wins; same-length ties prefer higher confidence.

#### 4.2.2 NER Model (`ner_model.py`)

spaCy `EntityRuler` with pharma-domain patterns as the base. If `HYPERLINK_NER_MODEL_PATH` points to a trained spaCy model, `SpacyNerExtractor` loads it instead — enabling a fine-tuned model trained on annotated dossier text.

NER catches references the regex catalog misses: compound surnames, abbreviated section titles, non-standard numbering.

#### 4.2.3 LLM Refinement (`llm_disambiguator.py`)

Low-confidence spans (below `llm_confidence_threshold`, default 0.7) are sent to the local Ollama daemon for confirmation/rejection. The prompt provides the matched text plus ±200 characters of surrounding context. The LLM returns a structured JSON decision: `{is_reference: bool, confidence: float, reasoning: str}`.

In `detect_hybrid` mode (`force_refine=True`), every span is sent regardless of confidence — useful for max-accuracy passes.

**Provider:** `ollama` (default, on-prem) or `nvidia` (NVIDIA API Catalog, POC/demo only — sends data off-machine).

#### 4.2.4 Agent Profiles

Three presets select the detection strategy per run:

| Profile | Detection | Speed | When to use |
|---|---|---|---|
| `fast` | regex only | fastest | Clean, well-formatted dossiers |
| `balanced` | regex + NER | default | General use |
| `max` | regex + NER + LLM | slowest | Final QC pass before submission |

The profile is selected at upload time and stored in `agent_profile` on the state.

### 4.3 Anchor Index — Definition Location (PLAN TEN)

**File:** `core/injection/anchor_index.py`

**The problem:** Without this layer, every link to "Table 14.2.1.1" would jump to the first sentence that *mentions* the table — not to the table itself.

The anchor index maps a canonical key (`table_ref_14_2_1_1`) to the **definition location** (the caption or heading), built in two passes:

1. **Detection-driven pass:** Detections that look like captions (caption regex fires, text starts with `Table`/`Figure`/etc., short length) are marked as definitions. First definition wins per key.
2. **Structure scan (additive):** PDF table-of-contents (`doc.get_toc()`) and DOCX heading paragraphs are scanned case-insensitively. This catches all-caps headings (`APPENDIX A.`) that the citation regex never fires on.

The result is a dict consumed by the inject step: `anchor -> (page_index, bbox)` for PDF, `anchor -> paragraph_index` for DOCX.

### 4.4 Injection Layer

#### 4.4.1 PDF Injection (`core/injection/pdf_linker.py`)

Uses PyMuPDF (`fitz`) exclusively:
- Opens source PDF read-only; saves a separate `*_linked.pdf` output
- For **internal anchors**: creates a named destination at the definition bbox, then adds a link annotation at the reference bbox pointing to that destination
- For **external URLs**: adds a URI link annotation
- For **cross-document links** (different file in the same run): links are created using the output file path of the target document

Why PyMuPDF and not pikepdf? PyMuPDF's link annotation API is smaller, more stable, and handles both reading and writing in one library. pikepdf is wired as a structural validator to confirm the saved PDF round-trips, but not for injection itself.

#### 4.4.2 DOCX Injection (`core/injection/docx_linker.py`)

Uses `python-docx`. Inserts `<w:hyperlink>` elements around the matched run text in the XML. Highlighted spans (yellow highlights in the authored document) get special treatment: `link_highlighted_spans=True` (default) ensures every highlighted span becomes one continuous link regardless of whether the regex also matched it.

### 4.5 Validation Layer

**File:** `core/validation/anomaly_detector.py`

Five anomaly classes, each with BLOCKER / WARNING / INFO severity:

1. **Blue text without hyperlink** — visual cue (blue colour) not backed by a link annotation. Sourced from `docx_parser.candidate_blue_runs()`.
2. **Orphaned references** — reference detected but no resolvable target. Indicates a missing document or numbering mismatch.
3. **Circular references** — A → B → A in the eCTD backbone graph. Detected via `cross_module_integrity.detect_circular_refs()`.
4. **Deprecated Study IDs** — identifier matches an entry in `data/deprecated_ids.yaml` (withdrawn / superseded studies).
5. **Suspicious link targets** — visible text says "Section 5.3.2" but annotation points to Section 4.x (semantic mismatch).

### 4.6 Scoring (`core/reporting/readiness_score.py`)

```
score = 100
  − 5  × broken_links
  − 2  × orphaned_refs
  − 3  × style_violations
  − 10 × blocker_anomalies
  − 2  × warning_anomalies
clamped to [0, 100]
```

Grade mapping: A ≥ 90, B ≥ 75, C ≥ 60, F < 60.

---

## 5. API Surface

All routes are registered in `api/app.py` via a single `create_app()` factory function.

### 5.1 Pipeline Routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/pipeline/upload` | Receive files (multipart), stage to `output/runs/{id}/input/`, return `run_id` |
| `POST` | `/api/pipeline/run/{run_id}` | Start pipeline in background thread |
| `POST` | `/api/pipeline/run/{run_id}/cancel` | Signal the runner to stop after current node |
| `GET` | `/api/pipeline/status/{run_id}` | Current status + score + node |
| `GET` | `/api/pipeline/stream/{run_id}` | SSE stream of node events |
| `GET` | `/api/pipeline/run/{run_id}/results` | Full run detail |
| `GET` | `/api/pipeline/run/{run_id}/links` | All links in the run |
| `GET` | `/api/pipeline/run/{run_id}/anomalies` | All anomalies |
| `GET` | `/api/pipeline/run/{run_id}/document-preview` | Before/After blocks for one doc |
| `GET` | `/api/pipeline/run/{run_id}/snippet` | Scrollable snippet for a specific link |
| `GET` | `/api/pipeline/run/{run_id}/export.csv` | CSV export |
| `GET` | `/api/pipeline/run/{run_id}/export.xlsx` | XLSX export |
| `PATCH` | `/api/pipeline/run/{run_id}/link` | Manual link approval/rejection |
| `GET` | `/api/pipeline/runs` | All in-memory runs (+ Neo4j hydration) |

### 5.2 Document Preview (`/api/pipeline/run/{run_id}/document-preview`)

Returns `DocPreview` JSON:
```json
{
  "doc_name": "Afatinib CSR PDF.pdf",
  "paragraphs": [
    {"index": 0, "type": "paragraph", "text": "…", "para_index": 0},
    {"index": 4, "type": "image", "src": "data:image/png;base64,…", "width_frac": 0.85}
  ],
  "links": [ { "link_text": "section 6", "target_anchor": "section_ref_6", … } ],
  "total_links": 27
}
```

The backend calls `_read_pdf_blocks()` which uses a parallel `ThreadPoolExecutor` (chunked by page) via `_process_pdf_page_chunk()`. Tables detected by a camelot/pdfplumber integration are excluded from the paragraph stream and returned as structured `{"type": "table", "rows": [[…]]}` blocks.

### 5.3 Snippet API (`/api/pipeline/run/{run_id}/snippet`)

Given a link's `link_location_descriptor` (e.g., `page1.span0:c224-233`), returns a `{heading, snippet, matched}` object. The heading is the section containing the link; the snippet is ±3 paragraphs of context; `matched=true` if the link text appears in that window. Used by the Detection Trace screen to show where each link was found.

---

## 6. Frontend Architecture

### 6.1 Routing

`App.tsx` is a single-page app with sidebar navigation. Screens are **kept mounted** (hidden via `display:none`) rather than unmounted on navigation — this preserves local state (scroll position, selected filters) when the user switches tabs.

Two special routing modes:
- **Standalone doc viewer:** `#/docview?run=&doc=&ref=` — renders `DocViewer` fullscreen. Used when the "Linked Documents" panel opens a cross-document link in a new tab.
- **Demo fallback:** Report screens fall back to `/api/dossiers/demo/…` endpoints when no completed pipeline run exists, so the UI is never blank.

### 6.2 Key Screens

| Screen | Purpose |
|---|---|
| `Pipeline.tsx` | Upload files, select agent profile, stream progress via SSE, cancel run |
| `RunCompare.tsx` | Pick a run and doc; render split Before/After view |
| `Comparison.tsx` | Single-doc Before/After with inline link highlighting and snippet sidebar |
| `Dashboard.tsx` | Score, grade, link health pie chart |
| `LinksTable.tsx` | Full paginated, filterable link table with status badges |
| `Issues.tsx` | Anomaly list with fix suggestions and manual dismiss |
| `ModuleMatrix.tsx` | CTD module breakdown (M2–M5) with ok/broken/unverified counts |
| `ComplianceGate.tsx` | Generate gate-review PDF for sign-off |
| `DetectionTrace.tsx` | Per-link provenance: regex/NER/LLM, confidence, snippet |
| `ReviewQueue.tsx` | Manual approve/reject queue for uncertain links |
| `ExportCenter.tsx` | Download CSV/XLSX exports |

### 6.3 Link Highlighting (`Comparison.tsx` + `refMatch.ts`)

**`segmentParagraph()`** splits a paragraph's text into `{text, isLink, link?}` segments. The match uses `normalizeWs()` before `indexOf()` — this is critical for OCR-derived text where PyMuPDF may collapse multi-space sequences differently from the extractor, causing misses.

**`findRefBlockIndex()`** (`refMatch.ts`) implements scroll-to-reference. It is:
- **Type-aware:** a `Section` reference never resolves to a table block
- **Boundary-safe:** `2.5` does not match inside `14.2.5.1` — uses a `(?<![\d.])num(?![\d.])` regex boundary
- **ToC-aware:** blocks containing dotted leaders (`……25`) are excluded (they list every number and would steal the scroll)

---

## 7. Configuration Reference

All settings use `HYPERLINK_` prefix. Key variables:

| Variable | Default | Effect |
|---|---|---|
| `HYPERLINK_OCR_ENABLED` | `false` | Master OCR switch |
| `HYPERLINK_OCR_ENGINE` | `tesseract` | `tesseract` or `easyocr` |
| `HYPERLINK_OCR_DPI` | `300` | Render DPI (quality vs. speed) |
| `HYPERLINK_OCR_FALLBACK_ON_EMPTY_PAGE` | `true` | Auto-OCR pages with no extractable text |
| `HYPERLINK_LLM_PROVIDER` | `ollama` | `ollama` (on-prem) or `nvidia` (POC only) |
| `HYPERLINK_LLM_FORCE_REFINE` | `false` | Send every span to LLM (max mode) |
| `HYPERLINK_ENFORCE_LOCAL_LLM_ONLY` | `true` | Block non-localhost LLM endpoints |
| `HYPERLINK_GRAPH_BACKEND` | `neo4j` | `neo4j` or `networkx` |
| `HYPERLINK_GRAPH_SCHEMA` | `v3` | v1 (core) / v2 (enterprise) / v3 (lifecycle) |
| `HYPERLINK_DEFAULT_AGENT_PROFILE` | `balanced` | Default detection preset |
| `HYPERLINK_AUTH_ENABLED` | `false` | SuperTokens auth gate |

---

## 8. Data Flow Diagram — Detection to Injection

```
Document (PDF or DOCX)
          │
          │ PyMuPDF / python-docx
          ▼
 Per-page / per-paragraph TEXT
          │
          │ PatternRegistry.find_all()
          ▼
 Regex Matches  ──────────────────────────────────────┐
          │                                            │
          │ SpacyNerExtractor.extract()                │
          ▼                                            │
 NER Matches                                          │
          │                                            │
          │ resolve_overlaps()                         │
          ▼                                            │
 Deduped Match List                                   │
          │                                            │
          │ LlmDisambiguator (if hybrid mode)          │
          ▼                                            │
 ExtractedReference[]                                  │
          │                                            │
          │ Cross-doc resolver (ref_index.py)          │
          │ ← which file in the run owns this anchor?  │
          ▼                                            │
 Detection Record                                      │
          │                                            │
          │                 AnchorIndex                │
          │  caption-scan ◄─────────────────────────── ┘
          │  (first definition wins)
          ▼
 anchor → (page, bbox) / paragraph_index
          │
          │ PdfLinker / DocxLinker
          ▼
 *_linked.pdf / *_linked.docx
  (named destinations + link annotations / <w:hyperlink>)
          │
          │ Validation + Scoring
          ▼
 LinkRecord[] + Anomaly[] + Score
```

---

## 9. Neo4j Graph Schema (v3)

The graph provides dossier-level querying and submission lifecycle tracking.

```
(Sponsor)-[:OWNS]->(Study)-[:HAS_DOSSIER]->(Dossier)
(Dossier)-[:INCLUDES]->(Document)
(Document)-[:HAS_REFERENCE]->(Reference)-[:TARGETS]->(Document)
(Reference)-[:DETECTED_BY]->(DetectionMethod)
(Dossier)-[:HAS_SEQUENCE]->(Sequence)-[:SUPERSEDES]->(Sequence)
(Sequence)-[:IN_STATE]->(:approval_state)
```

**v3 additions (lifecycle):** `Sequence`, `Approval`, `SUPERSEDES`, `INCLUDES` edges model the eCTD submission lifecycle — linked → compliance_approved → fda_ready. Each stage transition is tracked so a submission's history is queryable.

Graph backend is **best-effort**: Neo4j unavailability degrades to in-memory `_RunStore` only. `networkx` backend is available for testing/offline use.

---

## 10. OCR Architecture

**File:** `core/ingestion/ocr_processor.py`

Two engines behind a common interface:

```python
def ocr_pdf_page(page, page_index, *, engine, language, dpi, min_confidence) -> OcrPageResult
def ocr_pdf_page_words(page, page_index, …) -> OcrPageResultWithWords  # with per-word bboxes
```

**Tesseract path:**
1. `page.get_pixmap(matrix=Matrix(scale, scale))` — renders page to PNG at `scale = dpi/72`
2. `pytesseract.image_to_data()` — returns TSV with per-word confidence scores
3. Words below `ocr_min_confidence` (default 0.5) are dropped
4. Per-word pixel bboxes are converted to PDF points: `x_pt = x_px * 72.0 / dpi`

Why word-level bboxes? The injection step needs to place a link annotation precisely over the matched text. Without word bboxes, the fallback is a full-page annotation box — correct but imprecise. With word bboxes, each injected link covers only its text span.

**EasyOCR path:** Returns block-level text only (no per-word bboxes). The fallback annotation covers the full page. Useful on systems without a Tesseract binary.

---

## 11. Cancellation Design

**File:** `orchestration/runner.py`

Pipeline runs execute in a daemon thread. A `threading.Event` per `run_id` is stored in `_cancel_events`. The sequential loop checks the event before entering each node:

```python
cancel_ev = _cancel_events.get(state["run_id"])
for node_name, node_fn in _resolve_nodes(state):
    if cancel_ev is not None and cancel_ev.is_set():
        state["status"] = "cancelled"
        return state
    state = node_fn(state)
```

The event is cleaned up in a `finally` block when the thread exits, so `_cancel_events` never leaks stale entries. The frontend calls `POST /api/pipeline/run/{id}/cancel` which calls `cancel_run(run_id)` — sets the event and returns `{signalled: true}` immediately. The next node boundary (typically within 1–30 seconds depending on node duration) the pipeline stops cleanly.

---

## 12. Design Decisions — Hows and Whys

### Why PyMuPDF over pdfplumber as the primary engine?
PyMuPDF (`fitz`) provides both reading and writing in one library, with a stable link annotation API. pdfplumber is better at certain table extractions but cannot write. We use pdfplumber as Tier 2 fallback for text extraction only.

### Why a fixed node sequence rather than a pure LangGraph graph?
LangGraph requires an optional dependency. The sequential fallback in `runner.py` is the production default and runs without it. LangGraph is wired in as an enhancement when installed — same nodes, same state, but with built-in retry and conditional routing. The fallback ensures the engine works in constrained environments.

### Why is the anchor index separate from detection?
Detection (`tasks.py`) and injection (`pdf_linker.py`) are already large. The anchor index is a **pure transformation** of detection output — no I/O, no ML. Keeping it separate makes the "find where things are defined" logic independently testable and replaceable.

### Why store runs in-memory (`_RunStore`) rather than a database?
The primary persistence is Neo4j. The in-memory store acts as a write-through cache that is always consistent with the running state. On startup, `_RunStore._ensure_hydrated()` reloads past runs from Neo4j (lazy, once). If Neo4j is down, the store degrades to session-only memory — acceptable for the on-prem / single-operator use case.

### Why `get_images()` + `get_image_rects()` for the compare view?
`get_text("blocks")` with type=1 returns inline image markers from the PDF content stream (`Do` operator). Clinical PDFs almost universally embed figures as **form XObjects** referenced by name — these appear in `get_images()` but not in `get_text("blocks")`. The fix catches every embedded image regardless of how it was placed.

### Why check `get_drawings()` for the OCR trigger?
Vector-path PDFs (text rendered as bezier paths by the PDF generator) have no text layer and no embedded raster images — `get_text()` and `get_images()` both return empty. The only signal that the page has content is `get_drawings()`. Without this check, OCR was silently skipped and link detection returned zero results for these documents.

### Why `normalizeWs()` in link highlighting?
PyMuPDF collapses whitespace in `get_text("blocks")` using its own rules. The regex/NER extractor operates on a different text representation. On OCR-derived pages especially, the extractor may see `"Section  6"` (double space) while the preview block shows `"Section 6"`. Normalizing before `indexOf` makes the highlighting robust to this divergence.

### Why enforce `enforce_local_llm_only=True` by default?
21 CFR Part 11 and GxP regulations require an audit trail and controlled data handling for regulated document systems. Sending dossier content to a cloud API without authorization is a compliance violation. The flag is a hard runtime guard — it refuses to make the call rather than relying on operator configuration.

### Why the `detect_hybrid` mode sends every span to the LLM?
The regex catalog emits 0.92–0.99 confidence for most matches. With `llm_confidence_threshold=0.7` (default), the LLM would be skipped on essentially every reference — making "Max accuracy" mode indistinguishable from "Balanced". `force_refine=True` bypasses the threshold so the LLM genuinely participates in every detection decision.
