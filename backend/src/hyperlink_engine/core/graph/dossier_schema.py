"""Neo4j persistence for pipeline runs and their hyperlink graph.

This is the run-history + link-graph store (Plan Two P2-B2). It is *separate*
from :class:`Neo4jBackboneStore` (which persists the eCTD ``index.xml`` backbone
of :Leaf / :Module nodes) — the two graphs join later via a ``PUBLISHED_AS``
bridge, deferred until the upload flow ingests a real backbone.

Schema (see docs/neo4j-schema or the design notes)::

    (:Dossier {dossier_id, sponsor, submission_type, region})
    (:Run {run_id, dossier_id, status, score, grade, total_links,
           preset, engine, review_status, created_at})
    (:Document {doc_id, run_id, filename, role, study_key, link_count,
                source_path, linked_path, sha256})
    (:Reference {ref_id, run_id, link_text, link_type, location,
                 target_doc, target_anchor, status, confidence, detected_by})
    (:Website {url, host})

    (:Dossier)-[:HAS_RUN]->(:Run)
    (:Run)-[:PROCESSED]->(:Document)
    (:Document)-[:CONTAINS_REF]->(:Reference)
    (:Reference)-[:RESOLVES_TO]->(:Document)      # cross-document target
    (:Reference)-[:LINKS_TO]->(:Website)          # external website
    (:Document)-[:CROSS_LINKS {count}]->(:Document)

Everything here is **best-effort**: if the neo4j driver is missing, the server
is unreachable, or ``graph_backend`` isn't "neo4j", the public helpers degrade
to no-ops / empty results so the in-memory run store keeps working unchanged.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings

_log = get_logger("graph.dossier")


# ─────────────────────────────────────────────────────────────────────────────
# Link classification (mirrors the frontend classifyLink rules)
# ─────────────────────────────────────────────────────────────────────────────


def _classify(link: dict[str, Any]) -> str:
    anchor = str(link.get("target_anchor") or "")
    if anchor.lower().startswith(("http://", "https://")):
        return "external"
    td = str(link.get("target_doc") or "")
    if td.lower().endswith(("_linked.docx", "_linked.pdf")):
        return "cross-doc"
    return "internal"


def _role(filename: str) -> str:
    n = filename.lower()
    if "protocol" in n:
        return "protocol"
    if "sap" in n:
        return "sap"
    if "listing" in n:
        return "listings"
    if "csr" in n or "body" in n:
        return "csr"
    return "other"


def _study_key(filename: str) -> str:
    import re

    m = re.search(r"\d{4}\d{2,3}", re.sub(r"[^0-9]", "", filename))
    return m.group(0) if m else ""


def _study_label(filename: str) -> str:
    """Human-readable study id, e.g. 'csr-sp-2026-001-body...' -> 'SP-2026-001'.

    Falls back to the digit-only :func:`_study_key` form when the canonical
    'XX-YYYY-NNN' pattern isn't present.
    """
    import re

    m = re.search(r"(?i)([a-z]{2,4})-?(\d{4})-?(\d{3})", filename)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}-{m.group(3)}"
    key = _study_key(filename)
    return f"STUDY-{key}" if key else "STUDY-UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────────────


class DossierGraphStore:
    """Persist + query pipeline runs and their reference graph in Neo4j."""

    def __init__(self, uri: str, user: str, password: str, *, database: str = "neo4j") -> None:
        import neo4j  # type: ignore[import-not-found]

        self._database = database
        self._driver = neo4j.GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def _session(self) -> Any:
        return self._driver.session(database=self._database)

    # ── Schema ──────────────────────────────────────────────────────────────

    def ensure_schema(self) -> None:
        stmts = [
            "CREATE CONSTRAINT run_id   IF NOT EXISTS FOR (r:Run)       REQUIRE r.run_id IS UNIQUE",
            "CREATE CONSTRAINT doc_id   IF NOT EXISTS FOR (d:Document)  REQUIRE d.doc_id IS UNIQUE",
            "CREATE CONSTRAINT ref_id   IF NOT EXISTS FOR (x:Reference) REQUIRE x.ref_id IS UNIQUE",
            "CREATE CONSTRAINT doss_id  IF NOT EXISTS FOR (n:Dossier)   REQUIRE n.dossier_id IS UNIQUE",
            "CREATE CONSTRAINT web_url  IF NOT EXISTS FOR (w:Website)   REQUIRE w.url IS UNIQUE",
        ]
        # v2 enterprise-layer constraints (additive — safe to create always).
        v2_stmts = [
            "CREATE CONSTRAINT sponsor_name IF NOT EXISTS FOR (s:Sponsor) REQUIRE s.name IS UNIQUE",
            "CREATE CONSTRAINT study_uid    IF NOT EXISTS FOR (s:Study) REQUIRE s.study_uid IS UNIQUE",
            "CREATE CONSTRAINT docver_id    IF NOT EXISTS FOR (v:DocumentVersion) REQUIRE v.version_id IS UNIQUE",
            "CREATE CONSTRAINT method_name  IF NOT EXISTS FOR (m:DetectionMethod) REQUIRE m.method IS UNIQUE",
            "CREATE CONSTRAINT reftype_name IF NOT EXISTS FOR (t:RefType) REQUIRE t.type IS UNIQUE",
        ]
        # v3 lifecycle-layer constraints + low-cardinality dimension indexes.
        # The indexes implement the "dims as indexed properties" refinement so
        # detected_by/status/stage analytics stay fast without supernodes.
        v3_stmts = [
            "CREATE CONSTRAINT seq_uid    IF NOT EXISTS FOR (s:Sequence) REQUIRE s.seq_uid IS UNIQUE",
            "CREATE CONSTRAINT appr_id    IF NOT EXISTS FOR (a:Approval) REQUIRE a.approval_id IS UNIQUE",
            "CREATE INDEX ref_detected_by IF NOT EXISTS FOR (x:Reference) ON (x.detected_by)",
            "CREATE INDEX ref_status      IF NOT EXISTS FOR (x:Reference) ON (x.status)",
            "CREATE INDEX docver_stage    IF NOT EXISTS FOR (v:DocumentVersion) ON (v.stage)",
        ]
        with self._session() as s:
            for stmt in stmts + v2_stmts + v3_stmts:
                s.run(stmt)

    # ── Write-through ─────────────────────────────────────────────────────────

    def persist_run(self, state: dict[str, Any]) -> None:
        """Write one finished run (Run + Documents + References) idempotently."""
        run_id = state["run_id"]
        dossier_id = state.get("dossier_id") or f"run-{run_id}"
        links = state.get("links", []) or []
        linked_files = [Path(p) for p in state.get("linked_files", [])]
        input_files = [Path(p) for p in state.get("input_files", [])]
        created_at = state.get("created_at") or _dt.datetime.utcnow().isoformat()

        _settings = get_settings()
        schema = getattr(_settings, "graph_schema", "v2")
        sponsor = getattr(_settings, "graph_sponsor_name", "Sun Pharma")

        # Map an original source basename -> its linked output path, so a
        # Reference's source_doc can be attached to the right Document node.
        src_to_linked: dict[str, Path] = {}
        for lf in linked_files:
            src_to_linked[lf.name.replace("_linked", "")] = lf
        # Map original basename -> original source path (for hydration/preview).
        src_to_origpath: dict[str, Path] = {p.name: p for p in input_files}

        with self._session() as s:
            # Dossier + Run
            s.run(
                """
                MERGE (n:Dossier {dossier_id: $dossier_id})
                MERGE (r:Run {run_id: $run_id})
                SET r.dossier_id = $dossier_id, r.status = $status,
                    r.score = $score, r.grade = $grade, r.total_links = $total_links,
                    r.preset = $preset, r.engine = $engine,
                    r.classification = $classification, r.owner = $owner,
                    r.review_status = coalesce(r.review_status, 'pending_review'),
                    r.created_at = coalesce(r.created_at, $created_at)
                MERGE (n)-[:HAS_RUN]->(r)
                """,
                dossier_id=dossier_id,
                run_id=run_id,
                status=state.get("status", "done"),
                score=float(state.get("score") or 0.0),
                grade=state.get("grade") or "F",
                total_links=len(links),
                preset=_preset_of(state),
                engine="langgraph",
                classification=str(state.get("classification") or "unclassified"),
                owner=str(state.get("owner") or ""),
                created_at=created_at,
            )

            # Documents (one per linked output file)
            for lf in linked_files:
                src_basename = lf.name.replace("_linked", "")
                count = sum(
                    1 for l in links
                    if str(l.get("source_doc")) in (src_basename, lf.name)
                )
                orig = src_to_origpath.get(src_basename)
                s.run(
                    """
                    MATCH (r:Run {run_id: $run_id})
                    MERGE (d:Document {doc_id: $doc_id})
                    SET d.run_id = $run_id, d.filename = $filename, d.role = $role,
                        d.study_key = $study_key, d.link_count = $link_count,
                        d.source_path = $source_path, d.linked_path = $linked_path
                    MERGE (r)-[:PROCESSED]->(d)
                    """,
                    run_id=run_id,
                    doc_id=f"{run_id}:{lf.name}",
                    filename=lf.name,
                    role=_role(lf.name),
                    study_key=_study_key(lf.name),
                    link_count=count,
                    source_path=str(orig) if orig else "",
                    linked_path=str(lf),
                )

            # References + their target edges. Each query is kept *connected*
            # (a single anchor node carried through WITH) to avoid Neo4j's
            # cartesian-product advisories when wiring two known nodes.
            for i, l in enumerate(links):
                ref_id = f"{run_id}:{i}"
                kind = _classify(l)
                src_doc = str(l.get("source_doc") or "")
                src_linked = src_to_linked.get(src_doc)
                src_doc_id = f"{run_id}:{src_linked.name}" if src_linked else None

                params = dict(
                    ref_id=ref_id,
                    run_id=run_id,
                    link_text=str(l.get("link_text") or ""),
                    link_type=kind,
                    location=str(l.get("link_location_descriptor") or ""),
                    target_doc=str(l.get("target_doc") or ""),
                    target_anchor=str(l.get("target_anchor") or ""),
                    status=str(l.get("status") or "ok"),
                    confidence=float(l.get("confidence") or 0.0),
                    detected_by=str(l.get("detected_by") or "regex"),
                    source_doc=src_doc,
                )
                set_clause = """
                    SET x.run_id = $run_id, x.link_text = $link_text,
                        x.link_type = $link_type, x.location = $location,
                        x.target_doc = $target_doc, x.target_anchor = $target_anchor,
                        x.status = $status, x.confidence = $confidence,
                        x.detected_by = $detected_by, x.source_doc = $source_doc
                """
                if src_doc_id:
                    # Create the Reference under its source Document in one go.
                    s.run(
                        "MATCH (d:Document {doc_id: $doc_id}) "
                        "MERGE (x:Reference {ref_id: $ref_id}) " + set_clause +
                        "MERGE (d)-[:CONTAINS_REF]->(x)",
                        doc_id=src_doc_id, **params,
                    )
                else:
                    s.run("MERGE (x:Reference {ref_id: $ref_id}) " + set_clause, **params)

                if kind == "external":
                    url = str(l.get("target_anchor"))
                    s.run(
                        """
                        MERGE (w:Website {url: $url}) SET w.host = $host
                        WITH w
                        MATCH (x:Reference {ref_id: $ref_id})
                        MERGE (x)-[:LINKS_TO]->(w)
                        """,
                        ref_id=ref_id, url=url, host=urlparse(url).hostname or "",
                    )
                elif kind == "cross-doc":
                    tgt_doc_id = f"{run_id}:{l.get('target_doc')}"
                    # Cross-doc target edge (only if the target doc is in this run).
                    s.run(
                        """
                        MATCH (t:Document {doc_id: $tgt_doc_id})
                        WITH t
                        MATCH (x:Reference {ref_id: $ref_id})
                        MERGE (x)-[:RESOLVES_TO]->(t)
                        """,
                        ref_id=ref_id, tgt_doc_id=tgt_doc_id,
                    )
                    # Aggregated doc->doc edge for the heatmap/viz.
                    if src_doc_id:
                        s.run(
                            """
                            MATCH (b:Document {doc_id: $dst})
                            WITH b
                            MATCH (a:Document {doc_id: $src})
                            MERGE (a)-[c:CROSS_LINKS]->(b)
                            SET c.count = coalesce(c.count, 0) + 1
                            """,
                            src=src_doc_id, dst=tgt_doc_id,
                        )

            # ── v2 enterprise layer (additive) ───────────────────────────────
            if schema in ("v2", "v3"):
                self._persist_enterprise_layer(
                    s, run_id=run_id, dossier_id=dossier_id, sponsor=sponsor,
                    linked_files=linked_files, links=links,
                )
            # ── v3 lifecycle layer: Sequence + INCLUDES the linked versions ──
            if schema == "v3":
                self._persist_sequence_layer(
                    s, run_id=run_id, dossier_id=dossier_id, state=state,
                    linked_files=linked_files,
                )

    def _persist_enterprise_layer(
        self,
        s: Any,
        *,
        run_id: str,
        dossier_id: str,
        sponsor: str,
        linked_files: list[Path],
        links: list[dict[str, Any]],
    ) -> None:
        """Write the enterprise graph layer on top of the core Run/Document/
        Reference nodes already created by :meth:`persist_run`.

        Adds the regulatory hierarchy (Sponsor → Dossier → Study → Document),
        per-stage DocumentVersion nodes, and first-class provenance nodes
        (DetectionMethod, RefType) so the graph answers *why* a link exists and
        *how* it was detected — instead of every Reference looking like "0.9".
        All writes MATCH existing nodes and MERGE the new structure, so they are
        idempotent and never disturb the core nodes or hydration.
        """
        # Sponsor owns the dossier.
        s.run(
            """
            MERGE (sp:Sponsor {name: $sponsor})
            WITH sp
            MATCH (d:Dossier {dossier_id: $dossier_id})
            MERGE (sp)-[:OWNS]->(d)
            """,
            sponsor=sponsor, dossier_id=dossier_id,
        )

        # Study hierarchy + a 'linked'-stage DocumentVersion per document.
        for lf in linked_files:
            doc_id = f"{run_id}:{lf.name}"
            study_label = _study_label(lf.name)
            study_uid = f"{dossier_id}:{study_label}"
            version_id = f"{doc_id}:linked"
            s.run(
                """
                MATCH (doc:Document {doc_id: $doc_id})
                MATCH (n:Dossier {dossier_id: $dossier_id})
                MATCH (r:Run {run_id: $run_id})
                MERGE (st:Study {study_uid: $study_uid})
                  ON CREATE SET st.label = $study_label, st.dossier_id = $dossier_id
                MERGE (n)-[:CONTAINS_STUDY]->(st)
                MERGE (st)-[:HAS_DOCUMENT]->(doc)
                MERGE (v:DocumentVersion {version_id: $version_id})
                  ON CREATE SET v.stage = 'linked', v.filename = $filename,
                                v.linked_path = $linked_path
                MERGE (doc)-[:HAS_VERSION]->(v)
                MERGE (r)-[:PRODUCED]->(v)
                """,
                doc_id=doc_id, dossier_id=dossier_id, run_id=run_id,
                study_uid=study_uid, study_label=study_label,
                version_id=version_id, filename=lf.name, linked_path=str(lf),
            )

        # Map an original source basename -> its linked DocumentVersion id.
        src_to_version: dict[str, str] = {}
        for lf in linked_files:
            src_to_version[lf.name.replace("_linked", "")] = f"{run_id}:{lf.name}:linked"
            src_to_version[lf.name] = f"{run_id}:{lf.name}:linked"

        # Provenance per reference: DetectionMethod + RefType, and tie each
        # reference to its source doc's linked DocumentVersion.
        for i, l in enumerate(links):
            ref_id = f"{run_id}:{i}"
            method = str(l.get("detected_by") or "regex").lower()
            ref_type = _classify(l)
            version_id = src_to_version.get(str(l.get("source_doc") or ""))
            s.run(
                """
                MATCH (x:Reference {ref_id: $ref_id})
                MERGE (m:DetectionMethod {method: $method})
                MERGE (x)-[:DETECTED_BY]->(m)
                MERGE (t:RefType {type: $ref_type})
                MERGE (x)-[:OF_TYPE]->(t)
                """,
                ref_id=ref_id, method=method, ref_type=ref_type,
            )
            if version_id:
                s.run(
                    """
                    MATCH (v:DocumentVersion {version_id: $version_id})
                    WITH v
                    MATCH (x:Reference {ref_id: $ref_id})
                    MERGE (v)-[:CONTAINS_REFERENCE]->(x)
                    """,
                    version_id=version_id, ref_id=ref_id,
                )

    # ── v3 lifecycle layer (Sequence + Approval + SUPERSEDES) ─────────────────

    def _persist_sequence_layer(
        self,
        s: Any,
        *,
        run_id: str,
        dossier_id: str,
        state: dict[str, Any],
        linked_files: list[Path],
    ) -> None:
        """v3 lifecycle seed: a Sequence node for the dossier that INCLUDES every
        linked DocumentVersion produced by this run (eCTD ``leaf_op='new'``).

        Idempotent — re-running a run MERGEs the same Sequence + edges.
        """
        seq_number = str(state.get("sequence") or "0001")
        region = str(state.get("region") or getattr(get_settings(), "graph_region", "US (FDA)"))
        seq_uid = f"{dossier_id}:{seq_number}"
        s.run(
            """
            MERGE (n:Dossier {dossier_id: $did})
            MERGE (sq:Sequence {seq_uid: $seq_uid})
              ON CREATE SET sq.seq_number = $seq, sq.region = $region,
                            sq.status = 'in_progress', sq.dossier_id = $did
            MERGE (n)-[:HAS_SEQUENCE]->(sq)
            """,
            did=dossier_id, seq_uid=seq_uid, seq=seq_number, region=region,
        )
        for lf in linked_files:
            s.run(
                """
                MATCH (sq:Sequence {seq_uid: $seq_uid})
                MATCH (v:DocumentVersion {version_id: $vid})
                MERGE (sq)-[inc:INCLUDES]->(v)
                  ON CREATE SET inc.leaf_op = 'new'
                """,
                seq_uid=seq_uid, vid=f"{run_id}:{lf.name}:linked",
            )

    def persist_lifecycle_stage(
        self,
        *,
        run_id: str,
        dossier_id: str,
        stage: str,
        source_stage: str,
        doc_paths: dict[str, str],
        meta: dict[str, Any] | None = None,
        seq_number: str = "0001",
        region: str = "US (FDA)",
    ) -> dict[str, int]:
        """Persist an advanced lifecycle stage as a new DocumentVersion (v3).

        Per document it writes a ``:DocumentVersion {stage}`` that SUPERSEDES the
        prior stage, a Sequence ``INCLUDES {leaf_op}`` edge ('replace' for
        fda_ready, else 'new'), an ``:Approval`` + ``APPROVED_BY`` for the
        compliance stage (21 CFR Part 11 e-signature), and re-anchors the run's
        references for that document to the new version. Best-effort + idempotent.
        """
        meta = meta or {}
        leaf_op = "replace" if stage == "fda_ready" else "new"
        seq_uid = f"{dossier_id}:{seq_number}"
        at = str(meta.get("at") or _dt.datetime.utcnow().isoformat())
        by = str(meta.get("by") or "Compliance Officer")
        versions = 0
        with self._session() as s:
            s.run(
                """
                MERGE (n:Dossier {dossier_id: $did})
                MERGE (sq:Sequence {seq_uid: $seq_uid})
                  ON CREATE SET sq.seq_number = $seq, sq.region = $region,
                                sq.status = 'in_progress', sq.dossier_id = $did
                MERGE (n)-[:HAS_SEQUENCE]->(sq)
                """,
                did=dossier_id, seq_uid=seq_uid, seq=seq_number, region=region,
            )
            for _key, path in (doc_paths or {}).items():
                fname = Path(path).name
                stem = fname.replace("_linked", "")
                new_vid = f"{run_id}:{fname}:{stage}"
                prior_vid = f"{run_id}:{fname}:{source_stage}"
                s.run(
                    """
                    MATCH (sq:Sequence {seq_uid: $seq_uid})
                    OPTIONAL MATCH (doc:Document {doc_id: $doc_id})
                    OPTIONAL MATCH (r:Run {run_id: $run_id})
                    MERGE (v:DocumentVersion {version_id: $new_vid})
                      ON CREATE SET v.stage = $stage, v.filename = $fname,
                                    v.linked_path = $path, v.created_at = $at
                      ON MATCH SET v.stage = $stage
                    MERGE (sq)-[inc:INCLUDES]->(v) SET inc.leaf_op = $leaf_op
                    FOREACH (_ IN CASE WHEN doc IS NULL THEN [] ELSE [1] END |
                        MERGE (doc)-[:HAS_VERSION]->(v))
                    FOREACH (_ IN CASE WHEN r IS NULL THEN [] ELSE [1] END |
                        MERGE (r)-[:PRODUCED]->(v))
                    WITH v
                    OPTIONAL MATCH (pv:DocumentVersion {version_id: $prior_vid})
                    FOREACH (_ IN CASE WHEN pv IS NULL THEN [] ELSE [1] END |
                        MERGE (v)-[:SUPERSEDES]->(pv))
                    """,
                    seq_uid=seq_uid, doc_id=f"{run_id}:{fname}", run_id=run_id,
                    new_vid=new_vid, prior_vid=prior_vid, stage=stage,
                    fname=fname, path=str(path), at=at, leaf_op=leaf_op,
                )
                # Separate query: re-anchor references so a zero-reference
                # document still gets its version created above.
                s.run(
                    """
                    MATCH (v:DocumentVersion {version_id: $new_vid})
                    MATCH (x:Reference {run_id: $run_id})
                    WHERE x.source_doc IN [$fname, $stem]
                    MERGE (v)-[:CONTAINS_REFERENCE]->(x)
                    """,
                    new_vid=new_vid, run_id=run_id, fname=fname, stem=stem,
                )
                if stage == "compliance_approved":
                    s.run(
                        """
                        MATCH (v:DocumentVersion {version_id: $new_vid})
                        MERGE (a:Approval {approval_id: $appr_id})
                          ON CREATE SET a.role = 'Compliance Officer', a.signer = $by,
                                        a.signed_at = $at, a.sig_alg = 'ECDSA-P256',
                                        a.outcome = 'approved'
                        MERGE (v)-[:APPROVED_BY]->(a)
                        """,
                        new_vid=new_vid, appr_id=f"{run_id}:{fname}:approval",
                        by=by, at=at,
                    )
                versions += 1
        _log.info("lifecycle_stage_persisted", run_id=run_id, stage=stage, versions=versions)
        return {"versions": versions}

    def migrate_existing_to_v2(self) -> dict[str, int]:
        """Backfill the v2 enterprise layer onto runs already in the graph.

        Operates *graph-natively* — it reads each node's own stored properties
        (``detected_by``, ``link_type``, ``filename``) rather than re-deriving
        from a list, so it's accurate regardless of ordering and fully
        idempotent (all MERGE; it never touches the counted ``CROSS_LINKS``
        edge, so re-running can't inflate counts). Safe to run repeatedly.
        """
        self.ensure_schema()
        sponsor = getattr(get_settings(), "graph_sponsor_name", "Sun Pharma")
        counts = {"dossiers": 0, "documents": 0, "references": 0}
        with self._session() as s:
            # Sponsor → every Dossier.
            s.run(
                "MATCH (d:Dossier) MERGE (sp:Sponsor {name: $sponsor}) MERGE (sp)-[:OWNS]->(d)",
                sponsor=sponsor,
            )
            counts["dossiers"] = (s.run("MATCH (d:Dossier) RETURN count(d) AS c").single() or {}).get("c", 0)

            # Provenance from each Reference's *own* properties.
            s.run(
                """
                MATCH (x:Reference)
                WITH x, toLower(coalesce(x.detected_by, 'regex')) AS m
                MERGE (dm:DetectionMethod {method: m})
                MERGE (x)-[:DETECTED_BY]->(dm)
                """
            )
            s.run(
                """
                MATCH (x:Reference)
                WITH x, coalesce(x.link_type, 'internal') AS t
                MERGE (rt:RefType {type: t})
                MERGE (x)-[:OF_TYPE]->(rt)
                """
            )
            counts["references"] = (s.run("MATCH (x:Reference) RETURN count(x) AS c").single() or {}).get("c", 0)

            # Study + linked DocumentVersion per Document (study label in Python).
            docs = s.run(
                """
                MATCH (n:Dossier)-[:HAS_RUN]->(r:Run)-[:PROCESSED]->(doc:Document)
                RETURN n.dossier_id AS dossier_id, r.run_id AS run_id,
                       doc.doc_id AS doc_id, doc.filename AS filename
                """
            ).data()
            for d in docs:
                study_label = _study_label(d.get("filename") or "")
                s.run(
                    """
                    MATCH (doc:Document {doc_id: $doc_id})
                    MATCH (n:Dossier {dossier_id: $dossier_id})
                    MATCH (r:Run {run_id: $run_id})
                    MERGE (st:Study {study_uid: $study_uid})
                      ON CREATE SET st.label = $label, st.dossier_id = $dossier_id
                    MERGE (n)-[:CONTAINS_STUDY]->(st)
                    MERGE (st)-[:HAS_DOCUMENT]->(doc)
                    MERGE (v:DocumentVersion {version_id: $version_id})
                      ON CREATE SET v.stage = 'linked', v.filename = $filename
                    MERGE (doc)-[:HAS_VERSION]->(v)
                    MERGE (r)-[:PRODUCED]->(v)
                    """,
                    doc_id=d["doc_id"], dossier_id=d["dossier_id"], run_id=d["run_id"],
                    study_uid=f"{d['dossier_id']}:{study_label}", label=study_label,
                    version_id=f"{d['doc_id']}:linked", filename=d.get("filename") or "",
                )
            counts["documents"] = len(docs)

            # Bridge references to their source doc's linked version.
            s.run(
                """
                MATCH (doc:Document)-[:CONTAINS_REF]->(x:Reference)
                MATCH (doc)-[:HAS_VERSION]->(v:DocumentVersion {stage: 'linked'})
                MERGE (v)-[:CONTAINS_REFERENCE]->(x)
                """
            )
        return counts

    def migrate_existing_to_v3(self) -> dict[str, int]:
        """Backfill the v3 lifecycle layer onto runs already in the graph.

        Creates a default Sequence per Dossier (seq '0001') + an INCLUDES edge to
        every linked DocumentVersion its runs produced, and ensures the v3
        constraints/indexes exist. Idempotent (all MERGE) — safe to repeat.
        """
        self.migrate_existing_to_v2()  # ensures v2 versions exist first
        region = getattr(get_settings(), "graph_region", "US (FDA)")
        with self._session() as s:
            s.run(
                """
                MATCH (n:Dossier)
                MERGE (sq:Sequence {seq_uid: n.dossier_id + ':0001'})
                  ON CREATE SET sq.seq_number = '0001', sq.region = $region,
                                sq.status = 'in_progress', sq.dossier_id = n.dossier_id
                MERGE (n)-[:HAS_SEQUENCE]->(sq)
                WITH n, sq
                MATCH (n)-[:HAS_RUN]->(:Run)-[:PRODUCED]->(v:DocumentVersion)
                MERGE (sq)-[inc:INCLUDES]->(v)
                  ON CREATE SET inc.leaf_op = 'new'
                """,
                region=region,
            )
            seqs = (s.run("MATCH (sq:Sequence) RETURN count(sq) AS c").single() or {}).get("c", 0)
        return {"sequences": seqs}

    def set_review_status(self, run_id: str, status: str) -> None:
        with self._session() as s:
            s.run(
                "MATCH (r:Run {run_id: $id}) SET r.review_status = $st",
                id=run_id, st=status,
            )

    def update_reference(
        self,
        run_id: str,
        source_doc: str,
        link_text: str,
        updates: dict[str, Any],
    ) -> None:
        """Update editable fields on a :Reference node (inline edit).

        Only ``target_doc``, ``target_anchor``, and ``status`` are allowed;
        other keys are silently ignored. Best-effort — a missing node or
        unavailable Neo4j connection is a no-op, not an error.
        """
        allowed = {"target_doc", "target_anchor", "status"}
        filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}
        if not filtered:
            return
        set_clauses = ", ".join(f"x.{k} = ${k}" for k in filtered)
        cypher = (
            f"MATCH (x:Reference {{run_id: $run_id, source_doc: $source_doc, "
            f"link_text: $link_text}}) SET {set_clauses}"
        )
        try:
            with self._session() as s:
                s.run(cypher, run_id=run_id, source_doc=source_doc, link_text=link_text, **filtered)
        except Exception as exc:  # noqa: BLE001
            _log.warning("update_reference_failed", run_id=run_id, error=str(exc))

    # ── Read / hydrate ────────────────────────────────────────────────────────

    def fetch_runs(self) -> list[dict[str, Any]]:
        """Return every persisted run as a state-like dict for hydration."""
        out: list[dict[str, Any]] = []
        with self._session() as s:
            runs = s.run(
                """
                MATCH (r:Run)
                RETURN r.run_id AS run_id, r.dossier_id AS dossier_id,
                       r.status AS status, r.score AS score, r.grade AS grade,
                       r.classification AS classification, r.owner AS owner,
                       r.created_at AS created_at
                ORDER BY r.created_at DESC
                """
            ).data()
            for r in runs:
                rid = r["run_id"]
                docs = s.run(
                    """
                    MATCH (:Run {run_id: $id})-[:PROCESSED]->(d:Document)
                    RETURN d.filename AS filename, d.source_path AS source_path,
                           d.linked_path AS linked_path
                    """,
                    id=rid,
                ).data()
                refs = s.run(
                    """
                    MATCH (x:Reference {run_id: $id})
                    RETURN x.source_doc AS source_doc, x.link_text AS link_text,
                           x.location AS location, x.target_doc AS target_doc,
                           x.target_anchor AS target_anchor, x.status AS status,
                           x.confidence AS confidence, x.detected_by AS detected_by
                    """,
                    id=rid,
                ).data()
                out.append(_run_to_state(r, docs, refs))
        return out


def _preset_of(state: dict[str, Any]) -> str:
    prof = state.get("agent_profile") or {}
    # detect agent encodes the preset intent well enough for display
    return str(prof.get("detect", "")) if isinstance(prof, dict) else ""


def _run_to_state(run: dict[str, Any], docs: list[dict], refs: list[dict]) -> dict[str, Any]:
    """Rebuild the minimal PipelineState a restarted server needs for Run Compare."""
    links = [
        {
            "source_doc": d.get("source_doc") or "",
            "link_text": d.get("link_text") or "",
            "link_location_descriptor": d.get("location") or "",
            "target_doc": d.get("target_doc") or "",
            "target_anchor": d.get("target_anchor") or "",
            "status": d.get("status") or "ok",
            "confidence": d.get("confidence") or 0.9,
            "error_msg": None,
            "detected_by": d.get("detected_by") or "regex",
        }
        for d in refs
    ]
    return {
        "run_id": run["run_id"],
        "dossier_id": run.get("dossier_id") or run["run_id"],
        "status": run.get("status") or "done",
        "current_node": "__end__",
        "score": run.get("score") or 0.0,
        "grade": run.get("grade") or "F",
        # Legacy Run nodes persisted before PLAN SEVEN have no classification
        # property — they hydrate as unclassified so existing demo data stays
        # visible (deliberate backward-compat tradeoff, see plan §2).
        "classification": run.get("classification") or "unclassified",
        "owner": run.get("owner") or "",
        "created_at": run.get("created_at"),
        "input_files": [d["source_path"] for d in docs if d.get("source_path")],
        "linked_files": [d["linked_path"] for d in docs if d.get("linked_path")],
        "links": links,
        "anomalies": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Best-effort singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_store: DossierGraphStore | None = None
_store_disabled = False


def get_dossier_store() -> DossierGraphStore | None:
    """Return a ready store, or ``None`` if Neo4j isn't available/enabled.

    Caches a 'disabled' flag after the first failure so we don't pay a slow
    connection timeout on every request when Neo4j simply isn't running.
    """
    global _store, _store_disabled
    if _store is not None:
        return _store
    if _store_disabled:
        return None

    settings = get_settings()
    if getattr(settings, "graph_backend", "networkx") != "neo4j":
        _store_disabled = True
        return None
    try:
        store = DossierGraphStore(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            database=getattr(settings, "neo4j_database", "neo4j"),
        )
        store.ensure_schema()
        _store = store
        _log.info("dossier_graph_store_ready", uri=settings.neo4j_uri)
        return _store
    except Exception as exc:  # noqa: BLE001 — persistence must never break a run
        _store_disabled = True
        _log.warning("dossier_graph_store_unavailable", error=str(exc))
        return None
