# Complete Application Architecture & Data Flow

> **Auth layer (PLAN SEVEN, 2026-06):** when `HYPERLINK_AUTH_ENABLED=true`, every
> request in the flows below first passes the SuperTokens ASGI middleware
> (`/api/auth/*` signin/signout/refresh) and the global `auth_guard` dependency
> (session cookie → `Principal`, else 401); run-scoped endpoints additionally
> enforce the classified-document gate (403 for non-cleared users). The
> SuperTokens core (:3567) + its Postgres run as two extra Docker containers.
> Diagrams below show the auth-OFF (default) path; full auth sequence diagrams
> live in `docs/auth-supertokens.md`.

## System Architecture Overview

```mermaid
graph TB
    subgraph Frontend["🖥️ FRONTEND (React/TypeScript)"]
        App["App.tsx<br/>Main Shell"]
        Pipeline["Pipeline.tsx<br/>Upload & Process"]
        RunCompare["RunCompare.tsx<br/>Click Handler<br/>Doc Navigation"]
        BeforeAfter["BeforeAfter.tsx<br/>Link Highlighting + Real Tables<br/>Edit UI · Snippet Popover<br/>Viewer List (Linked Docs)<br/>externalUrl/isExternalLink helper"]
        APIClient["api.ts<br/>API Client"]
    end

    subgraph Backend["⚙️ BACKEND (FastAPI/Python)"]
        FastAPI["FastAPI App<br/>app.py"]
        RunEndpoints["GET /run/{id}/link/snippet<br/>PATCH /run/{id}/link<br/>GET /run/{id}/stages"]
        PipelineOrch["Orchestration<br/>LangGraph State"]
        Detection["Detection Layer<br/>Regex + NER + LLM"]
        Injection["Injection Layer<br/>docx_linker<br/>pdf_linker"]
        RunStore["Run Store<br/>In-Memory State"]
    end

    subgraph Graph["📊 NEO4J DATABASE"]
        DossierNode["Dossier Node<br/>dossier_id<br/>sponsor<br/>status"]
        DocNode["Document Node<br/>doc_id<br/>filename<br/>sha256"]
        RefNode["Reference Node<br/>text<br/>confidence<br/>source_layer"]
        LeafNode["Leaf Node<br/>leaf_id<br/>module<br/>path"]
        
        DossierHas["HAS_DOCUMENT<br/>edge"]
        DocPublished["PUBLISHED_AS<br/>edge"]
        RefDetected["DETECTED_IN<br/>edge"]
        RefResolves["RESOLVES_TO<br/>edge"]
        DocLinks["LINKS_TO<br/>edge"]
    end

    subgraph FileSystem["📁 FILE SYSTEM"]
        InputFiles["input/run-id/<br/>original.docx"]
        OutputFiles["output/run-id/linked/<br/>original_linked.docx"]
    end

    %% Frontend connections
    App --> Pipeline
    App --> RunCompare
    Pipeline --> APIClient
    RunCompare --> BeforeAfter
    BeforeAfter --> APIClient

    %% Frontend to Backend
    APIClient -->|HTTP Requests| FastAPI

    %% Backend routing
    FastAPI --> RunEndpoints
    FastAPI --> PipelineOrch
    
    %% Backend services
    RunEndpoints --> RunStore
    PipelineOrch --> Detection
    Detection --> Injection
    Injection --> RunStore

    %% Neo4j persistence
    RunStore -->|update_reference()| RefNode
    PipelineOrch -->|persist_to_neo4j()| DossierNode
    DossierNode -->|HAS_DOCUMENT| DocNode
    DocNode -->|PUBLISHED_AS| LeafNode
    DocNode -->|DETECTED_IN| RefNode
    RefNode -->|RESOLVES_TO| DocNode
    RefNode -->|RESOLVES_TO| LeafNode
    DocNode -->|LINKS_TO| DocNode

    %% File I/O
    InputFiles -->|parse| PipelineOrch
    PipelineOrch -->|inject links| OutputFiles
    Injection -->|writes| OutputFiles

    style Frontend fill:#e3f2fd
    style Backend fill:#f3e5f5
    style Graph fill:#e8f5e9
    style FileSystem fill:#fff3e0
```

---

## Feature 1: Editing Hyperlinks (Full Request/Response Cycle)

```mermaid
sequenceDiagram
    actor User
    participant BeforeAfter as BeforeAfter.tsx
    participant RunCompare as RunCompare.tsx
    participant APIClient as api.ts
    participant Backend as FastAPI
    participant RunStore as run_store
    participant Neo4j as Neo4j DB

    User->>BeforeAfter: Click ✏️ button on link row
    BeforeAfter->>BeforeAfter: setEditingIdx(i)<br/>Show input fields
    
    User->>BeforeAfter: Edit target_doc field
    BeforeAfter->>BeforeAfter: setEditDraft({target_doc: newValue})
    
    User->>BeforeAfter: Click Save button
    BeforeAfter->>APIClient: updateLink(runId, sourceDoc, linkText, editDraft)
    
    APIClient->>Backend: PATCH /api/pipeline/run/{runId}/link<br/>?source_doc={sourceDoc}<br/>?link_text={linkText}<br/>Body: {target_doc: newValue}
    
    Backend->>RunStore: get(runId)
    RunStore-->>Backend: state = {..., links: [...]}
    
    Backend->>Backend: Find link by source_doc+link_text
    Backend->>Backend: links[idx].update(target_doc)
    
    Backend->>RunStore: update(state)
    RunStore->>RunStore: state["links"] = modified_links
    
    Backend->>Neo4j: ds.update_reference(runId, sourceDoc, linkText, {target_doc})
    Neo4j->>Neo4j: MATCH (r:Reference {...})<br/>SET r.target_doc = newValue
    Neo4j-->>Backend: ✓ Updated
    
    Backend-->>APIClient: {updated: {target_doc, target_anchor, status, ...}}
    
    APIClient-->>BeforeAfter: Response received
    BeforeAfter->>BeforeAfter: setLocalLinks([...new_links])
    BeforeAfter->>BeforeAfter: setEditingIdx(null)
    
    BeforeAfter-->>User: Link table row updates immediately<br/>Status shows "OK" or "BROKEN"

    Note over User,Neo4j: Edit persists across page reload via Neo4j
```

---

## Feature 2: Click-to-Navigate with Auto-Scroll (Full Flow)

```mermaid
sequenceDiagram
    actor User
    participant BeforeAfter as BeforeAfter.tsx
    participant Popover as Snippet Popover
    participant RunCompare as RunCompare.tsx
    participant APIClient as api.ts
    participant Backend as FastAPI<br/>Snippet Endpoint
    participant RunStore as run_store

    rect rgb(200, 220, 255)
        Note over User,RunStore: PHASE 1: LINK CLICK & SNIPPET FETCH
    end

    User->>BeforeAfter: Click highlighted link<br/>in AFTER panel
    BeforeAfter->>BeforeAfter: handleLink(link, x, y)
    
    alt isInternal(link) = true
        Note over BeforeAfter: → Go to Feature 3 (Internal Link)
    else isInternal(link) = false
        alt runId is set
            BeforeAfter->>BeforeAfter: openSnippet(link, x, y)
            BeforeAfter->>APIClient: api.pipeline.linkSnippet(runId, target_doc, anchor)
            
            APIClient->>Backend: GET /api/pipeline/run/{runId}/snippet<br/>?doc={target_doc}&anchor={anchor}
            Backend->>RunStore: Get run state
            Backend->>Backend: Load document from state
            Backend->>Backend: Search for table/section<br/>matching anchor
            Backend->>Backend: Extract heading text<br/>and first 3 table rows
            Backend-->>APIClient: {found: true,<br/>heading: "Table 14.2.1.1 - Demographics",<br/>snippet: "Row1;Row2;Row3",<br/>is_table: true,<br/>found_in: "csr-sp-2026-002_linked.docx"}
            
            APIClient-->>BeforeAfter: Snippet data received
            BeforeAfter->>Popover: Display popover with heading & snippet
            Popover-->>User: Show Google-style preview<br/>"Open document →" button visible
        end
    end

    rect rgb(200, 255, 200)
        Note over User,RunCompare: PHASE 2: NAVIGATION & SCROLL
    end

    User->>Popover: Click "Open document →"
    Popover->>Popover: const heading = snippet.data.heading
    Popover->>RunCompare: onLinkClick(link, heading)
    
    RunCompare->>RunCompare: handleLinkClick(link, scrollTargetHeading)
    RunCompare->>RunCompare: const c = classifyLink(link)
    
    alt c.kind = "cross-doc"
        RunCompare->>RunCompare: setScrollTarget(scrollTargetHeading)
        RunCompare->>RunCompare: setDoc(c.target)
        RunCompare-->>User: ✓ Flash: "Followed link → csr-sp-2026-002_linked.docx"
        
        Note over RunCompare: State changes trigger useEffect
        RunCompare->>APIClient: api.pipeline.stagePreview(runId, doc, stage)
        APIClient->>Backend: GET /api/pipeline/run/{runId}/preview?doc=...
        Backend-->>APIClient: {paragraphs: [...], links: [...], ...}
        APIClient-->>RunCompare: preview loaded
        
        RunCompare->>BeforeAfter: Pass preview + scrollTarget as props
    end

    rect rgb(255, 255, 200)
        Note over BeforeAfter: PHASE 3: AUTO-SCROLL AFTER RENDER
    end

    BeforeAfter->>BeforeAfter: useEffect on [preview, scrollTarget]
    BeforeAfter->>BeforeAfter: needle = scrollTarget.slice(0, 60)
    BeforeAfter->>BeforeAfter: target = paragraphs.find(p => p.text includes needle)
    
    BeforeAfter->>BeforeAfter: setTimeout(150ms) {<br/>  el = afterRefs.current[target.index]<br/>  el.scrollIntoView(smooth, center)<br/>  setHighlightPara(target.index)<br/>  setTimeout(2200ms) { setHighlightPara(null) }
    BeforeAfter-->>User: Document scrolls smoothly<br/>to the table heading<br/>Yellow highlight flashes<br/>for 2.2 seconds

    Note over User: User can now see<br/>the exact table they clicked on!
```

---

## Feature 3: Internal Same-Document Links (No Redirect)

```mermaid
sequenceDiagram
    actor User
    participant BeforeAfter as BeforeAfter.tsx
    participant LS as Local State
    participant Refs as afterRefs

    User->>BeforeAfter: Click link: "Table 14.3.1.2"
    BeforeAfter->>BeforeAfter: handleLink(link)
    
    BeforeAfter->>BeforeAfter: const isInt = isInternal(link)
    
    alt Link is internal
        Note over BeforeAfter: target_anchor contains NO URL<br/>AND target_doc is NOT _linked.docx
        
        BeforeAfter->>BeforeAfter: scrollToInternal(link)
        
        alt scrollToInternal returns true
            BeforeAfter->>BeforeAfter: Extract number from link_text<br/>"Table 14.3.1.2" → "14.3.1.2"
            
            BeforeAfter->>BeforeAfter: Find paragraph by number:<br/>1. Try para.text.startsWith(num)<br/>2. Fallback to para.text.includes(num)
            
            BeforeAfter->>Refs: const el = afterRefs.current[target.index]
            
            BeforeAfter->>BeforeAfter: el.scrollIntoView({<br/>  behavior: "smooth",<br/>  block: "center"<br/>})
            
            BeforeAfter->>LS: setHighlightPara(target.index)
            LS->>LS: Yellow background applied<br/>to paragraph
            
            BeforeAfter->>BeforeAfter: setTimeout(2200ms) {<br/>  setHighlightPara(null)<br/>}
            LS->>LS: Yellow background fades
            
            BeforeAfter-->>User: ✓ Scroll within AFTER panel<br/>No document change<br/>No server call<br/>Instant response
        else scrollToInternal returns false
            BeforeAfter-->>User: ⚠️ Section not found<br/>in current document
        end
    else Link is cross-document or external
        Note over BeforeAfter: → Go to Feature 2 or 1
    end
```

---

## Data Flow: From Detection to Neo4j

```mermaid
graph TD
    A["📄 Input Document<br/>original.docx"] -->|Parse| B["Paragraphs & Text<br/>DocPreview Model"]
    
    B -->|Detect References| C["Regex Engine<br/>confidence: 0.92-0.99"]
    B -->|Detect References| D["NER Layer<br/>confidence: 0.80"]
    B -->|Detect References| E["LLM Disambiguator<br/>Ollama Fallback"]
    
    C -->|Merge overlaps| F["Entity List<br/>Match objects"]
    D -->|Merge overlaps| F
    E -->|Merge overlaps| F
    
    F -->|Resolve targets| G["Link Objects<br/>{source_doc, link_text,<br/>target_doc, target_anchor,<br/>link_kind, confidence, source_layer}"]
    
    G -->|Inject| H["🔗 Inject Hyperlinks<br/>into .docx/.pdf"]
    
    H -->|Output| I["📄 output_linked.docx<br/>with clickable links"]
    
    G -->|Persist| J["🔄 Run Store<br/>state['links'] = [...]"]
    
    J -->|Extract| K["Neo4j Persistence<br/>ds.persist_to_neo4j"]
    
    K -->|Create Nodes| L["Dossier Node<br/>{dossier_id, sponsor, ...}"]
    K -->|Create Nodes| M["Document Node<br/>{doc_id, filename, sha256}"]
    K -->|Create Nodes| N["Reference Node<br/>{text, confidence,<br/>source_layer, ...}"]
    
    L -->|HAS_DOCUMENT| M
    M -->|DETECTED_IN| N
    N -->|RESOLVES_TO| M
    M -->|LINKS_TO| M
    
    G -->|Validate| O["Validation Layer<br/>existence_checker<br/>anomaly_detector"]
    
    O -->|Report| P["CSV/XLSX Reports<br/>validation_report.csv"]
    
    style A fill:#fff3e0
    style B fill:#fff3e0
    style C fill:#f3e5f5
    style D fill:#f3e5f5
    style E fill:#f3e5f5
    style F fill:#f3e5f5
    style G fill:#e3f2fd
    style H fill:#e3f2fd
    style I fill:#fff3e0
    style J fill:#fff3e0
    style K fill:#e8f5e9
    style L fill:#e8f5e9
    style M fill:#e8f5e9
    style N fill:#e8f5e9
    style O fill:#f3e5f5
    style P fill:#fff3e0
```

---

## Neo4j Query Examples

### Query 1: Show All Links in a Document

```cypher
MATCH (doc:Document {doc_id: "csr-sp-2026-001"})
       <-[:DETECTED_IN]-(ref:Reference)-[:RESOLVES_TO]->(target)
RETURN doc.filename, ref.text, ref.confidence, 
       labels(target), target.filename
ORDER BY ref.confidence DESC
```

### Query 2: Find Cross-Document Reference Chains

```cypher
MATCH (doc1:Document)-[l:LINKS_TO {count: gt(0)}]->(doc2:Document),
      (doc2:Document)-[l2:LINKS_TO {count: gt(0)}]->(doc3:Document)
RETURN doc1.filename, doc2.filename, doc3.filename
LIMIT 20
```

### Query 3: Update a Reference After Edit

```cypher
MATCH (r:Reference {
  run_id: "2026-01-15-14-32-45",
  source_doc: "csr-sp-2026-001",
  link_text: "Table 14.2.1.1"
})
SET r.target_anchor = "14.2.1.1_updated",
    r.target_doc = "csr-sp-2026-002_linked.docx"
RETURN r
```

### Query 4: View Dossier-Level Statistics

```cypher
MATCH (d:Dossier {dossier_id: "DOS-2026-DEMO"})
       -[:HAS_DOCUMENT]->(doc:Document)
       <-[:DETECTED_IN]-(ref:Reference)
RETURN d.dossier_id,
       COUNT(DISTINCT doc) as doc_count,
       COUNT(ref) as link_count,
       AVG(ref.confidence) as avg_confidence,
       COLLECT(DISTINCT ref.source_layer) as sources
```

---

## HTTP Request/Response Examples

### PATCH: Update Link

**Request:**
```http
PATCH /api/pipeline/run/2026-01-15-14-32-45/link?source_doc=csr-sp-2026-001&link_text=Table%2014.2.1.1
Content-Type: application/json

{
  "target_doc": "csr-sp-2026-002_linked.docx",
  "target_anchor": "14.2.1.1_demographics",
  "status": "ok"
}
```

**Response:**
```json
{
  "updated": {
    "source_doc": "csr-sp-2026-001",
    "link_text": "Table 14.2.1.1",
    "target_doc": "csr-sp-2026-002_linked.docx",
    "target_anchor": "14.2.1.1_demographics",
    "status": "ok",
    "confidence": 0.95,
    "source_layer": "regex"
  }
}
```

### GET: Link Snippet

**Request:**
```http
GET /api/pipeline/run/2026-01-15-14-32-45/snippet?doc=csr-sp-2026-002_linked.docx&anchor=Table%2014.2.1.1
```

**Response:**
```json
{
  "found": true,
  "doc": "csr-sp-2026-002_linked.docx",
  "found_in": "csr-sp-2026-002_linked.docx",
  "heading": "Table 14.2.1.1 - Subject Demographics (Intent-to-Treat Population)",
  "snippet": "Characteristic ; Solzumab 200 mg ; Solzumab 100 mg ; Placebo ; Total",
  "is_table": true,
  "matched": true
}
```

---

## State Management Flow

```mermaid
stateDiagram-v2
    [*] --> Idle: Page Load
    
    Idle --> ViewingRun: Select Run
    ViewingRun --> ViewingDoc: Select Document
    ViewingDoc --> PreviewLoaded: Preview Fetches
    
    PreviewLoaded --> ClickingLink: User Clicks Link
    
    ClickingLink --> ShowSnippet: Is Cross-Doc?
    ClickingLink --> ScrollInternal: Is Internal?
    ClickingLink --> OpenExternal: Is External? (externalUrl / link_kind)
    
    ShowSnippet --> WaitingForSnippet: Fetching...
    WaitingForSnippet --> SnippetDisplayed: Display Popover
    SnippetDisplayed --> Navigating: Click "Open document →"
    
    Navigating --> PreviewLoaded: Load target doc
    
    ScrollInternal --> HighlightFlash: Find para, scroll
    HighlightFlash --> HighlightFading: Wait 2.2s
    HighlightFading --> PreviewLoaded
    
    OpenExternal --> ExternalTab: Open in browser
    ExternalTab --> ViewingDoc
    
    ViewingDoc --> Editing: Click ✏️ button
    Editing --> EditMode: Show inputs
    EditMode --> Saving: Click Save
    Saving --> BackendPatch: Send PATCH
    BackendPatch --> UpdatedLocal: Update run_store
    UpdatedLocal --> UpdatedNeo4j: Persist Neo4j
    UpdatedNeo4j --> PreviewLoaded
    
    note right of ShowSnippet
        Calls GET /snippet endpoint
        Returns heading + table preview
    end note
    
    note right of BackendPatch
        PATCH /api/pipeline/run/{id}/link
        Updates: target_doc, anchor, status
    end note
    
    note right of UpdatedNeo4j
        Neo4j Reference node updated
        Survives page reload
    end note
```

---

## Component Hierarchy & Props Flow

```mermaid
graph TD
    A["App.tsx<br/>---<br/>activeRun: RunSummary<br/>selectedDoc: string"] --> B["Pipeline.tsx<br/>---<br/>onRunComplete: () => void"]
    A --> C["RunCompare.tsx<br/>---<br/>active: boolean<br/>initialRunId: string"]
    
    C --> D["BeforeAfter.tsx<br/>---<br/>preview: DocPreview<br/>runId: string<br/>scrollTarget: string<br/>onLinkClick: (link, heading?) => void"]
    
    C --> E["Stage Stepper<br/>---<br/>stages: RunStage[]<br/>currentStage: string"]
    
    B --> F["Upload Form<br/>---<br/>allowedExtensions: string[]"]
    
    D --> G["Stats Row<br/>---<br/>totalLinks: number<br/>internalCount: number"]
    
    D --> H["BEFORE Panel<br/>---<br/>paragraphs: Paragraph[]<br/>linkCount: number"]
    
    D --> I["AFTER Panel<br/>---<br/>paragraphs: Paragraph[]<br/>links: Link[]<br/>segmented: true"]
    
    D --> J["Links Table<br/>---<br/>localLinks: Link[]<br/>editingIdx: number<br/>editDraft: LinkEdit"]
    
    D --> K["Snippet Popover<br/>---<br/>snippet: LinkSnippet<br/>loading: boolean<br/>onOpen: () => void"]
    
    J --> L["Edit Inputs<br/>---<br/>target_doc: string<br/>target_anchor: string<br/>status: select"]
    
    K --> M["Heading Display<br/>---<br/>text: string<br/>icon: 📊/📄"]
    
    K --> N["Snippet Preview<br/>---<br/>excerpt: string<br/>firstRows: string"]
    
    K --> O["'Open document →'<br/>Button<br/>---<br/>onClick: handleNavigate"]
    
    style A fill:#e3f2fd
    style C fill:#e3f2fd
    style D fill:#e3f2fd
    style J fill:#f3e5f5
    style K fill:#f3e5f5
    style L fill:#fff3e0
    style O fill:#c8e6c9
```

---

## Deployment Architecture

```mermaid
graph TB
    subgraph Local["Local Development (docker-compose)"]
        FS["File System<br/>./output"]
        OL["Ollama<br/>:11434"]
        RE["Redis<br/>:6379"]
        NJ["Neo4j<br/>:7474/7687"]
    end
    
    subgraph Backend_Tier["Backend Tier (FastAPI)"]
        API["FastAPI App<br/>:8000"]
        Worker["Celery Worker<br/>Process links"]
    end
    
    subgraph Frontend_Tier["Frontend Tier (React)"]
        Dev["Dev Server<br/>:5174<br/>npm run dev"]
        Build["Build Output<br/>dist/"]
    end
    
    API -->|Read/Write| FS
    API -->|Call LLM| OL
    API -->|Cache/Queue| RE
    API -->|Persist| NJ
    Worker -->|Read/Write| FS
    Worker -->|Access| NJ
    
    Dev -->|Requests| API
    Build -->|Deployed to| API
    
    style Local fill:#fff3e0
    style Backend_Tier fill:#f3e5f5
    style Frontend_Tier fill:#e3f2fd
    style API fill:#c8e6c9
    style OL fill:#ffccbc
    style NJ fill:#c8e6c9
```

---

## Error Handling & Recovery

```mermaid
graph TD
    A["API Request"] --> B{Request Valid?}
    
    B -->|No| C["❌ Return 400/404<br/>with error message"]
    B -->|Yes| D["Process Request"]
    
    D --> E{Neo4j Available?}
    E -->|No| F["⚠️ Log warning<br/>Continue (best-effort)"]
    E -->|Yes| G["✅ Persist to Neo4j"]
    
    D --> H{Snippet Found?}
    H -->|No| I["Return snippet.found=false<br/>with fallback heading"]
    H -->|Yes| J["✅ Return full snippet"]
    
    D --> K{Edit Valid?}
    K -->|Invalid fields| L["❌ Return 400<br/>Field validation error"]
    K -->|Valid| M["Update run_store"]
    
    M --> N["Call Neo4j update"]
    N --> O{Update Success?}
    O -->|Failed| P["⚠️ Log error<br/>return edited_link anyway"]
    O -->|Success| Q["✅ Return updated link"]
    
    C --> R["❌ Show error toast<br/>in UI"]
    F --> S["⚠️ Show warning<br/>Data may be lost"]
    I --> T["⚠️ Show snippet<br/>heading unavailable"]
    L --> U["❌ Highlight invalid<br/>field in edit form"]
    P --> V["✅ Link updated locally<br/>⚠️ Neo4j sync failed"]
    Q --> W["✅ Link updated<br/>locally + persisted"]
    
    style A fill:#e3f2fd
    style C fill:#ffcdd2
    style F fill:#fff9c4
    style G fill:#c8e6c9
    style J fill:#c8e6c9
    style M fill:#c8e6c9
    style Q fill:#c8e6c9
    style W fill:#c8e6c9
```

---

## Timeline: Feature Demonstration Walkthrough

```mermaid
timeline
    title Feature Demo Timeline (5 minutes)
    
    section 0:00-1:00
        Upload: Use Pipeline screen
        Upload: Select enhanced CSR dossier
        Upload: Run hyperlink detection
        
    section 1:00-2:30
        : Open Run Compare
        : Select completed run
        : Select first CSR document
        Link Click: Click cross-document link in AFTER panel
        Snippet: Show Google-style snippet popover
        Snippet: Point out heading + table preview
        
    section 2:30-3:30
        Navigate: Click "Open document →"
        Scroll: Document changes + auto-scrolls to table
        Highlight: Yellow highlight flashes
        Check: Verify correct table is visible
        
    section 3:30-4:30
        Internal: Click internal link (same document)
        Instant: NO popover, NO server call
        Scroll: Direct scroll within AFTER panel
        
    section 4:30-5:00
        Edit: Click ✏️ button on broken link
        Edit: Show edit inputs + Save button
        Save: Change target_anchor → Save
        Result: Link updates immediately
        Persist: Reload page → values still changed (Neo4j)
```

---

## Features 4–6: Real Tables, Viewer List & Authoritative External Routing (PLAN FIVE / PLAN SIX)

### Feature 4 — Structured blocks → real HTML tables

```mermaid
graph LR
    A["original.docx"] -->|"_read_docx_blocks()"| B["Typed blocks<br/>paragraph: {index,type,text}<br/>table: {index,type,rows,text}"]
    B --> C["/document-preview<br/>/run/{id}/document-preview<br/>/stage-preview"]
    C --> D["DocPreviewBlock[]<br/>(types.ts)"]
    D --> E["BeforeAfter.renderBeforeBlock / renderAfterBlock<br/>ReferenceView.renderBlock"]
    E -->|"type==='table'"| F["real &lt;table&gt; grid<br/>cells → segmentParagraph(inTable:true)"]
    E -->|"else"| G["&lt;p&gt; paragraph"]
    style B fill:#e8f5e9
    style F fill:#e3f2fd
```

- One backend function (`_read_docx_blocks`) fixes all three preview panels.
- `text` is preserved on every block, so `scrollToInternal` / snippet search / any
  `p.text` scan still locate a table by its dotted number.

### Feature 5 — Viewer List (BEFORE | AFTER | Linked Documents)

```mermaid
sequenceDiagram
    actor User
    participant BA as BeforeAfter.tsx
    participant RC as RunCompare.tsx
    BA->>BA: relatedDocs = group cross-doc targets<br/>(skip external via isExternalLink, skip self/internal)
    BA-->>User: render 3rd pane "📎 Linked Documents"<br/>cards: 📄 name · N links · text chips
    User->>BA: click an available card
    BA->>RC: onSelectRelatedDoc(docBasename)
    RC->>RC: match in docOptions → setDoc(match)<br/>guard "Already viewing" · scrollTo(top)
    RC->>BA: new preview prop → compare reloads for target
```

- No new endpoint — the list is derived from the preview's own links.
- `runDocs` (= `docOptions`) marks targets not in this run as muted.

### Feature 6 — External links ALWAYS open externally (authoritative `link_kind`)

```mermaid
graph TD
    A["node_validate (backend)"] -->|"writes link_kind"| B{"kind == external_url<br/>AND target is http(s)?"}
    B -->|"yes"| C["link_kind = external_url<br/>(a real website)"]
    B -->|"no (docx-wired cross-doc)"| D["link_kind = cross_doc"]
    C --> E["externalUrl(link) → URL<br/>(BeforeAfter.tsx, shared)"]
    E --> F["window.open(url,_blank) and RETURN<br/>before any popover / scroll / onLinkClick"]
    D --> G["isExternalLink=false →<br/>Reference View / scroll-to-ref / Viewer List"]
    style C fill:#fff3e0
    style F fill:#c8e6c9
    style G fill:#e3f2fd
```

- `externalUrl` / `isExternalLink` are the **single source of truth**, imported by
  `RunCompare.classifyLink` / `handleLinkClick` and `ReferenceView.handleInnerLink`.
- Authoritative `link_kind` first; raw-`^https?://` fallback keeps **legacy runs**
  (created before the field) working. The only `^https?://` test left in the
  frontend lives inside `externalUrl`.

