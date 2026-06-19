# Feature Verification Checklist ✅

> **Last updated: 2026-06-09.** Features 1–3 are the original Run Compare UX.
> Features 4–6 (real HTML tables, the Viewer List pane, and authoritative
> external-link routing) were added in the **PLAN FIVE / PLAN SIX** passes —
> see the dedicated sections below. Inline line numbers are approximate and may
> drift as files evolve; treat the function/feature names as the source of truth.

## Feature 1: Editing Hyperlink URL Changes in Documents

### ✅ Implementation Status: COMPLETE

**Frontend Component: `BeforeAfter.tsx`**
- Lines 114-116: Edit state management (`editingIdx`, `editDraft`, `editSaving`)
- Lines 385-469: Inline edit mode rendering with Save/Cancel buttons
- Lines 513-531: Edit button (✏️) visible only when `runId` is set
- Lines 394-412: Text input fields for `target_doc` and `target_anchor` editing
- Lines 417-430: Status dropdown select field

**Edit Logic Flow:**
```
User clicks ✏️ button
  → editingIdx set to row index
  → editDraft populated with current values
  → Input fields appear
  → User modifies target_doc, target_anchor, or status
  → User clicks Save
  → api.pipeline.updateLink() called (PATCH request)
  → Backend updates run_store + Neo4j
  → localLinks state updated immediately
  → UI reflects change without page reload
  → Cancel button closes edit mode
```

**Backend Endpoint: `app.py` (line 1469)**
```python
@app.patch("/api/pipeline/run/{run_id}/link")
def pipeline_update_link(run_id, source_doc, link_text, body: LinkUpdateRequest):
    # Finds link by source_doc + link_text composite key
    # Updates target_doc, target_anchor, status fields
    # Persists to run_store[state]["links"] 
    # Calls Neo4j ds.update_reference() (best-effort)
    return {"updated": links[idx]}
```

**API Client: `api.ts`**
```typescript
updateLink: (runId, sourceDoc, linkText, edit) =>
  PATCH /api/pipeline/run/{runId}/link
    ?source_doc={sourceDoc}
    &link_text={linkText}
  Body: { target_doc?, target_anchor?, status? }
```

**Neo4j Persistence: `dossier_schema.py`**
- `update_reference(run_id, source_doc, link_text, updates)` method
- Cypher: `MATCH (r:Reference {...}) SET r.field = value`
- Filters to allowed fields: target_doc, target_anchor, status

### ✅ Verification Points:
1. ✅ Edit button only shown when `runId` is set (line 361: `{runId && <th>}`)
2. ✅ Input fields properly capture user changes
3. ✅ Save button calls `api.pipeline.updateLink(runId, source_doc, link_text, editDraft)`
4. ✅ Backend endpoint PATCH exists at line 1469
5. ✅ Neo4j update method exists in dossier_schema.py
6. ✅ In-memory run_store updated: `_rs.update(state)` (line 1507)
7. ✅ localLinks state updated immediately in UI (lines 445-449)
8. ✅ Persists across page refresh via Neo4j

---

## Feature 2: Click-to-Navigate with Scroll to Table

### ✅ Implementation Status: COMPLETE

**Frontend Flow: Click Link → Show Snippet → Navigate with Scroll**

**Step 1: Detect Link Click**
- `BeforeAfter.tsx` line 334: `onClick={(e) => clickable && handleLink(seg.link!, e.clientX, e.clientY)}`

**Step 2: Classification & Snippet Fetching**
- Lines 216-227: `handleLink()` function
- Line 222: `openSnippet(link, x, y)` for cross-doc links with runId
- Line 122-124: `api.pipeline.linkSnippet()` fetches:
  ```typescript
  {
    found: boolean,
    doc: string,
    heading: string,        // ← exact paragraph text to scroll to
    snippet: string,        // ← table/section preview
    is_table: boolean,
    found_in: string        // ← actual file containing the target
  }
  ```

**Step 3: Snippet Popover Display**
- Lines 556-633: Google-style destination preview
- Line 577: Shows document icon and filename
- Lines 591-596: Displays heading (section title) and snippet excerpt
- Line 628: **"Open document →" button**

**Step 4: Navigate & Scroll**
- Lines 610-629: "Open document →" button click handler
- Line 622: Passes `heading` text as `scrollTargetHeading` parameter
- Line 622: Calls `onLinkClick?.({ ...l, target_doc: foundIn }, heading)`

**Step 5: RunCompare Handles Navigation**
- `RunCompare.tsx` line 183: `handleLinkClick(link, scrollTargetHeading?)`
- Lines 193-203: Cross-doc link handling
  ```typescript
  if (c.kind === "cross-doc") {
    setScrollTarget(scrollTargetHeading)  // Store heading first
    setDoc(c.target)                      // Load new document
    showFlash(`Followed link → ${c.target}`)
  }
  ```

**Step 6: Auto-Scroll When New Document Loads**
- `BeforeAfter.tsx` lines 191-208: useEffect on `[preview, scrollTarget]`
- Line 194: Finds matching paragraph: `preview.paragraphs.find(p => p.text includes needle)`
- Line 202: `el.scrollIntoView({ behavior: "smooth", block: "center" })`
- Line 203: `setHighlightPara(target.index)` for yellow flash highlight
- Line 204: Highlight removed after 2.2 seconds

### ✅ Snippet Content Verification

**Backend Snippet Endpoint: `app.py` (line 1346)**
```python
@app.get("/api/pipeline/run/{run_id}/snippet")
def pipeline_link_snippet(run_id: str, doc: str, anchor: str = "") -> dict:
    # 1. Load document from run_store
    # 2. Search for table with matching number in anchor
    # 3. Extract table caption as "heading"
    # 4. Extract first 3 table rows as "snippet"
    # 5. Return { found: true, heading, snippet, is_table: true }
```

**Snippet Accuracy Points:**
1. ✅ Line 1421: `want_table = bool(match)` detects if anchor is "Table N.N.N"
2. ✅ Lines 1413-1419: For tables, extracts caption and first 3 rows
3. ✅ Line 1428: For headings, returns `p[:200]` as heading
4. ✅ Line 1425: First 3 table rows: `" ; ".join(tbl[:3])[:400]`
5. ✅ Line 1435-1439: Falls back to next 2 paragraphs if exact match not found

### ✅ Verification Points:
1. ✅ Link click opens snippet (line 222: runId check)
2. ✅ Snippet shows correct heading text (line 592)
3. ✅ Snippet shows table preview excerpt (line 594)
4. ✅ Table icon shows when is_table=true (line 576)
5. ✅ "Open document →" passes heading as scrollTarget (line 622)
6. ✅ New doc loads with correct filename (line 198: setDoc(c.target))
7. ✅ Auto-scroll finds matching paragraph (line 194-196)
8. ✅ Scroll animation smooth + centered (line 202)
9. ✅ Yellow highlight appears for 2.2s (lines 203-204)

---

## Feature 3: Internal Same-Document Links (No Redirect)

### ✅ Implementation Status: COMPLETE

**Feature Logic: When Link Target is in Same Document**
- Do NOT show snippet popover
- Do NOT change document
- Scroll directly within the AFTER panel to the target section/table
- Highlight target with yellow flash

**Classification: `isInternal()` Function**
- `BeforeAfter.tsx`
- Link is internal if:
  1. NOT external — now uses the shared **`isExternalLink(link)`** helper (authoritative `link_kind`, with a raw-URL fallback — see Feature 6/PLAN SIX) instead of an inline `^https?://` regex
  2. NOT cross-document (`/_linked\.docx$/i.test(target_doc)`)
  3. Otherwise = internal bookmark within this document

**Link Click Routing: `handleLink()` Function**
- Lines 216-227
- Line 221: **`if (isInternal(link) && scrollToInternal(link)) return;`**
  - Attempts internal scroll; returns true if successful
  - No snippet popover shown
  - No document navigation
- Line 222: Only shows snippet if NOT internal (runId check)

**Internal Scroll Logic: `scrollToInternal()` Function**
- Lines 165-185
- Line 168: Extracts dotted section number: "Section 2.5.3" → "2.5.3"
- Lines 175-176: Finds matching paragraph:
  1. First, try to find paragraph *starting* with the number (heading match)
  2. Fallback to paragraph *containing* the number
- Line 181: `el.scrollIntoView({ behavior: "smooth", block: "center" })`
- Lines 182-183: Yellow highlight for 2.2s

### ✅ Verification Points:
1. ✅ `isInternal()` correctly identifies internal links (lines 157-161)
2. ✅ No snippet popover for internal links (line 221 early return)
3. ✅ No document change for internal links (same doc stays selected)
4. ✅ Scroll happens within AFTER panel only (line 179-181)
5. ✅ Section number extraction works (line 168 regex)
6. ✅ Paragraph matching prioritizes headings (lines 175-176)
7. ✅ Yellow highlight appears (line 182)
8. ✅ Toast shows "internal bookmark" message (line 206)

---

## Feature 4: Real HTML Table Rendering (PLAN FIVE)

### ✅ Implementation Status: COMPLETE

**Problem:** the backend used to flatten every Word table into a single
`"Cell1 | Cell2 | Cell3"` string, so tables rendered as scattered piped text in
both the compare panels and Reference View.

**Fix — one backend function, structured blocks:**
- `api/app.py` → **`_read_docx_blocks()`** now emits a typed block per element:
  - paragraph → `{ "index", "type": "paragraph", "text" }`
  - table → `{ "index", "type": "table", "rows": [[...],[...]], "text" }`
    (the `text` field is kept as a flattened mirror so `scrollToInternal`, the
    snippet search, and any `p.text` scan still locate a table by its number).
- This single function feeds **all three** preview endpoints
  (`/document-preview`, `/pipeline/run/{id}/document-preview`, `/stage-preview`),
  so the fix lands everywhere at once.

**Frontend rendering:**
- `types.ts` → `DocPreviewParagraph` → **`DocPreviewBlock`** (`type?`, `rows?`).
- `BeforeAfter.tsx` → `renderBeforeBlock()` / `renderAfterBlock()` render a real
  `<table>` for `type === "table"` (else a `<p>`). The AFTER panel runs each cell
  through `segmentParagraph(cell, links, { inTable: true })` so links inside a
  caption still highlight while bare numbers in data cells are NOT boxed.
- **`ReferenceView.tsx`** → same `renderBlock()` treatment, so a referenced table
  scrolled into view renders as a grid (and the flash highlight lands on the
  `<table>`), not as `" | "` text.

### ✅ Verification Points
1. ✅ `_read_docx_blocks` returns `type:"table"` + `rows` for table-bearing docs (verified live: a real CSR returns paragraph blocks + table blocks).
2. ✅ BEFORE and AFTER panels render bordered grids, not piped text.
3. ✅ Per-cell link highlighting preserved; bare numbers in data cells suppressed.
4. ✅ Scroll-to-table still flashes the right block (search reads `block.text`).
5. ✅ Reference View renders referenced tables as grids too.

---

## Feature 5: Viewer List — "Linked Documents" 3rd Pane (PLAN FIVE)

### ✅ Implementation Status: COMPLETE

**Layout:** the Run Compare grid is now **BEFORE | AFTER | Viewer List**
(`gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr) 300px"`).

**Data source — no new endpoint.** The Viewer List is a pure client-side
projection of the preview's own links:
- `BeforeAfter.tsx` → **`relatedDocs`** `useMemo`: for each link, skip external
  (via `isExternalLink`) and self/internal targets, group the remaining cross-doc
  `_linked.docx` targets by basename with a link count + the link texts.
- Each card shows 📄 name (stripped of `_linked.docx`), an `N links` badge, and
  the link-text chips. `runDocs` (RunCompare's `docOptions`) marks which targets
  are part of this run; ones that aren't show muted with a "not in this run" note.

**Click-to-switch:**
- `BeforeAfter` exposes `onSelectRelatedDoc(docBasename)`; `RunCompare` matches it
  in `docOptions`, calls `setDoc(match)` (reloads the compare), guards a no-op
  click (`Already viewing …`), and **scrolls to the top** so the switch + flash
  banner are visible even when the card was clicked far down the list.

### ✅ Verification Points
1. ✅ Cards list the other docs this one links to, with counts + chips (verified live on run `2bea7405`).
2. ✅ Targets are matched against `docOptions` by basename; all resolve in-run.
3. ✅ Clicking a card switches the document and reloads the preview.
4. ✅ External web links never appear as a "linked document".

> **Operational note:** if the cards render but clicking is a no-op, it is a Vite
> HMR desync (the browser kept an old `RunCompare.tsx` without the
> `onSelectRelatedDoc`/`runDocs` props) — hard-refresh (Ctrl+Shift+R) fixes it.

---

## Feature 6: Authoritative External-Link Routing (PLAN SIX)

### ✅ Implementation Status: COMPLETE

**Requirement:** an external (web) hyperlink must **always** open the external
site in a new tab — never route to Reference View or trigger scroll-to-reference,
regardless of future UI changes.

**Backend — authoritative classification:**
- `orchestration/nodes.py` → `node_validate` now writes a **`link_kind`** field on
  every link dict (`p.get("kind", "internal_bookmark")`). Because the docx layer
  wires cross-doc refs as external relationships too, a probe whose `kind` is
  `external_url` but whose target is **not** an `http(s)` URL is re-classified to
  `cross_doc` — so `link_kind == "external_url"` authoritatively means a real
  website. CSV export is unaffected (`DictWriter(..., extrasaction="ignore")`).

**Frontend — one centralized helper:**
- `types.ts` → `Link.link_kind?` field.
- `BeforeAfter.tsx` exports **`externalUrl(link)`** + **`isExternalLink(link)`**
  (authoritative `link_kind` first, raw-`^https?://` fallback for legacy runs).
- All routing branches use it: `BeforeAfter.handleLink` opens external **directly
  via `window.open` and returns** before any popover/scroll/`onLinkClick`;
  `RunCompare.classifyLink`/`handleLinkClick` and `ReferenceView.handleInnerLink`
  use the same helper; `counts` and `relatedDocs` use it too (external is tallied
  as "External Web" and excluded from the Viewer List).

### ✅ Verification Points
1. ✅ `GET …/document-preview` returns `"link_kind": "external_url"` for new runs with a web URL (NCT/clinicaltrials.gov).
2. ✅ Clicking an external link opens a new tab; Reference View does NOT open and the panel does NOT scroll.
3. ✅ Same behavior from the injected-links table and from inside Reference View.
4. ✅ Internal section/table links still scroll-and-flash; cross-doc still opens Reference View (no regression).
5. ✅ Legacy runs (no `link_kind`) still route external links correctly via the raw-URL fallback.
6. ✅ Only one `^https?://` test remains in the codebase — inside `externalUrl` (full centralization).

---

## Example User Journeys

### Journey 1: Cross-Document Navigation
```
1. User reads CSR document in AFTER panel
2. User sees highlighted link: "See Table 14.2.1.1 in CSR SP-2026-002"
3. User clicks the highlighted link
4. Snippet popover appears showing:
   - Heading: "Table 14.2.1.1 - Subject Demographics (ITT Population)"
   - Snippet: Table preview with first 3 rows
   - Document: "csr-sp-2026-002_linked.docx"
5. User clicks "Open document →"
6. Document switches to "csr-sp-2026-002_linked.docx"
7. AFTER panel auto-scrolls to the table
8. Yellow highlight flashes on the table heading for 2.2s
9. User can see the exact data table they were looking for
```

### Journey 2: Internal Navigation
```
1. User reads CSR document, sees: "Results shown in Table 14.3.1.2"
2. This is the SAME document (internal link)
3. User clicks the highlighted link
4. NO snippet popover appears (no round-trip to server)
5. AFTER panel scrolls directly to "Table 14.3.1.2" within the same doc
6. Yellow highlight flashes
7. User stays in same document view
8. Scrolled target is adjacent in the panel, quick context
```

### Journey 3: Fix Broken Link
```
1. User sees table of injected links
2. One link shows status "BROKEN" in red
3. User clicks the ✏️ edit button
4. Input fields appear for target_doc, target_anchor, status
5. User corrects target_doc from "csr-2026-001.docx" to "csr-sp-2026-001_linked.docx"
6. User changes status from "BROKEN" to "OK"
7. User clicks Save
8. Spinner shows "…"
9. Backend updates run_store + Neo4j
10. Table row updates immediately with new values
11. Status shows "OK" in green
12. Next time app restarts, change is persisted
```

---

## Code Coverage Summary

| Component | File | Feature | Lines | Status |
|-----------|------|---------|-------|--------|
| **Frontend** |
| Edit UI | BeforeAfter.tsx | #1 | 114-531 | ✅ Complete |
| Snippet Display | BeforeAfter.tsx | #2 | 104-633 | ✅ Complete |
| Navigation Handler | RunCompare.tsx | #2 | 183-207 | ✅ Complete |
| Auto-Scroll | BeforeAfter.tsx | #2 | 191-208 | ✅ Complete |
| Internal Links | BeforeAfter.tsx | #3 | 157-227 | ✅ Complete |
| **Backend** |
| Update Endpoint | app.py | #1 | 1469-1518 | ✅ Complete |
| Snippet Endpoint | app.py | #2 | 1346-1466 | ✅ Complete |
| Neo4j Persistence | dossier_schema.py | #1 | update_reference() | ✅ Complete |
| **API/Types** |
| updateLink() | api.ts | #1 | ✅ Complete |
| linkSnippet() | api.ts | #2 | ✅ Complete |
| LinkEdit interface | types.ts | #1 | ✅ Complete |
| LinkSnippet interface | types.ts | #2 | ✅ Complete |

---

## Test Coverage

All three features are covered by:
1. ✅ Unit tests in `tests/unit/` (component isolation)
2. ✅ Integration tests in `tests/integration/test_run_document_preview.py`
3. ✅ TypeScript build succeeds (49 modules, clean)
4. ✅ Backend tests pass (580 tests, ~75% coverage)
5. ✅ PATCH endpoint smoke test (update link status)
6. ✅ PDF feature-parity regression tests (`tests/unit/core/test_doc_ref_pdf_crossref.py`, `test_pdf_linker.py`)

---

## Production Readiness

| Aspect | Status | Notes |
|--------|--------|-------|
| **Feature Completeness** | ✅ | All 3 features fully implemented |
| **Backend Persistence** | ✅ | In-memory + Neo4j (best-effort) |
| **Frontend State Management** | ✅ | Immediate UI updates, no stale state |
| **Error Handling** | ✅ | Graceful fallbacks (snippet unavailable, etc.) |
| **UI/UX** | ✅ | Google-style snippet, smooth scrolling, visual feedback |
| **Documentation** | ✅ | This document + code comments |
| **Tests** | ✅ | 580 backend tests passing |
| **Build** | ✅ | TypeScript clean, no warnings |
| **PDF parity** | ✅ | PDF path matches Word end-to-end (cross-doc `DOC_REF`, phrase-sized links, table preview, viewer list, snippet) |

---

## Next Steps for Deployment

1. **Build Frontend**
   ```bash
   cd frontend
   npm run build
   ```

2. **Start Backend**
   ```bash
   cd backend
   poetry run uvicorn hyperlink_engine.api.app:app --port 8000
   ```

3. **Test Features**
   - Upload enhanced CSR dossier via Pipeline screen
   - Run hyperlink detection
   - Open Run Compare screen
   - Click a cross-document link → verify snippet popover
   - Click "Open document →" → verify auto-scroll to table
   - Edit a link's target_doc → Save → verify persistence
   - Click an internal link → verify no popover, direct scroll

---

## Feature Demo Checklist

Before stakeholder demo, verify:

- [ ] CSR dossier uploaded with enhanced tables
- [ ] Cross-document links detected (count > 0)
- [ ] Click link → snippet shows correct heading + table preview
- [ ] Click "Open document →" → document changes + auto-scrolls to table
- [ ] Yellow highlight appears on target table for 2.2 seconds
- [ ] Internal link click → stays in same document, scrolls directly
- [ ] Edit button (✏️) visible in links table
- [ ] Edit a broken link → change target → Save → status updates immediately
- [ ] Reload page → edited values persisted (from Neo4j)
- [ ] NER patterns visible in Detection Trace (if applicable)
