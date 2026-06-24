# Hyperlink Engine 

> **UI:** http://localhost:5174 — the React SPA in `frontend/`.

---






---

## Pre-flight (do this 10 min before they join)

1. **Start the four terminals** (see `RUN-GUIDE-30-DOCS.md` / the run-commands doc):
   - **T1 Backend API** — from `backend/`: `python -m uvicorn hyperlink_engine.api.app:app --reload --port 8000`
   - **T2 Docker services** — from repo root: `docker compose -f infra/docker/docker-compose.yml up -d` (Ollama, Redis, Neo4j)
   - **T3 Frontend** — from `frontend/`: `npm run dev` → **http://localhost:5174**
   - **T4 Celery worker** *(optional — tasks run in-process by default)*.
2. **Pull the local LLM once** so the first inference isn't slow:
   `docker exec hyperlink-ollama ollama pull llama3.2:3b`
3. **Do one warm-up run** of the demo dossier (so caches are hot and you have a completed run on the board if the live one ever stalls).
4. **Open two browser tabs:** the dashboard (`:5174`) and **Neo4j Browser** (`http://localhost:7474`) — only if you plan to show the graph.
5. **(Optional) Auth demo:** the gate is OFF by default. To show login + classified-document access, also start `docker compose -f infra/docker/docker-compose.yml up -d supertokens-db supertokens-core`, set `HYPERLINK_AUTH_ENABLED=true`, and use `admin@sunpharma.test` / `officer@sunpharma.test` (password `Passw0rd!123`). Script: classified run invisible to the officer, 403 Access Denied on direct open, admin sees all + flips the Security toggle live.





---

## The story in one sentence

> "Upload a folder of study reports → the engine finds every cross-reference, injects
> real clickable hyperlinks, validates them, scores submission-readiness, routes it
> through a compliance review, and packages it for the FDA — **on-prem, with a full
> audit trail, and nothing ever leaves this machine.**"

## The cast (demo data)

| Thing | Value |
|---|---|
| Dossier | **DOS-2026-DEMO** |
| Documents | 4× Module 5 Clinical Study Reports — **SP-2026-001 … 004** |
| Why these | They **reference each other** ("See Section 2.5 of CSR SP-2026-002…") — so we can show *cross-document* links that actually navigate |
| Cross-refs seeded | ~12, including a few deliberately ambiguous ones to make the AI's LLM layer earn its keep |

---

# SCENE 0 — Framing the problem (≈2 min, no clicking yet)

🗣 **Say this:**
> "A single NDA dossier can need around **2,000 hyperlinks**. Done by hand, each link
> is 3–5 minutes of find-the-target, copy, paste, verify — that's **150–300 hours per
> dossier**, and it's the step where 2–5% of links end up broken, which is a top cause
> of submission rejections. SunPharma files thousands of these a year.
>
> This engine automates the detection, injection, validation, and QC of those links.
> Today I'll take four real study reports the whole way through — upload to submission —
> and you'll see every link the machine made and *why* it made it."

💡 pain — broken-link rejections and manual hours — before any technology. 

---

# SCENE 1 — The screen you're looking at (≈1 min)

🖱 **Click path:** Just have the app open at **http://localhost:5174**. It lands on **Run Pipeline**.

> "One screen, three groups in the left rail:
> **AI Pipeline** is the assembly line — run it, compare before/after, review, and clear compliance.
> **Reports** is the QC evidence — score, per-module health, every link, every issue, exports.
> **Analysis** explains *how* the AI decided.
> Top-right, notice the **On-Prem** badge — that's the whole compliance story in two words."

💡  Point at the **On-Prem badge** and say *"no document content ever calls an external service — no cloud AI, no internet."* For a regulated SME that single sentence removes their biggest objection up front.

---

# SCENE 2 — Run Pipeline: the engine works 

This is the centrepiece. Upload the four CSRs and watch the engine light up.

### 2a. Choose how the AI behaves

🖱 **Click path:** On the **⚙️ Agent Configuration** card, pick **🎯 Max accuracy**.
*(Optionally click **Advanced ▼** to reveal the six per-layer dropdowns: Ingest, Parse, Detect, Inject, Validate, Report.)*

> "Before we run, I choose a profile. **Fast** is regex only — pattern-matching, instant.
> **Balanced** adds an NLP model (spaCy NER) for context. **Max accuracy** adds a local
> language model that disambiguates the tricky references. Advanced lets a power user
> swap the engine behind any single layer. I'll run Max so you can later see exactly
> which links needed the AI's help."

💡 "You're in control of the accuracy/speed trade-off **per run** — the machine isn't a black box you have to accept wholesale."

### 2b. Upload the dossier

🖱 **Click path:** Leave **Dossier ID** as `DOS-2026-DEMO`. Drag the four `csr-sp-2026-00*.docx` files (or the whole `53-clin-stud-rep` folder) onto the **📂 drop zone** — or use **📁 Browse folder**. They appear under **STAGED (4 files)**. Click **▶ Run Pipeline**.

> "I can drop individual files or an entire nested folder — it walks the tree and picks
> up every `.docx` and `.pdf`. These four are clinical study reports that cite each other."

### 2c. Watch the assembly line — live

🖱 **Click path:** Nothing — just narrate the **Pipeline Stages** stepper as it streams.

> "This is the live pipeline — streamed from the server, not a canned animation:
> **Load Dossier → Parse Docs → Detect Refs → Resolve Targets → Inject Links → Validate
> → Score & Report → Push/Flag → Done.**
> Detect is finding the references. Resolve Targets is the clever part — it figures out
> that 'CSR SP-2026-002' means *that specific other document* and wires the link to it.
> Inject writes real Word hyperlinks. Validate confirms every one actually resolves."

💡  Call out the **Live Log** panel at the bottom — *"every step is timestamped and streamed; this is also what becomes the audit trail."*

### 2d. The result

🖱 **Click path:** When it finishes, point at the metadata strip (**Score / Grade / Links**) and the **Per-Document Results** table.

> "Done. We get a **readiness score and an A–F grade**, the **total links injected**, and
> a per-document breakdown — each CSR with its link count, all marked ✓ linked. From here
> I can download the linked `.docx`, compare it, or push it to review. Let's prove the
> links are real first."

❓ **Likely question:** *"Did it change my original files?"*
> **Answer:** *"Never. The engine writes new `*_linked.docx` copies and records a hash of
> the original in the audit log so QA can prove zero in-place mutation."*

---

# SCENE 3 — Run Compare: prove the links are real

This is the believability moment for a publishing SME — they need to *see* a hyperlink navigate.

🖱 **Click path:** On a document row in the results table, click **🆚 Compare** (or sidebar **AI Pipeline → Run Compare**). The newest run and first doc auto-select.

> "Left is the **original** paragraph text — no links. Right is the **same document after
> processing**, with every injected link highlighted. Green is validated, amber is
> 'unverified, please check', red is broken. The stats bar tells you how many links are
> **internal** (within the doc), **cross-document** (to another CSR), or **external web**."

### 3a. Click a cross-document link

🖱 **Click path:** In the **AFTER** panel, click a highlighted cross-doc reference, e.g. *"Section 2.5 of CSR SP-2026-002"* (try a **Table** reference too, e.g. *"Table 14.2.1.1"*). A **Google-style destination popover** appears showing the target heading + an excerpt. Click **Open document →**.

> "Watch — I click the link and it shows me a **preview of where it lands**: the target
> document, the actual section heading, a snippet of the text there. Then it opens that
> document **and scrolls straight to the referenced section or table — and flashes it
> yellow** so you can see exactly where you landed. No hunting, no scrolling from the top.
> That's a genuine cross-document hyperlink between two separate study reports — exactly
> the kind a reviewer at the FDA would click."

💡  *"This is the difference between 'blue underlined text' and a link that
**actually resolves to the right place** — it doesn't just open the right document, it
lands you on the right line. The amber/red colours are the machine telling you where
it's not 100% sure — that's your human review list, pre-built."*

❓ **Likely question:** *"Does this work for table references, not just sections?"*
> **Answer:** *"Both. Section headings and table/figure captions are located the same way —
> by the human-readable reference text (e.g. 'Table 14.2.1.1'), so the jump-to-target lands
> on the exact caption, not the top of the file."*

### 3b. (Optional) The submission lifecycle

🖱 **Click path:** Point at the **Submission Lifecycle** stepper: **Linked → Compliance-approved → FDA-ready**. Click **Advance →** on the next available stage.

> "The same document carries through stages. Each stage keeps its own before/after, and
> when it advances it records *what changed and who changed it* — so you have a defensible
> trail from raw upload to FDA-ready package."

---

# SCENE 4 — Reports: the QC evidence 

Now switch from "look, it works" to "here's the auditable proof." First, point at the **Data source** bar.

🖱 **Click path:** At the top of any Reports screen, the **Run Selector** shows **● LIVE RUN** with your run selected (vs **📦 Demo data**). 

 *"Everything below now reflects the run we just did — or I can switch to the seeded demo dossier. Same screens either way."*

### 4a. Overview (sidebar: Reports → Overview)

> "The headline: a **readiness score in a circle**, a grade, and a verdict —
> **Submission Ready / Needs Review / Not Ready**. Then the counts: total links, OK,
> broken, suspicious, unverified. Below, the **top issues** and a sample of recent links.
> This is the one-glance health check a publishing lead wants."

### 4b. Module Matrix (Reports → Module Matrix)

> "Same links, organised the way **you** think — by **CTD module**: m1 Regional, m2
> Summaries, m3 Quality, m4 Nonclinical, m5 Clinical. Each row is colour-coded like a
> heatmap with a health bar, so a problem module jumps out. Our demo is all m5 today, but
> on a full dossier this is where you'd spot 'Module 3 has 2% broken' instantly."


### 4c. Link Inspector (Reports → Link Inspector)

🖱 **Click path:** Click the **Broken** and **Suspicious** filter chips; type a doc name in the filter; click the **Detected By** column header to sort.
> "Every link, filterable. By default it surfaces problems first — broken and suspicious.
> Each row shows source, link text, target, a **confidence bar**, and crucially **Detected
> By** — regex, NER, or the LLM. So when QA asks 'why is this a link?', the answer is right
> there. Export the whole thing to CSV or XLSX at the bottom."

### 4d. Issues (Reports → Issues)

> "The anomaly worklist: **blockers, warnings, info**. Blue-text-without-a-link, orphaned
> references, circular references, deprecated study IDs — each with a **suggested fix** and
> a confidence. You can **Mark as Fixed** or **Ignore**, and the progress bar tracks the
> cleanup. This is the to-do list that used to be a manual page-by-page hunt."

### 4e. Export (Reports → Export)

> "CSV for spreadsheet QC, XLSX with conditional formatting (red = broken), and a print
> view for sign-off. The CSV columns include `detected_by` and `confidence` — so the export
> itself is audit-grade, not just a link dump."

---

# SCENE 5 — Detection Trace: how the AI decided 

This is the trust-builder. A regulated SME will not accept "the AI did it" — show the breakdown.

🖱 **Click path:** Sidebar **Analysis → Detection Trace**.

> "This answers the question every auditor asks: *how* did the machine find each link?
> **🟦 Regex** — deterministic pattern match, the bulk of them. **🟩 NER** — an NLP model
> caught a reference the patterns missed. **🟪 Ollama** — the **local** language model was
> brought in only when regex and NER weren't confident enough, to disambiguate. **🟧 Mixed**
> — multiple layers agreed. You get a per-document table and an overall split."

 Three points that land hard with regulatory:
> 1. *"The AI is the **last resort**, not the first — most links are deterministic regex."*
> 2. *"Every LLM decision is **logged with its reasoning** — fully traceable for GxP."*
> 3. *"That language model runs **here, on this box** — Ollama, local. No document text ever goes to a cloud API. That's what makes it 21 CFR Part 11-defensible."*

❓ **Likely question:** *"Can the AI hallucinate a wrong link?"*
> **Answer:** *"It only runs on low-confidence cases, it must clear a confidence threshold,
> and every one is flagged for human review and logged. The regex/NER layers are
> deterministic. Worst case it's surfaced amber for you to check — it can't silently ship
> a guess."*

---

# SCENE 6 — Review Queue: human-in-the-loop 


🖱 **Click path:** On the Pipeline results, click **→ Send to Review Queue** (or sidebar **AI Pipeline → Review Queue**; note the red **pending** badge).

> "The machine never auto-submits. Completed runs land here, in front of a **compliance
> officer** — a person. You see the score, grade, broken count, and the linked files. You
> **Approve**, or **Reject with a required reason** that sends it back for reprocessing.
> Nothing moves forward without a human signing off."

>"This is the control point your SOPs require. The engine does the
>650-hour grind; the human keeps the judgment and the accountability."*

🖱 **Click path:** Click **✓ Approve** on the run → then **→ Compliance Gate**.

---

# SCENE 7 — Compliance Gate: eCTD check → submit 

The finish line — turn an approved run into a submittable package.

🖱 **Click path:** The run ID is pre-filled. Click **🔬 Run Compliance Check**.

> "Now we check the package against **eCTD v4.0** readiness — backbone present, naming
> conventions, cross-reference integrity, bookmarks, hyperlink colour rules. Each item is
> **pass / warning / fail** with detail. Green banner means ready."

🖱 **Click path:** When all-pass, the **Submit to Regulatory Authority** card appears. Pick an authority — **🇺🇸 FDA CDER (ESG)**, **🇪🇺 EMA (EUDRALINK)**, **🇯🇵 PMDA**, or **🇨🇦 Health Canada** — and click **📤 Submit**.

> "One package, multiple destination authorities, each with its own rules. I submit, and we
> get an **electronic receipt number** — and note the line: *'this action is audit-logged
> and cannot be undone.'* That receipt and the whole journey are now in the immutable
> trail."

💡 *"From a folder of Word files to an FDA-ready, receipted submission —
with every machine and human decision recorded — in minutes, not weeks."*

>the POC the submit step **generates a receipt
> and audit record** — it simulates the gateway handoff. Live FDA ESG / EMA gateway
> integration is Phase 4. Don't imply it's wired to the real FDA today.

---

# SCENE 8 — Close: why this is safe to adopt 

> "Three things to take away:
> 1. **It's accurate and transparent** — most links are deterministic, the AI is a logged
>    last resort, and every link shows its confidence and how it was found.
> 2. **It's compliant by construction** — fully on-prem, no external calls, originals never
>    mutated, an append-only audit trail, and a mandatory human approval gate.
> 3. **It's fast** — the manual 150–300 hours per dossier becomes a few minutes of compute
>    plus your review.
>
> The working POC. The roadmap adds the live submission gateways,
> Dossplorer integration, and formal GxP qualification."



---

# Appendix A — Anticipated questions (cheat sheet)

| They ask… | You answer… |
|---|---|
| "Does our document content go to the cloud / ChatGPT?" | **No.** All AI (LLM + embeddings) runs locally via Ollama on this machine. The On-Prem badge = zero external calls for content. |
| "Will it corrupt Dosscriber styling?" | The injector preserves run-level styling and only touches the link runs; it diff-checks afterward and refuses to write if styling outside the link mutated. |
| "What if the AI is wrong?" | LLM is last-resort, confidence-gated, logged with reasoning, and anything uncertain is flagged amber for human review — never auto-submitted. |
| "Can I prove to an auditor what happened?" | Append-only `audit.jsonl` per dossier: timestamps, before/after hashes, links added, who approved, submission receipt. |
| "What formats?" | Word `.docx` and PDF today; eCTD `index.xml` backbone aware; cross-module/leaf references. |
| "What if Neo4j / Redis / the LLM is down?" | Graceful degradation — in-memory graph fallback, tasks run in-process, regex/NER still detect. A basic run needs none of them. |
| "Is the score auditable or a black box?" | It's a weighted formula (broken links, orphans, anomalies) — documented and configurable, not a vibe. |
| "Multiple regions?" | Compliance Gate already targets FDA / EMA / PMDA / Health Canada; regional eCTD variants are handled in the backbone layer. |

---

# Appendix B — Under the hood 

The engine is a **six-layer pipeline** (all local Python):

1. **Ingestion** — load `.docx` / PDF / eCTD XML / dossier metadata (never mutate originals).
2. **Parsing** — extract paragraphs, runs, styling, and exact location anchors.
3. **Detection** — **17 regex patterns (incl. document-type DOC_REF) → spaCy NER → local Ollama LLM** (only on low-confidence/conflict).
4. **Injection** — write real Word/PDF hyperlinks + bookmarks; preserve styling; emit `*_linked` copies.
5. **Validation** — existence, target-correctness, anomalies (blue-text-no-link, orphans, cycles, deprecated IDs).
6. **Reporting & Dashboard** — readiness score + grade, CSV/XLSX, and this React UI.

Cross-cutting: an **eCTD graph** (NetworkX in-memory, persisted to **Neo4j**) resolves
"which document does this reference point to," and an **append-only audit log** records
every action. Orchestrated by a LangGraph state machine (the 9 nodes you watched stream).

---

# Appendix C — Screen ↔ sidebar map 

```
AI Pipeline                 Reports                 Analysis
─────────────               ───────────             ──────────────
Run Pipeline   (Scene 2)    Overview     (4a)       Comparison    (canned/fallback)
Run Compare    (Scene 3)    Module Matrix(4b)       Detection Trace (Scene 5)
Review Queue   (Scene 6)    Link Inspector(4c)
Compliance Gate(Scene 7)    Issues       (4d)
                            Export       (4e)
```

> **Comparison** (Analysis group) is a *static, canned* before/after kept as a no-run
> fallback. The **Run Compare** screen (AI Pipeline group)
---


