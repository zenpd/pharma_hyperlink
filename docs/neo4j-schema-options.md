# Neo4j Schema Options for the Hyperlink Engine

> Three candidate schemas for the dossier / run / hyperlink graph, with trade-offs
> and a recommendation. The goal: faithfully model **detection provenance**
> (regex / NER / LLM), the **submission lifecycle** (raw → linked →
> compliance-approved → eCTD/FDA-ready), and **21 CFR Part 11 audit** — while
> staying fast to write and query.

## Where we are today (baseline)

The current `graph/dossier_schema.py` (v2) writes:

```
(:Sponsor)-[:OWNS]->(:Dossier)-[:HAS_RUN]->(:Run)-[:PROCESSED]->(:Document)
(:Dossier)-[:CONTAINS_STUDY]->(:Study)-[:HAS_DOCUMENT]->(:Document)
(:Document)-[:HAS_VERSION]->(:DocumentVersion {stage:'linked'})
(:Document)-[:CONTAINS_REF]->(:Reference)-[:DETECTED_BY]->(:DetectionMethod)
(:Reference)-[:OF_TYPE]->(:RefType)
(:Reference)-[:RESOLVES_TO]->(:Document) | -[:LINKS_TO]->(:Website)
(:Document)-[:CROSS_LINKS {count}]->(:Document)
```

Two pain points motivate a rethink:

1. **Low-cardinality dimension nodes become supernodes.** `DetectionMethod`
   has only ~4 distinct values (`regex`/`ner`/`llm`/`mixed`) but every one of
   thousands of `:Reference` nodes points at it via `DETECTED_BY`. Same for
   `RefType`. These hubs are hotspots and add a write per reference for little
   analytical gain over an indexed property.
2. **References hang off `Document`, not `DocumentVersion`.** So you can't ask
   "what links existed in the *approved* vs the *FDA-ready* version?" — exactly
   the question the compliance/eCTD change-control flow needs.

---

## Schema A — Lean Property Graph (write-fast, minimal)

Keep only true entities as nodes; push every low-cardinality attribute onto the
`:Reference`/`:Document` as an **indexed property**.

**Nodes**

```
(:Dossier   {dossier_id, sponsor, region})
(:Run       {run_id, status, score, grade, preset, engine, created_at})
(:Document  {doc_id, run_id, filename, role, study_key, sha256, stage, link_count})
(:Reference {ref_id, run_id, link_text, location, target_doc, target_anchor,
             status, confidence, detected_by, ref_type})   // dims = properties
(:Website   {url, host})
```

**Relationships**

```
(:Dossier)-[:HAS_RUN]->(:Run)-[:PROCESSED]->(:Document)
(:Document)-[:CONTAINS]->(:Reference)
(:Reference)-[:RESOLVES_TO]->(:Document)
(:Reference)-[:LINKS_TO]->(:Website)
(:Document)-[:CROSS_LINKS {count}]->(:Document)
```

**Indexes** `Reference.detected_by`, `Reference.status`, `Reference.ref_type`,
`Document.study_key`.

**Detection-method mix** → `MATCH (x:Reference) RETURN x.detected_by, count(*)`

- ➕ Fewest nodes/edges, fastest writes, no supernodes, trivial to reason about.
- ➖ No sponsor/study hierarchy; no version/lifecycle history; cross-dossier
  analytics are property scans, not graph traversals.

---

## Schema B — Provenance-Normalized (today's v2, refined)

Everything is a first-class node so the graph itself answers "how/why".

**Nodes** `Sponsor, Dossier, Study, Document, DocumentVersion, Run, Reference,
DetectionMethod, RefType, Website`

**Relationships**

```
(:Sponsor)-[:OWNS]->(:Dossier)-[:CONTAINS_STUDY]->(:Study)-[:HAS_DOCUMENT]->(:Document)
(:Dossier)-[:HAS_RUN]->(:Run)-[:PROCESSED]->(:Document)-[:HAS_VERSION]->(:DocumentVersion)
(:Document)-[:CONTAINS_REF]->(:Reference)-[:DETECTED_BY]->(:DetectionMethod)
(:Reference)-[:OF_TYPE]->(:RefType)
(:Reference)-[:RESOLVES_TO]->(:Document) | -[:LINKS_TO]->(:Website)
```

**Detection-method mix** →
`MATCH (:Reference)-[:DETECTED_BY]->(m:DetectionMethod) RETURN m.method, count(*)`

- ➕ Rich ad-hoc analytics, sponsor/study hierarchy, provenance hubs,
  graph-native "group by method/type".
- ➖ `DetectionMethod`/`RefType` supernodes; an extra 2 writes per reference;
  references still anchored to `Document`, so no per-version link history.

---

## Schema C — Lifecycle-Versioned / Bitemporal (audit-first)  ★ recommended

Make the **DocumentVersion** the centre of gravity and model the eCTD sequence
+ approvals as first-class. This is the schema that directly encodes "a document
changed after the compliance officer approved it, so the eCTD leaf is replaced
in the next sequence and the new version must be re-approved."

**Nodes**

```
(:Sponsor   {name})
(:Dossier   {dossier_id, region})
(:Sequence  {seq_number, region, status})            // eCTD submission sequence
(:Study     {study_uid, label})
(:Document  {doc_id, study_key, role})               // identity only
(:DocumentVersion {version_id, stage, sha256,        // stage: raw|linked|
                   created_at, valid_from, valid_to})//   compliance_approved|fda_ready
(:Run       {run_id, status, score, grade, preset, engine, created_at})
(:Reference {ref_id, link_text, location, target_anchor,
             status, confidence, detected_by, ref_type})  // dims = indexed props
(:Approval  {approval_id, role, signer, signed_at, sig_alg, outcome})
(:Website   {url, host})
```

**Relationships**

```
(:Sponsor)-[:OWNS]->(:Dossier)-[:CONTAINS_STUDY]->(:Study)-[:HAS_DOCUMENT]->(:Document)
(:Dossier)-[:HAS_SEQUENCE]->(:Sequence)
(:Document)-[:HAS_VERSION]->(:DocumentVersion)
(:DocumentVersion)-[:SUPERSEDES]->(:DocumentVersion)        // version/lifecycle chain
(:Run)-[:PRODUCED]->(:DocumentVersion)
(:Sequence)-[:INCLUDES {leaf_op}]->(:DocumentVersion)       // leaf_op: new|replace|append
(:DocumentVersion)-[:CONTAINS_REFERENCE]->(:Reference)      // refs live on the VERSION
(:Reference)-[:RESOLVES_TO]->(:DocumentVersion) | -[:LINKS_TO]->(:Website)
(:DocumentVersion)-[:APPROVED_BY]->(:Approval)              // 21 CFR Part 11 e-signature
```

Low-cardinality dimensions (`detected_by`, `status`, `ref_type`, `stage`) stay
as **indexed properties** (borrowed from Schema A) — no supernodes.

**Signature queries**

```cypher
// Links present in the FDA-ready version of sequence 0010
MATCH (s:Sequence {seq_number:'0010'})-[:INCLUDES]->(v:DocumentVersion {stage:'fda_ready'})
      -[:CONTAINS_REFERENCE]->(r:Reference)
RETURN v.version_id, r.link_text, r.detected_by, r.status;

// Documents changed AFTER approval → need an eCTD replace + re-approval
MATCH (new:DocumentVersion)-[:SUPERSEDES]->(old:DocumentVersion)-[:APPROVED_BY]->(a:Approval)
WHERE new.created_at > a.signed_at
RETURN old.version_id AS approved, new.version_id AS changed, a.signer;

// Detection-method mix for a run (indexed property scan — no supernode)
MATCH (:Run {run_id:$id})-[:PRODUCED]->(:DocumentVersion)-[:CONTAINS_REFERENCE]->(r)
RETURN r.detected_by, count(*) ORDER BY count(*) DESC;
```

- ➕ Models the real regulatory lifecycle (post-approval change, eCTD replace,
  re-approval); per-version link history; full bitemporal audit; no supernodes.
- ➖ Most nodes/edges per document; heavier writes; requires the lifecycle
  (compliance/eCTD stages + approvals) to be persisted, not just the `linked`
  stage we write today.

---

## Comparison

| Dimension | A · Lean | B · Provenance (current) | C · Lifecycle ★ |
|---|---|---|---|
| Node types | 5 | 10 | 10 |
| Write cost / reference | lowest | +2 edges (supernodes) | +1 edge (to version) |
| Supernode risk | none | `DetectionMethod`,`RefType` | none (dims are props) |
| Sponsor/Study hierarchy | ✗ | ✓ | ✓ |
| Per-version link history | ✗ | ✗ | ✓ |
| eCTD sequence + leaf op | ✗ | ✗ | ✓ (`INCLUDES {leaf_op}`) |
| 21 CFR approval/audit | ✗ | partial | ✓ (`Approval`, `SUPERSEDES`) |
| Detection-method analytics | property scan | graph traversal | property scan (indexed) |
| Best when | demo / speed | ad-hoc graph analytics | compliance + eCTD is the product |

## Recommendation — **Schema C**, with two refinements from A

Pick **C (Lifecycle-Versioned)** because the engine's value story *is* the
regulatory lifecycle you keep surfacing (compliance approval changes the doc →
eCTD leaf replace → re-approval). Refine it with:

1. **Dimensions as indexed properties** (`detected_by`, `status`, `ref_type`,
   `stage`) instead of `DetectionMethod`/`RefType` nodes — kills the supernode
   hotspots while keeping `RETURN detected_by, count(*)` fast.
2. **Anchor `Reference` to `DocumentVersion`**, not `Document`, so link history
   is per-version and the eCTD replace chain stays intact.

It's **additive** over what exists: you already persist
`Sponsor/Dossier/Study/Document/DocumentVersion/Run/Reference`. C adds the
`Sequence` and `Approval` nodes, the `SUPERSEDES` chain, `INCLUDES {leaf_op}`,
and moves `CONTAINS_REFERENCE` onto the version.

### Constraints & indexes (for C)

```cypher
CREATE CONSTRAINT doss_id   IF NOT EXISTS FOR (n:Dossier)         REQUIRE n.dossier_id IS UNIQUE;
CREATE CONSTRAINT seq_id    IF NOT EXISTS FOR (s:Sequence)        REQUIRE (s.dossier_id, s.seq_number) IS UNIQUE;
CREATE CONSTRAINT doc_id    IF NOT EXISTS FOR (d:Document)        REQUIRE d.doc_id IS UNIQUE;
CREATE CONSTRAINT ver_id    IF NOT EXISTS FOR (v:DocumentVersion) REQUIRE v.version_id IS UNIQUE;
CREATE CONSTRAINT run_id    IF NOT EXISTS FOR (r:Run)             REQUIRE r.run_id IS UNIQUE;
CREATE CONSTRAINT ref_id    IF NOT EXISTS FOR (x:Reference)       REQUIRE x.ref_id IS UNIQUE;
CREATE CONSTRAINT appr_id   IF NOT EXISTS FOR (a:Approval)        REQUIRE a.approval_id IS UNIQUE;
CREATE CONSTRAINT web_url   IF NOT EXISTS FOR (w:Website)         REQUIRE w.url IS UNIQUE;
CREATE INDEX ref_detected  IF NOT EXISTS FOR (x:Reference)       ON (x.detected_by);
CREATE INDEX ref_status    IF NOT EXISTS FOR (x:Reference)       ON (x.status);
CREATE INDEX ver_stage     IF NOT EXISTS FOR (v:DocumentVersion) ON (v.stage);
```
