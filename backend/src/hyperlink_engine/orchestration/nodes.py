"""Pipeline node functions.

Each function:
  - Takes a PipelineState dict
  - Calls existing pipeline primitives (detect_references, inject_links, …)
  - Emits progress events via event_bus
  - Returns the updated PipelineState

This is the LangGraph node pattern: ``def node(state) -> state``.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path
from typing import Any

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.orchestration.events import event_bus
from hyperlink_engine.orchestration.state import PipelineState

_log = get_logger("orchestration.nodes")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _emit(state: PipelineState, node: str, status: str, **details: Any) -> None:
    state["current_node"] = node
    event_bus.emit(state["run_id"], node, status, details or None)


def _sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Node 1 — load_dossier
# ─────────────────────────────────────────────────────────────────────────────


def node_load_dossier(state: PipelineState) -> PipelineState:
    """Hash each uploaded file and ensure the output directory exists."""
    _emit(state, "load_dossier", "running")
    t0 = time.time()

    output_dir: Path = state["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for fp in state["input_files"]:
        fp = Path(fp)
        records.append(
            {
                "source_path": str(fp),
                "filename": fp.name,
                "sha256": _sha256(fp),
                "file_size_bytes": fp.stat().st_size,
                "suffix": fp.suffix.lower(),
            }
        )

    state["ingest_records"] = records
    _emit(
        state,
        "load_dossier",
        "done",
        files=len(records),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 2 — parse_all
# ─────────────────────────────────────────────────────────────────────────────


def node_parse_all(state: PipelineState) -> PipelineState:
    """Parse each document (docx → paragraphs + run metadata; pdf → pages + spans)."""
    _emit(state, "parse_all", "running", total=len(state["ingest_records"]))
    t0 = time.time()

    parsed = []
    for rec in state["ingest_records"]:
        fp = Path(rec["source_path"])
        suffix = fp.suffix.lower()
        if suffix == ".docx":
            para_count, run_count = _parse_docx(fp)
        elif suffix == ".pdf":
            para_count, run_count = _parse_pdf(fp)
        else:
            para_count, run_count = 0, 0

        parsed.append(
            {
                **rec,
                "para_count": para_count,
                "run_count": run_count,
                "parse_ok": True,
            }
        )
        _emit(state, "parse_all", "running", parsed=fp.name, paras=para_count)

    state["detection_records"] = parsed  # detection will overwrite with detections
    _emit(
        state,
        "parse_all",
        "done",
        files=len(parsed),
        elapsed=round(time.time() - t0, 2),
    )
    return state


def _parse_docx(path: Path) -> tuple[int, int]:
    try:
        from docx import Document

        doc = Document(str(path))
        paras = [p for p in doc.paragraphs if p.text.strip()]
        runs = sum(len(p.runs) for p in paras)
        return len(paras), runs
    except Exception:
        return 0, 0


def _parse_pdf(path: Path) -> tuple[int, int]:
    try:
        import fitz

        doc = fitz.open(str(path))
        page_count = doc.page_count
        span_count = 0
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                if block.get("type", 0) != 0:
                    continue
                for line in block.get("lines", []):
                    span_count += len(line.get("spans", []))
        doc.close()
        return page_count, span_count
    except Exception:
        return 0, 0


# ─────────────────────────────────────────────────────────────────────────────
# Node 3 — detect_references
# ─────────────────────────────────────────────────────────────────────────────


def node_detect_references(state: PipelineState) -> PipelineState:
    """Run the regex → NER → LLM cascade on every uploaded document."""
    from hyperlink_engine.workers.tasks import detect_references as _detect

    _emit(state, "detect_references", "running", total=len(state["ingest_records"]))
    t0 = time.time()

    detection_records = []
    total_refs = 0
    for rec in state["ingest_records"]:
        suffix = Path(rec["source_path"]).suffix.lower()
        if suffix not in (".docx", ".pdf"):
            continue
        try:
            result = _detect(rec)
            detection_records.append(result)
            total_refs += len(result.get("detections", []))
            _emit(
                state,
                "detect_references",
                "running",
                file=rec["filename"],
                refs=len(result.get("detections", [])),
            )
        except Exception as exc:
            _log.warning("detection_failed", file=rec["filename"], error=str(exc))
            detection_records.append({"ingest": rec, "detections": []})

    state["detection_records"] = detection_records
    _emit(
        state,
        "detect_references",
        "done",
        total_references=total_refs,
        files=len(detection_records),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 4 — resolve_targets
# ─────────────────────────────────────────────────────────────────────────────


def node_resolve_targets(state: PipelineState) -> PipelineState:
    """Map detected reference text to target documents in the same upload batch.

    Heuristic: if a reference text contains a Study ID or filename stem that
    matches another uploaded document, treat that document as the target.
    The injection node will build a cross-doc hyperlink pointing to it.
    """
    _emit(state, "resolve_targets", "running")
    t0 = time.time()

    file_index = _build_file_index(state["ingest_records"])

    resolved = 0
    for drec in state["detection_records"]:
        src_path = drec.get("ingest", {}).get("source_path", "")
        for det in drec.get("detections", []):
            target = _resolve_one(det, file_index, src_path)
            det["resolved_target_doc"] = target
            if target:
                resolved += 1

    _emit(
        state,
        "resolve_targets",
        "done",
        resolved=resolved,
        elapsed=round(time.time() - t0, 2),
    )
    return state


def _norm(s: str) -> str:
    """Lowercase, strip everything but alphanumerics — for loose matching."""
    import re as _re

    return _re.sub(r"[^a-z0-9]", "", s.lower())


# Document-type keywords used to route DOC_REF references and tag indexed files.
_DOC_TYPES = ("protocol", "sap", "csr", "listing", "appendix", "iss", "ise")

# Doc-type / structural tokens that can prefix a filename and corrupt study-key
# extraction. e.g. "protocol-sp-2026-001" must key on "sp2026001" — without
# stripping, the ``[a-z]{2,5}`` study-id pattern greedily grabs letters from the
# prefix ("colsp2026001"), so a study's siblings get DIFFERENT keys and DOC_REF
# routing (protocol↔sap↔csr) silently fails. NCT ids are matched first, so this
# never touches them. (PLAN THIRTEEN Fix 1.)
_STUDY_KEY_NOISE = re.compile(
    r"(?:protocol|sap|csr|listings?|appendices|appendix|annex|body|amendment|amd|module|vol)\d*"
)


def _robust_study_key(nstem: str) -> str:
    """Extract a study identifier from a normalized filename stem.

    Naming-scheme-agnostic, tried most-specific-first so production NCT files
    and synthetic sponsor-id CSRs both resolve cleanly:
      ``nct04089566sap`` → ``nct04089566`` · ``csrsp2026002body`` → ``sp2026002``
      · ``protocolsp2026001`` → ``sp2026001`` (all four siblings → same key).
    Falls back to the longest digit run so an unknown scheme still groups by study.
    """
    m = re.search(r"nct\d{8}", nstem)
    if m:
        return m.group(0)
    # Strip doc-type / structural prefix words BEFORE the sponsor-id pattern so a
    # study's protocol/sap/csr/listings siblings all key on the same id. (Fix 1.)
    cleaned = _STUDY_KEY_NOISE.sub("", nstem)
    m = re.search(r"[a-z]{2,5}\d{4}\d{3,4}", cleaned)  # e.g. sp2026002
    if m:
        return m.group(0)
    runs = re.findall(r"\d{4,}", cleaned)
    return max(runs, key=len) if runs else ""


def _doc_type_of(nstem: str) -> str:
    """Classify an indexed file by document type from its normalized stem."""
    for t in _DOC_TYPES:
        if t in nstem:
            return t
    if "statisticalanalysisplan" in nstem or "analysisplan" in nstem:
        return "sap"
    if "clinicalstudyreport" in nstem:
        return "csr"
    return "other"


def _doc_ref_type(text: str) -> str:
    """Map a DOC_REF reference's text to the document type it points at."""
    import re as _re

    t = text.lower()
    if "protocol" in t:
        return "protocol"
    if "statistical analysis plan" in t or _re.search(r"\bsap\b", t):
        return "sap"
    if "clinical study report" in t or _re.search(r"\bcsr\b", t):
        return "csr"
    if "integrated summary of safety" in t or _re.search(r"\biss\b", t):
        return "iss"
    if "integrated summary of efficacy" in t or _re.search(r"\bise\b", t):
        return "ise"
    return ""


# Structural references that can be QUALIFIED by a document name ("SAP Section 6.2").
_STRUCT_LABELS = {"SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"}


def _qualifier_doc_type(det: dict[str, Any]) -> str:
    """The document type that QUALIFIES a structural reference, read from the text
    immediately to its LEFT in context: 'SAP Section 6.2' -> 'sap',
    'Protocol TMX-67_301 Section 6.1' -> 'protocol'. '' when none is adjacent."""
    ctx = det.get("context") or ""
    txt = det.get("text") or ""
    i = ctx.find(txt)
    left = (ctx[:i] if i >= 0 else ctx)[-48:].lower()
    best, best_pos = "", -1
    for kw, dt in (
        ("statistical analysis plan", "sap"),
        ("clinical study report", "csr"),
        ("integrated summary of safety", "iss"),
        ("integrated summary of efficacy", "ise"),
        ("protocol", "protocol"),
        ("sap", "sap"),
        ("csr", "csr"),
        ("iss", "iss"),
        ("ise", "ise"),
    ):
        pos = left.rfind(kw)
        if pos > best_pos:
            best, best_pos = dt, pos
    return best


def _build_file_index(ingest_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Index uploaded files by a normalized study-id key + doc-type hint.

    Each entry: {path, stem, study_key, is_csr_body}. The study_key is the
    normalized study identifier embedded in the filename (e.g. "sp2026002"),
    used to route a reference like "CSR SP-2026-002" to that study's documents.
    """
    import re as _re

    index: list[dict[str, Any]] = []
    for rec in ingest_records:
        path = rec["source_path"]
        stem = Path(path).stem
        nstem = _norm(stem)
        # Study key = the digit core of the study id, e.g. "csr-sp-2026-002-body"
        # → "2026002". Digits-only so a reference "SP-2026-002" (norm "sp2026002")
        # reliably contains it.
        m = _re.search(r"\d{4}\d{2,3}", nstem)
        study_key = m.group(0) if m else ""
        is_csr_body = ("csr" in nstem or "body" in nstem) and "protocol" not in nstem
        index.append(
            {
                "path": path,
                "stem": stem,
                "nstem": nstem,
                "study_key": study_key,
                "is_csr_body": is_csr_body,
                # Naming-scheme-agnostic fields used by the DOC_REF path (PDFs).
                # Kept separate from the legacy study_key so the existing
                # study-id / token routing is byte-for-byte unchanged.
                "study_key_v2": _robust_study_key(nstem),
                "doc_type": _doc_type_of(nstem),
            }
        )
    return index


def _pick_sibling(cands: list[dict[str, Any]], source_path: str) -> str | None:
    """Choose ONE target among several same-doc-type candidates.

    When a batch holds more than one document of the referenced type — e.g. a Word
    ``SAP.docx`` sibling AND a ``clinicaltrials/NCT…_SAP.pdf`` reference copy — a
    bare ``SAP`` / ``SAP Section 5.3`` reference is ambiguous. Rather than guess
    blindly (or silently drop the link), prefer the candidate that shares the
    SOURCE's own file format, then its folder: a Word dossier's internal "SAP"
    cross-reference means the Word SAP that sits beside it, not a PDF in a sub-folder.
    Returns None only when no single preference uniquely identifies a sibling — so the
    "don't guess among several unrelated studies" guard (PLAN THIRTEEN) is preserved
    (N same-format docs in one folder stays unresolved, exactly as before)."""
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]["path"]
    src = Path(source_path)
    src_ext = src.suffix.lower()
    src_dir = str(src.parent).lower()
    same_fmt = [f for f in cands if Path(f["path"]).suffix.lower() == src_ext]
    if len(same_fmt) == 1:
        return same_fmt[0]["path"]
    pool = same_fmt or cands
    same_dir = [f for f in pool if str(Path(f["path"]).parent).lower() == src_dir]
    if len(same_dir) == 1:
        return same_dir[0]["path"]
    return None


def _resolve_one(
    det: dict[str, Any],
    file_index: list[dict[str, Any]],
    source_path: str,
) -> str | None:
    """Resolve a detected reference to the most specific target document.

    Strategy:
      1. Prefer a study-key match (e.g. reference "SP-2026-002" → a doc whose
         filename carries study key "2026002"). When several docs share the
         study, prefer that study's CSR body as the canonical target.
      2. Fall back to scoring filename tokens that appear in the reference text.
    Never resolves a reference to its own source document.

    A table / section reference ("Table 14.1.1.1", "Section 2.3") usually
    carries no study id or doc-type in its own link text — the qualifier
    ("… in CSR SP-2026-003") lives in the surrounding sentence. We therefore
    resolve against the reference text *plus* its surrounding ``context`` so
    such a reference routes to the document that actually holds the table /
    section (the CSR) instead of self-anchoring in the source doc.
    """
    text = _norm(det.get("text", ""))
    if not text:
        return None
    src_stem = Path(source_path).stem if source_path else ""
    label = det.get("label")
    groups = det.get("groups", {})

    # ── External citations are ALWAYS external, never cross-document. A registry
    #    NCT id → clinicaltrials.gov; ICH/CFR/DOI/Helsinki → their public URLs
    #    (wired in tasks._resolve_target). Guard here so they can never be
    #    re-routed to a same-batch sibling document. ───────────────────────────
    if label == "STUDY_ID" and det.get("pattern_id") == "STUDY_ID_NCT_V1":
        return None
    if label in ("EXT_REF", "URL"):
        return None

    # ── DOC_REF / DOC_ID routing: "the protocol" / "TMX-67_301" → the same
    #    study's sibling Protocol. A doc-type reference carries no study id in its
    #    own text; the study identity comes from the SOURCE document. The doc type
    #    comes from a compound qualifier ("Protocol TMX-67_301 …" stamps
    #    'protocol' onto the id piece) first, else from the reference's own words. ─
    if label in ("DOC_REF", "DOC_ID"):
        dt = groups.get("compound_qual_dt") or (
            _doc_ref_type(det.get("text", "")) if label == "DOC_REF" else ""
        )
        if dt:
            src_key = _robust_study_key(_norm(src_stem))
            # Self-type reference: a bare "SAP"/"CSR" INSIDE the SAP/CSR itself refers
            # to THIS document ("this Statistical Analysis Plan (SAP) describes…"), so
            # it must NOT be routed to a *different* same-type file in the batch (e.g.
            # another study's NCT…_SAP.pdf). Drop it as a self-reference UNLESS a
            # same-study sibling of that type exists (a genuine, study-keyed cross-ref).
            if _doc_type_of(_norm(src_stem)) == dt:
                same_study_self = [
                    f
                    for f in file_index
                    if f["doc_type"] == dt
                    and f["stem"] != src_stem
                    and f["study_key_v2"]
                    and src_key
                    and f["study_key_v2"] == src_key
                ]
                if same_study_self:
                    return same_study_self[0]["path"]
                # No same-type sibling → this is a self-reference. Normally unlinked,
                # but when the AUTHOR highlighted it the injector links it to THIS
                # document's own top (parity with an adjacent cross-ref). Flag it;
                # the target stays None so it's never routed to another document.
                if det.get("is_highlighted"):
                    det["self_ref_top"] = True
                return None
            same_study = [
                f
                for f in file_index
                if f["doc_type"] == dt
                and f["stem"] != src_stem
                and f["study_key_v2"]
                and f["study_key_v2"] == src_key
            ]
            if same_study:
                return same_study[0]["path"]
            # No same-study sibling: resolve if exactly one doc of that type exists,
            # or — when several do — the one matching the source's format/folder
            # (avoids guessing among several unrelated studies; a mixed docx+pdf batch
            # routes a Word "SAP" to the Word SAP, not a clinicaltrials PDF copy).
            typed = [f for f in file_index if f["doc_type"] == dt and f["stem"] != src_stem]
            return _pick_sibling(typed, source_path)
        if label == "DOC_REF":
            # A doc-type reference with no recognizable type is not a link.
            return None
        # A bare DOC_ID with no doc-type qualifier ("TMX-67_301" on its own) falls
        # through to token-overlap scoring below, so an id that names an uploaded
        # file still resolves (file-gated — an id with no matching file is dropped).

    # Does the reference's OWN text already name a study id? A bare "SP-2026-003"
    # cite does; a "Table 14.1.1.1" / "Section 2.3" cite does not. We only fold
    # in the surrounding sentence (`context`) for the latter — so the study-id
    # path keeps its exact prior behavior and is never contaminated by other
    # studies mentioned elsewhere in the same paragraph.
    text_has_study = any(f["study_key"] and f["study_key"] in text for f in file_index)
    if text_has_study:
        search = text
    else:
        # Table/Section cite: route using text + surrounding run/sentence, e.g.
        # "Table 14.1.1.1 in CSR SP-2026-003" → that study's CSR body.
        search = text + _norm(det.get("context", ""))

    # 1) Study-key routing.
    src_nstem = _norm(src_stem)
    doctypes = ["protocol", "sap", "listing", "appendix", "csr", "iss", "ise"]
    # Which doc-type does the reference (or, for table/section cites, its
    # surrounding sentence) name? "CSR SP-2026-002" → ["csr"].
    named = [kw for kw in doctypes if kw in search]

    study_matches = [
        f for f in file_index
        if f["study_key"] and f["study_key"] in search and f["stem"] != src_stem
    ]
    if study_matches:
        if named:
            # Keep only candidates whose filename matches a named doc-type, so a
            # "CSR …" cite never lands on that study's Listings/SAP/etc.
            typed = [f for f in study_matches if any(kw in f["nstem"] for kw in named)]
            if typed:
                typed.sort(key=lambda f: 10 if f["is_csr_body"] else 0, reverse=True)
                return typed[0]["path"]
            # The only doc of the named type is the *source itself* (e.g. a
            # "CSR SP-2026-002 Section 2.7" cite written inside CSR 2026-002):
            # this is an internal reference — keep it in-document, do NOT route
            # it to an unrelated same-study doc.
            if any(kw in src_nstem for kw in named):
                return None
            # Named type isn't present anywhere → fall through to token scoring.
        else:
            # Bare study id → that study's CSR body is the canonical target.
            csr_bodies = [f for f in study_matches if f["is_csr_body"]]
            if csr_bodies:
                return csr_bodies[0]["path"]
            # The CSR body is the source itself → internal reference.
            if "csr" in src_nstem or "body" in src_nstem:
                return None

    # 1b) Cross-doc QUALIFIED structural reference: "SAP Section 6.2",
    #     "Protocol … Section 6.1" — the section/table is qualified by a doc-type
    #     word right before it, so route to that sibling document (the injector then
    #     carries the section sub-anchor, e.g. SAP_linked.docx#section_ref_6_2).
    #     Gated to run only after study-key routing found nothing, so the synthetic
    #     CSR (study-keyed) behavior is untouched. Dynamic: any <DocType> + section
    #     ref with exactly one matching sibling (or a same-study sibling) routes.
    if label in _STRUCT_LABELS:
        # A compound phrase ("Protocol TMX-67_301 Section 6.1") stamps the
        # qualifier doc-type onto the section even when Word split the doc-type
        # word into a different run — so the section routes to the SAME sibling
        # everywhere (fixes "same citation, different destination" across docs).
        qdt = groups.get("compound_qual_dt") or _qualifier_doc_type(det)
        if qdt:
            sk = _robust_study_key(src_nstem)
            same = [
                f
                for f in file_index
                if f["doc_type"] == qdt
                and f["stem"] != src_stem
                and f["study_key_v2"]
                and f["study_key_v2"] == sk
            ]
            if same:
                return same[0]["path"]
            typed = [f for f in file_index if f["doc_type"] == qdt and f["stem"] != src_stem]
            picked = _pick_sibling(typed, source_path)
            if picked:
                return picked

    # 2) Token-overlap scoring fallback. An id-routed compound DOC_ID carries the
    #    WHOLE phrase as its text (so the link/preview box spans the continuous
    #    reference), but it must be matched by the bare id alone (`compound_id_token`)
    #    — otherwise the trailing "Section 6.1"/"Study"/"ID" words skew the file
    #    match. With the token present this reproduces the pre-compound id routing
    #    exactly; without it (every other reference) `text` is used as before.
    route_text = _norm(groups.get("compound_id_token") or "") or text
    best: tuple[int, str] | None = None
    for f in file_index:
        if f["stem"] == src_stem:
            continue
        score = 0
        for tok in f["stem"].replace("-", " ").replace("_", " ").split():
            nt = _norm(tok)
            if len(nt) >= 3 and nt in route_text:
                score += len(nt)
        if score >= 4 and (best is None or score > best[0]):
            best = (score, f["path"])
    return best[1] if best else None


# ─────────────────────────────────────────────────────────────────────────────
# Node 5 — inject_links
# ─────────────────────────────────────────────────────────────────────────────


def node_inject_links(state: PipelineState) -> PipelineState:
    """Inject hyperlinks into each document using the existing inject_links task."""
    from hyperlink_engine.core.injection.anchor_index import build_anchor_index
    from hyperlink_engine.workers.tasks import inject_links as _inject

    output_dir: Path = state["output_dir"]
    _emit(state, "inject_links", "running", total=len(state["detection_records"]))
    t0 = time.time()

    # PLAN TEN: pre-build the anchor index (definition locations) for every doc in
    # the run, so each injection can (a) anchor internal links at the real
    # caption/heading and (b) target the exact heading in a *sibling* document for
    # cross-doc links. Best-effort: a build failure yields an empty index → the
    # injector falls back to citation-anchored links (legacy behavior).
    anchor_indexes: dict[str, dict[str, Any]] = {}
    for drec in state["detection_records"]:
        s = Path(drec["ingest"]["source_path"])
        try:
            anchor_indexes[s.stem] = build_anchor_index(
                drec["detections"], str(s), is_pdf=(s.suffix.lower() == ".pdf")
            )
        except Exception as exc:  # noqa: BLE001 — never break the run
            _log.warning("anchor_index_build_failed", source=str(s), error=str(exc))
            anchor_indexes[s.stem] = {}

    # Cross-doc bookmark provisioning: a document only declares bookmarks for the
    # anchors IT cites, but a sibling may link into a section this document merely
    # DEFINES (Protocol defines §6.1; CSR/ISE/ISS/SAP link to it). Collect, per
    # target document, every anchor key another document links INTO it (and that the
    # target actually defines) so the target declares those bookmarks — otherwise the
    # cross-doc link opens the file but can't scroll.
    from hyperlink_engine.workers.tasks import _resolve_target as _resolve_target_key

    incoming_anchors: dict[str, set[str]] = {}
    for drec in state["detection_records"]:
        src = Path(drec["ingest"]["source_path"])
        for det in drec["detections"]:
            rtd = det.get("resolved_target_doc")
            if not rtd:
                continue
            rt = Path(rtd)
            if rt.stem == src.stem or rt.suffix.lower() != ".docx":
                continue
            _kind, key = _resolve_target_key(det)
            if not key or key in ("doc_ref", "doc_id") or key.startswith("http"):
                continue
            if key in anchor_indexes.get(rt.stem, {}):
                incoming_anchors.setdefault(rt.stem, set()).add(key)

    injection_records = []
    linked_files = []

    for drec in state["detection_records"]:
        source = Path(drec["ingest"]["source_path"])
        out_path = output_dir / (source.stem + "_linked" + source.suffix)
        try:
            result = _inject(
                drec,
                output_path=str(out_path),
                target_anchor_indexes=anchor_indexes,
                incoming_anchor_keys=incoming_anchors.get(source.stem),
            )
            injection_records.append(result)
            linked_files.append(out_path)
            _emit(
                state,
                "inject_links",
                "running",
                file=source.name,
                links=len(result.get("probes", [])),
            )
        except Exception as exc:
            _log.warning("injection_failed", file=source.name, error=str(exc))
            # Fall back: copy original so the file exists
            shutil.copy2(source, out_path)
            injection_records.append({"ingest": drec["ingest"], "output_path": str(out_path), "probes": []})
            linked_files.append(out_path)

    state["injection_records"] = injection_records
    state["linked_files"] = linked_files
    _emit(
        state,
        "inject_links",
        "done",
        linked_files=len(linked_files),
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 6 — validate
# ─────────────────────────────────────────────────────────────────────────────


def _docx_bookmark_names(path: Path) -> set[str] | None:
    """Every bookmark name declared in a .docx, or None if it is not a readable
    .docx (a PDF target, a missing file, or a corrupt one) — in which case the
    caller treats the anchor as *unverified* rather than broken."""
    if path.suffix.lower() != ".docx" or not path.exists():
        return None
    try:
        from docx import Document as _Docx
        from docx.oxml.ns import qn

        doc = _Docx(str(path))
        return {
            b.get(qn("w:name"))
            for b in doc.element.body.iter(qn("w:bookmarkStart"))
            if b.get(qn("w:name"))
        }
    except Exception:  # noqa: BLE001 — an unreadable target never crashes validation
        return None


def node_validate(state: PipelineState) -> PipelineState:
    """Validate every injected link against the REAL output and record its true
    status, so the readiness score reflects reality instead of a hard-coded "ok".

    * external web link  → valid scheme + host (no network probe, per on-prem mandate)
    * cross-document     → the "file#anchor" target file exists under output_dir AND
                           the bookmark exists in it (a bare "file" opens at the top)
    * internal bookmark  → the anchor exists in this document's own linked output
    A PDF / unreadable target is UNVERIFIED (never counted broken).
    """
    _emit(state, "validate", "running")
    t0 = time.time()

    output_dir = state.get("output_dir")
    _bm_cache: dict[str, set[str] | None] = {}

    def _bookmarks(path: Path) -> set[str] | None:
        key = str(path)
        if key not in _bm_cache:
            _bm_cache[key] = _docx_bookmark_names(path)
        return _bm_cache[key]

    def _validate(p: dict[str, Any], link_kind: str, target: str) -> tuple[str, str | None]:
        if link_kind == "external_url":
            low = target.lower()
            if low.startswith(("http://", "https://")) and "." in target:
                return "ok", None
            return "broken", "invalid external URL"
        if link_kind == "cross_doc":
            file_part, _, frag = target.partition("#")
            if not output_dir or not file_part:
                return "unverified", "cannot resolve cross-doc target"
            tgt = Path(output_dir) / file_part
            if not tgt.exists():
                return "broken", f"target document {file_part} not found"
            if not frag:
                return "ok", None  # opens the document at the top — valid
            bms = _bookmarks(tgt)
            if bms is None:
                return "unverified", "cross-doc target is not a readable docx"
            return ("ok", None) if frag in bms else ("broken", f"bookmark {frag!r} missing in {file_part}")
        # internal bookmark → this document's own linked output
        tdoc_raw = p.get("target_doc", "")
        if not tdoc_raw:
            return "unverified", "no target document"
        tpath = Path(tdoc_raw)
        if not tpath.exists():
            return "broken", f"target document {tpath.name} not found"
        bms = _bookmarks(tpath)
        if bms is None:
            return "unverified", "target is not a readable docx"
        return ("ok", None) if target in bms else ("broken", f"bookmark {target!r} missing")

    links: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for irec in state["injection_records"]:
        src = Path(irec["ingest"]["source_path"]).name
        for p in irec.get("probes", []):
            target = str(p.get("target", "") or "")
            # The docx injector wires BOTH true web links and cross-document refs as
            # external relationships, so a cross-doc probe also has kind
            # "external_url" even though its target is a filename. Re-classify so the
            # rule stays clean: link_kind == "external_url" ⇔ a real http(s) website.
            link_kind = p.get("kind", "internal_bookmark")
            if link_kind == "external_url" and not target.lower().startswith(
                ("http://", "https://")
            ):
                link_kind = "cross_doc"
            status, err = _validate(p, link_kind, target)
            links.append(
                {
                    "source_doc": p.get("source_doc", src),
                    "link_text": p.get("link_text", ""),
                    "link_location_descriptor": p.get("location_descriptor", ""),
                    "target_doc": p.get("target_doc", ""),
                    "target_anchor": target,
                    "link_kind": link_kind,
                    # PLAN TWELVE: 1-based page of the reference in the document the
                    # link opens, so the UI can open that PDF at #page=N (None ⇒ p1).
                    "target_page": p.get("target_page"),
                    "status": status,
                    "confidence": float(
                        p.get("llm_confidence_after") or p.get("llm_confidence_before") or 0.9
                    ),
                    "error_msg": err,
                    "detected_by": p.get("detected_by", "regex"),
                }
            )
            results.append(
                {
                    "source_doc": p.get("source_doc", src),
                    "link_text": p.get("link_text", ""),
                    "target_anchor": target,
                    "link_kind": link_kind,
                    "status": status,
                    "error_msg": err,
                }
            )

    broken = sum(1 for r in results if r["status"] == "broken")
    unverified = sum(1 for r in results if r["status"] == "unverified")
    state["links"] = links
    state["validation_results"] = {
        "checked": len(results),
        "broken": broken,
        "unverified": unverified,
        "results": results,
    }
    _emit(
        state,
        "validate",
        "done",
        links_checked=len(results),
        broken=broken,
        unverified=unverified,
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 7 — score_and_report
# ─────────────────────────────────────────────────────────────────────────────


def node_score_and_report(state: PipelineState) -> PipelineState:
    """Compute submission readiness score + write CSV report."""
    _emit(state, "score_and_report", "running")
    t0 = time.time()

    links = state.get("links", [])
    total = len(links)
    broken = sum(1 for l in links if l.get("status") == "broken")

    score = max(0.0, min(100.0, 100.0 - broken * 5.0)) if total else 85.0
    grade = "A" if score >= 95 else "B" if score >= 85 else "C" if score >= 70 else "F"

    state["score"] = round(score, 1)
    state["grade"] = grade

    # Write CSV
    try:
        import csv
        csv_path = state["output_dir"] / "validation_report.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            fieldnames = [
                "source_doc", "link_text", "link_location_descriptor",
                "target_doc", "target_anchor", "status", "confidence",
                "detected_by", "error_msg",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(links)
    except Exception as exc:
        _log.warning("csv_write_failed", error=str(exc))

    _emit(
        state,
        "score_and_report",
        "done",
        score=score,
        grade=grade,
        total_links=total,
        broken=broken,
        elapsed=round(time.time() - t0, 2),
    )
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 8a — push_dossplorer
# ─────────────────────────────────────────────────────────────────────────────


def node_push_dossplorer(state: PipelineState) -> PipelineState:
    """Push readiness score to Dossplorer (mock client)."""
    _emit(state, "push_dossplorer", "running")
    try:
        from hyperlink_engine.core.ingestion.dossplorer_client import (
            MockDossplorerClient,
            get_client,
        )
        client = get_client()
        dossier_id = state["dossier_id"]
        # Auto-register the dossier in the mock client if it's unknown
        if isinstance(client, MockDossplorerClient):
            if dossier_id not in client._dossiers:
                from hyperlink_engine.models import DossierMetadata
                client._dossiers[dossier_id] = DossierMetadata(
                    dossier_id=dossier_id,
                    sponsor="SunPharma",
                    submission_type="NDA",
                    region="US",
                    sequence_number="0001",
                    status="in_review",
                )
        client.push_readiness_score(dossier_id, state["score"])
        _emit(state, "push_dossplorer", "done", score=state["score"])
    except Exception as exc:
        # Non-fatal: Dossplorer push failure doesn't fail the pipeline
        _log.warning("push_dossplorer_failed", error=str(exc))
        _emit(state, "push_dossplorer", "error", error=str(exc))
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Node 8b — flag_for_review
# ─────────────────────────────────────────────────────────────────────────────


def node_flag_for_review(state: PipelineState) -> PipelineState:
    """Log anomalies and set status to 'needs_review'."""
    _emit(state, "flag_for_review", "running")
    anomalies = state.get("anomalies", [])
    _log.info(
        "pipeline_flagged_for_review",
        run_id=state["run_id"],
        score=state.get("score"),
        anomalies=len(anomalies),
    )
    _emit(state, "flag_for_review", "done", anomalies=len(anomalies), score=state.get("score"))
    return state
