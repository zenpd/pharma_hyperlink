# POC Proposal — analysis & revised path (SunPharma / Celegence eCTD)

Analysis of the "AI-Powered Hyperlink Automation & Validation Engine" POC proposal
against what is **actually built** in this repo and against the root cause of the
ongoing regex/heuristic churn.

## Verdict
The proposal is a **strong client-facing narrative** and its architecture matches the
codebase (most layers already exist as scaffolds). It will **not** stop the churn as
written, because it omits the three foundations that cause the churn:
1. **Layout-aware parsing** (the citation→root + fragmentation fix) — absent.
2. **A continuous evaluation harness** (the scoreboard) — only implied in "next steps".
3. **Trained NER + a correction→retrain loop** — proposal trains once; needs a loop.

Fix those three *under* the existing layers and the 15-day cycle ends.

---

## 1. Reality reconciliation (proposal claim → what's built → gap)

| Proposal layer | In the repo today | Gap for *your* pain |
|---|---|---|
| Parsing (python-docx, PyMuPDF, pdfplumber, lxml) | `core/parsing/*` — **span/run level** | **No layout model** → fragmentation + heuristic anchoring = the churn |
| NLP detection (Regex + NER) | regex strong; **NER untrained** (rule-fallback) | NER is aspirational today; regex carries it |
| Contextual disambiguation ("Section 5.3.2 → exact doc") | `anchor_index.py` — heuristic | This *is* the citation→root problem; underweighted in the proposal |
| Hyperlink injection (Word + PDF) | `docx_linker.py`, `pdf_linker.py` (PyMuPDF; pikepdf validates) | Works; Word→PDF cross-format is **page-level** (viewer limit) |
| eCTD backbone / graph | `ectd_*`, `core/graph/*` (Neo4j/NetworkX) | Exists; cross-module *root* landing needs target-doc structure (Track B) |
| Validation & anomaly | `core/validation/*` (existence, anomaly, viewer_compat, ha_rule_engine) | Scaffolded; viewer/HA-simulator depth unproven |
| QC dashboard | React + FastAPI (`api/app.py`, `frontend/`) | Exists |
| Scale (Celery/Redis) | `workers/*` | Wired; "500 in <4h" is the *scaled* target, not local |
| CAPTIS model-sharing | **design doc only** (`docs/captis-integration.md`) | Not implemented (no adopt script / models) |

**Takeaway:** you are not missing layers — you are missing *foundations under them*.

---

## 2. The three insertions that stop the churn

### Insert A — Evaluation harness (Phase 0, Week 1–2) — *the scoreboard*
Build it from the "3 representative dossiers" the proposal already gathers, but make it
a **continuous regression gate** with **two metrics reported separately**:
- **Detection:** precision / recall / F1 vs gold.
- **Anchoring:** *definition-rate* = % of citations landing on the **root**
  (already computed by `scripts/diag_anchor_coverage_all.py`).

> Why first: 15 days felt endless because there was no number telling you the *net*
> direction. This converts whack-a-mole into measurable progress and protects every
> shipped fix from regression.

### Insert B — Layout-aware parsing (spike Week 1–2, integrate Phase 1) — *the citation→root fix*
Augment span extraction with a model that returns **typed blocks** (Heading, Caption,
Table, ToC, Paragraph). Candidates: **Docling, `unstructured`, deepdoctection**, or a
LayoutLM-family model. This fixes **fragmentation** *and* yields **reliable definition
coordinates**. The anchor index then does a **structural lookup** (the Heading/Caption
block *is* the root) instead of bold/font heuristics that break per template.

> Proof this is the right lever (from this session): "Appendix D" linked to the
> *citation* page (p6) until we used the **bold heading** signal to find the root (p92).
> A layout model makes that classification general instead of a hand-tuned heuristic.

### Insert C — Trained NER + correction→retrain loop (Phase 1–2) — *the detection-recall fix*
- Bootstrap labels with the **existing regex** (high precision), then a human **adds the
  prose references** regex misses. **Label definition-vs-citation roles** too — they feed
  both NER *and* the anchoring classifier.
- Train NER (spaCy → transformer if it plateaus), gate at **F1 ≥ 0.85**.
- **Keep regex as the precision voter.** NER adds recall + generalization to new patterns.
- **Reviewer corrections → labels → periodic retrain.** This is what ends "edit regex per
  doc": tuning moves from *code* to *data*.

---

## 3. Sharper success metrics (replace the coarse ">90% detection")

| Proposal metric | Problem | Replace with |
|---|---|---|
| ">90% reference detection" | Already ~100% on *structured* refs via regex; hides the hard part | **Detection F1 on gold** *and* **definition-rate (citation→root) ≥ target**, reported separately |
| "<2% broken links" | Conflates broken with mis-targeted | broken-rate **and** wrong-root-rate |
| "60–75% effort reduction", "<30s/link" | Projections, unmeasured | Substantiate via the harness before quoting to the client |
| "100% link functionality in HA simulators" | Depends on simulator access + cross-format reality | Scope to Adobe + headless Chrome first; flag Word→PDF as page-level |

---

## 4. Revised 12-week path (keep the 3 phases; re-sequence the inside)

**Phase 0 — Foundation (Week 1–2)**
- Gold set + **eval harness** (Insert A). Pattern/role inventory from SOPs.
- **Layout-parsing spike** (Insert B) on real docs → go/no-go.

**Phase 1 — Single Module (Week 1–4)** *(attack anchoring EARLY, not in Phase 3)*
- Detection: regex + start bootstrapped labeling + initial NER → measure F1.
- Parsing: integrate **layout-aware parsing** → typed structure.
- **Anchoring: structure-driven anchor index → measure definition-rate.** ← citation→root
- Injection: Word + PDF (exists). Style preservation (exists).
- Gate: F1 **and** definition-rate both ≥ target on gold.

**Phase 2 — Multi-Module + Scale (Week 5–8)**
- eCTD backbone graph (exists) + cross-module linking → **cross-module root landing uses
  each target doc's layout-derived index** (depends on Phase 1 Track B).
- Bulk pipeline (Celery — exists) for 500-doc batches.
- Anomaly v1 (blue-text-without-link — exists) + **correction→retrain loop** (Insert C).
- Dashboard v1 (exists).

**Phase 3 — Submission-ready (Week 9–12)**
- Viewer validation: Adobe + headless Chrome (realistic); HA simulators *pending tool access*.
- HA rules (`ha_rule_engine` — exists). Dossplorer QC push.
- LLM as **extractor/verifier** on the residual (Insert C) + final QC reports.

---

## 5. Honest flags to carry into the client conversation
- **NER is untrained today** — Phase 1 "train NER" is real work, not a config flag.
- **CAPTIS model-sharing is a design doc**, not built.
- **Word→PDF links land at the page, not the exact spot** (PDF-viewer limit) — affects
  "100% functionality" claims; mitigated by `#page=N`.
- **2 engineers / 12 weeks** proves the *approach* on a bounded scope; production-grade
  500-doc/HA-viewer/full-integration is beyond a 12-week 2-person POC — frame accordingly.
- **Don't quote accuracy %s** until the harness produces them.

---

## 6. Exact immediate next steps (revised Week 1–2)
1. **Gather 3 gold dossiers** (IND/NDA/MAA) — *and label definition vs citation roles*, not
   just references.
2. **Stand up the eval harness** with the two metrics; baseline the current engine (get the
   first real number).
3. **Run a layout-parsing spike** (Docling/`unstructured`) on the NCT01101035 protocol and
   one Dosscriber Word doc — measure: does it reassemble captions and classify the
   "Appendix D" heading as the root *without regex*? Go/no-go on Track B.
4. **Pattern/role inventory** from SunPharma publishing SOPs (Study-ID formats, section
   schemes, CTD-leaf refs) → the labeling schema.
5. Only then **kick off Phase 1** with the re-sequenced plan above.
