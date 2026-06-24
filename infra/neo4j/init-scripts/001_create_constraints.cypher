// Neo4j initialization — unique constraints for the eCTD dossier graph
//
// Run once after first Neo4j startup:
//   cat infra/neo4j/init-scripts/001_create_constraints.cypher | docker exec -i hyperlink-neo4j cypher-shell -u neo4j -p changeme

// ── Dossier node ──────────────────────────────────────────────────────
CREATE CONSTRAINT dossier_id_unique IF NOT EXISTS
FOR (d:Dossier) REQUIRE d.dossier_id IS UNIQUE;

// ── Document (leaf) node ──────────────────────────────────────────────
CREATE CONSTRAINT document_path_unique IF NOT EXISTS
FOR (doc:Document) REQUIRE doc.path IS UNIQUE;

// ── Module node ───────────────────────────────────────────────────────
CREATE CONSTRAINT module_code_unique IF NOT EXISTS
FOR (m:Module) REQUIRE m.code IS UNIQUE;

// ── Sequence node ─────────────────────────────────────────────────────
CREATE CONSTRAINT sequence_id_unique IF NOT EXISTS
FOR (s:Sequence) REQUIRE s.sequence_id IS UNIQUE;

// ── HyperlinkRef relationship index ───────────────────────────────────
CREATE INDEX hyperlink_ref_source_idx IF NOT EXISTS
FOR ()-[r:HYPERLINK_REF]-() ON (r.source_doc);
