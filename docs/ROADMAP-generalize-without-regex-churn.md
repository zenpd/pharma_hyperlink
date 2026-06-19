# Roadmap — from regex-churn to a self-improving reference engine

> Goal: the engine should **detect references on new documents/patterns** and make
> every **citation jump to its root definition** — *without* an engineer editing
> regex/heuristics for each new document. This is the plan to get there honestly.

---

## 0. Why 15 days has felt endless (the honest diagnosis)

Three things are happening at once, and naming them separately is half the fix:

1. **No scoreboard.** There is no single accuracy number, so every change is
   whack-a-mole — you fix doc A, doc B regresses, and nothing tells you the *net*
   direction. This alone makes any rule system feel infinite.
2. **Rules don't generalize.** Regex + anchoring heuristics encode *the documents
   you've seen*. A new template = a new edge case = a new rule. That curve never ends.
3. **Two different problems are conflated.** "Detect the reference" (detection) and
   "send the citation to the root" (anchoring) are *separate pipeline stages* with
   *separate fixes*. Tuning one never fixes the other, which feels like running in place.

**The reframe:** you will never reach "zero tuning." The win is to **move the tuning
from code → data, and from heuristics → learned structure**, so the system improves
from *usage* (reviewer corrections, more labeled docs) instead of *engineer-hours*
(regex commits). That is what ends the churn.

---

## 1. Foundation (do this FIRST) — the evaluation harness

You cannot stop the churn until you can *measure* it. This is the highest-leverage
first move and it is currently missing (the eval harness is "Phase 2" on paper).

- **Gold test set:** 30–50 documents, **hand-labeled**, *held out* — never used for
  training or rule-tuning. Cover multiple sponsors / templates / doc types
  (protocol, SAP, CSR). Diversity matters more than size.
- **Two metrics, reported separately** (because they are two problems):
  - **Detection:** precision / recall / F1 of references found vs. gold.
  - **Anchoring:** *definition-rate* = % of citations whose link lands on the **root**
    (we already measure this with `scripts/diag_anchor_coverage_all.py`).
- **Regression gate:** every change runs against the gold set; a number goes up or
  down. No more guessing. (This also protects the regex/heuristic fixes already shipped.)

> Deliverable: a "current accuracy" dashboard line. The moment this exists, "endless
> tweaking" becomes "measurable progress toward a target."

---

## 2. Track A — Detection that generalizes (kill the *detection*-regex churn)

**Problem it solves:** detecting references — especially **prose** ("as described in
the protocol") and **new templates** — without writing a new pattern each time.

The cascade already exists (`core/detection/entity_extractor.py`: regex → NER → LLM).
The plan repositions each layer:

- **A1 · Gold-labeled dataset (the real asset).** Bootstrap with *weak supervision*:
  auto-label with the **existing high-precision regex** (`regex_patterns.py`), then a
  human **corrects + adds the prose references regex missed**. Label the reference
  **and its role** (definition vs citation) — that role label also feeds Track B.
  You already have the scaffolding: `data/training/refs.*.jsonl`,
  `scripts/label_references.py`. Target ~500 *diverse* docs; **label quality > count**.
- **A2 · Train NER.** Start with the wired spaCy model (`core/detection/ner_model.py`),
  graduate to a transformer token-classifier (clinical BERT family) if it plateaus.
  Gate on **F1 ≥ 0.85** (the threshold already written into `docs/captis-integration.md`).
  **Keep regex as the high-precision voter** — NER *adds recall*, regex *holds precision*
  on structured refs. You stop *needing* new regex because NER covers novel patterns;
  regex stays for what it's already perfect at.
- **A3 · LLM as extractor/verifier, not tie-breaker.** Reposition Ollama
  (`core/detection/llm_disambiguator.py`): on the residual the cascade is unsure about,
  use it to (a) extract prose refs with no pattern, (b) verify a link points at the right
  thing. Keep it **surgical** (only low-confidence spans) for latency, cost, and
  auditability — not on every span.
- **A4 · The feedback loop (this is what ENDS the cycle).** Every correction a reviewer
  makes in the dashboard becomes a new labeled example → periodic retrain. Detection then
  improves from **use**, not from regex commits.

**Buys you:** recall on prose + graceful handling of new formats, improving over time.
**Honest limit:** NER still has a training distribution; truly alien layouts may miss
until labeled. It's *continuous improvement*, not *done forever*.

---

## 3. Track B — Parsing + Anchoring that generalizes (citation → root)

**Problem it solves:** the one you care about most — *"the citation must go to the
root"* — on documents whose layout you've never seen. **NER does not fix this.**

Root cause of the anchoring churn: PDF/Word extraction yields **loose spans**; we
rebuild "is this a heading/caption?" with bold/font/ToC **heuristics**, and every new
layout breaks one.

- **B1 · Layout-aware parsing (the structural foundation).** Augment raw PyMuPDF span
  extraction (`core/parsing/pdf_parser.py`) with a layout model that returns **typed
  blocks**: Title, Heading, Caption, Table, List, Paragraph, Footer, ToC. Options to
  evaluate: `Docling`, `unstructured`, `deepdoctection`, or a LayoutLM-family model;
  `pdfplumber`/`camelot` for table structure. This fixes **fragmentation** *and* yields
  **reliable definition coordinates** in one move.
- **B2 · Definition-vs-citation by structure.** Of all "Appendix D" occurrences, the one
  in a **Heading/Caption** block is the root; a **Paragraph** occurrence is a citation; a
  **ToC** block is excluded. This becomes a *structural lookup*, not a bold/font guess.
  Optionally a small **definition/citation classifier** trained on the role labels from
  A1 — this is the one place ML *does* help anchoring, and it generalizes past "bold = heading".
- **B3 · Structure-driven anchor index.** `core/injection/anchor_index.py` consumes the
  typed structure: for each reference key, find the block typed as its Heading/Caption →
  use its page+bbox. The bold-gating / ToC-exclusion heuristics we built become
  **fallbacks** for when the layout model is low-confidence — graceful degradation.
- **B4 · Cross-document** ("Table X of CSR Y") already routes via the target doc's index;
  reliable layout parsing makes that target index trustworthy too.

**Buys you:** citation → root on new layouts, because the **layout model** generalizes,
not a per-template heuristic. **Stays deterministic + auditable** (ML produces structure;
deterministic logic does the anchoring) — important for GxP.
**Honest limit:** layout models aren't perfect either; keep heuristics as fallback and
*measure* with the harness.

---

## 4. How the two tracks connect

- The **role labels** (definition/citation) from A1 train *both* the NER (detection) and
  the B2 classifier (anchoring) — one labeling effort, two payoffs.
- The **layout structure** from B1 also gives the NER better, de-fragmented text to read
  → detection recall goes up too.
- **Reviewer corrections** feed retraining for both tracks → the engine compounds.

---

## 5. Sequenced roadmap (realistic)

| Phase | Work | Delivers | Effort |
|---|---|---|---|
| **P0** | Eval harness + gold set (§1) | A real accuracy number; regression safety | days (mostly labeling) |
| **P1** | Layout parsing pilot (§B1) on 5–10 docs | Proof it fixes fragmentation + finds roots | ~1–2 weeks |
| **P2** | Bootstrapped labeling + train NER (§A1–A2) | Detection recall on prose/new formats | weeks (labeling-bound) |
| **P3** | Structure-driven anchor index (§B2–B3) | Citation→root on unseen layouts | ~2–3 weeks after P1 |
| **P4** | LLM extractor/verifier + feedback loop (§A3–A4) | Self-improving from reviewer corrections | ongoing |

Run **Track A (P2)** and **Track B (P1/P3)** in parallel — they don't block each other.

---

## 6. The honest bottom line

- There is **no architecture that needs zero tuning.** The win is changing the *shape*
  of the work: corrections in the UI → data → models, instead of engineer → regex.
- **Detection** generalizes via **trained NER + LLM** (Track A). **Anchoring** generalizes
  via **layout-aware parsing + structure-driven anchoring** (Track B). They are *different
  fixes* — investing only in NER will **not** fix the citation→root problem.
- **Highest leverage right now:** the **eval harness (P0)** — it converts 15 days of
  blind tweaking into measurable progress — and the **layout-parsing pilot (P1)**, which
  attacks both your pains (parsing *and* root anchoring) at once.
- Keep everything **deterministic at the anchoring step** so links stay auditable for
  regulatory use; ML produces *structure and candidates*, deterministic code makes the
  *final link*.
