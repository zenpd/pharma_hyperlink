"""PLAN TWELVE — the injector stamps ``target_page`` onto each PDF probe so the
UI can open the target PDF in a new tab at ``#page=N`` (scroll-to-reference).

* Internal links → the 1-based page of the reference's *definition* in THIS
  document (falls back to the citation's own page when no definition is indexed).
* Cross-doc links → the page of the reference in the *sibling* document's anchor
  index, keyed by the reference's canonical key.
* A whole-document reference ("the protocol", ``DOC_REF``) has no specific page →
  ``target_page is None`` so the UI opens that PDF at page 1.
"""

from __future__ import annotations

from pathlib import Path

from hyperlink_engine.workers.tasks import _inject_links_pdf


def _make_pdf(path: Path, pages: int = 3) -> None:
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), "Section 2.5 and Table 3 are discussed here", fontsize=12)
    doc.save(str(path))
    doc.close()


def _det(label, text, num, page, **extra):
    d = {
        "label": label,
        "text": text,
        "groups": {"num": num} if num is not None else {},
        "page_index": page,
        "bbox": [72.0, 90.0, 200.0, 110.0],
        "char_start": 0,
        "char_end": len(text),
        "span_index": 0,
        "source_layer": "regex",
    }
    d.update(extra)
    return d


def test_inject_pdf_stamps_target_page(tmp_path: Path) -> None:
    src = tmp_path / "NCT99_SAP.pdf"
    _make_pdf(src, pages=3)
    sibling = tmp_path / "NCT99_Protocol.pdf"  # only the path is needed (cross-doc URL)

    # Definition locations: this doc's Section 2.5 is on page 2; the sibling
    # Protocol's Table 3 is on page 4 (both 0-based → target_page 3 and 5).
    target_anchor_indexes = {
        src.stem: {"section_ref_2_5": {"page_index": 2, "bbox": [72.0, 90.0, 200.0, 110.0]}},
        "NCT99_Protocol": {"table_ref_3": {"page_index": 4, "bbox": None}},
    }

    dets = [
        # internal section ref: cited on page 0, defined on page 2 → target_page 3
        _det("SECTION_REF", "Section 2.5", "2.5", 0),
        # cross-doc table ref → sibling Protocol's page 4 → target_page 5
        _det("TABLE_REF", "Table 3", "3", 1, resolved_target_doc=str(sibling)),
        # cross-doc whole-document ref → no specific page → None (UI opens at p1)
        _det("DOC_REF", "the protocol", None, 2, resolved_target_doc=str(sibling)),
    ]
    rec = {"ingest": {"source_path": str(src)}, "detections": dets}

    result = _inject_links_pdf(
        rec, output_path=tmp_path / "NCT99_SAP_linked.pdf",
        target_anchor_indexes=target_anchor_indexes,
    )
    probes = {p["link_text"]: p for p in result["probes"]}

    assert probes["Section 2.5"]["target_page"] == 3      # definition page (0-based 2) + 1
    assert probes["Table 3"]["target_page"] == 5          # sibling's table_ref_3 (page 4) + 1
    assert probes["the protocol"]["target_page"] is None  # whole-document ref → page 1


def test_internal_link_falls_back_to_citation_page(tmp_path: Path) -> None:
    """When a reference has no indexed definition, the page falls back to the
    citation's own page (so the link still lands somewhere sensible)."""
    src = tmp_path / "NCT99_SAP.pdf"
    _make_pdf(src, pages=3)

    # Empty index for this doc → Section 2.5 has no definition entry.
    rec = {
        "ingest": {"source_path": str(src)},
        "detections": [_det("SECTION_REF", "Section 2.5", "2.5", 1)],  # cited on page 1
    }
    result = _inject_links_pdf(
        rec, output_path=tmp_path / "out_linked.pdf",
        target_anchor_indexes={src.stem: {}},
    )
    probe = result["probes"][0]
    assert probe["target_page"] == 2  # citation page (0-based 1) + 1


def test_node_validate_carries_target_page() -> None:
    """The LINKED DOCUMENTS dropdown reads ``link["target_page"]`` (and ``link_kind``)
    off the link dict. Lock that ``node_validate`` copies ``target_page`` from the probe
    into that dict, and reclassifies a cross-doc external probe (external_url + filename
    target) to ``cross_doc`` so the UI's external-vs-document rule stays clean."""
    from hyperlink_engine.orchestration.nodes import node_validate

    state = {
        "run_id": "test-run",
        "injection_records": [
            {
                "ingest": {"source_path": "/tmp/NCT99_SAP.pdf"},
                "probes": [
                    # internal ref → its definition page in THIS doc
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "Section 2.5",
                        "target": "section_ref_2_5", "target_doc": "NCT99_SAP_linked.pdf",
                        "kind": "internal_bookmark", "target_page": 3,
                    },
                    # cross-doc ref → the sibling's page (carried from the sibling index)
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "Table 3",
                        "target": "NCT99_Protocol_linked.pdf", "target_doc": "NCT99_Protocol_linked.pdf",
                        "kind": "external_url", "target_page": 5,
                    },
                    # whole-document ref → no specific page (UI opens at page 1)
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "the protocol",
                        "target": "NCT99_Protocol_linked.pdf", "target_doc": "NCT99_Protocol_linked.pdf",
                        "kind": "external_url", "target_page": None,
                    },
                ],
            }
        ],
    }

    node_validate(state)  # type: ignore[arg-type]
    links = {l["link_text"]: l for l in state["links"]}

    assert links["Section 2.5"]["target_page"] == 3
    assert links["Section 2.5"]["link_kind"] == "internal_bookmark"
    assert links["Table 3"]["target_page"] == 5
    assert links["Table 3"]["link_kind"] == "cross_doc"   # external_url + filename → reclassified
    assert links["the protocol"]["target_page"] is None


def test_node_validate_pdf_links_verify_by_page(tmp_path: Path) -> None:
    """PDF links are page-level GoTo jumps, not docx bookmarks. ``node_validate``
    must verify them by page so valid PDF links read ``ok`` instead of the old
    blanket ``unverified`` — while keeping the worst case at ``unverified`` (never a
    false ``broken``) and still flagging a genuinely missing target file as broken.

    Regression guard: the Word/docx path is unchanged; only ``.pdf`` targets take the
    new branch (the file must exist first, so this never relocates a working anchor).
    """
    from hyperlink_engine.orchestration.nodes import node_validate

    pdf = tmp_path / "NCT99_SAP_linked.pdf"
    _make_pdf(pdf, pages=3)

    state = {
        "run_id": "test-run",
        "output_dir": str(tmp_path),
        "injection_records": [
            {
                "ingest": {"source_path": str(tmp_path / "NCT99_SAP.pdf")},
                "probes": [
                    # internal PDF link, target page in range → OK (was unverified)
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "Section 2.5",
                        "target": "section_ref_2_5", "target_doc": str(pdf),
                        "kind": "internal_bookmark", "target_page": 2,
                    },
                    # whole-doc PDF link, opens at top (page 1) → OK
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "the protocol",
                        "target": "section_ref_x", "target_doc": str(pdf),
                        "kind": "internal_bookmark", "target_page": None,
                    },
                    # target page beyond the file → unverified, NEVER a false broken
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "Section 9.9",
                        "target": "section_ref_9_9", "target_doc": str(pdf),
                        "kind": "internal_bookmark", "target_page": 99,
                    },
                    # genuinely missing target file → broken
                    {
                        "source_doc": "NCT99_SAP.pdf", "link_text": "Gone",
                        "target": "section_ref_1", "target_doc": str(tmp_path / "missing.pdf"),
                        "kind": "internal_bookmark", "target_page": 1,
                    },
                ],
            }
        ],
    }

    node_validate(state)  # type: ignore[arg-type]
    status = {l["link_text"]: l["status"] for l in state["links"]}

    assert status["Section 2.5"] == "ok"       # in-range page → verified (the fix)
    assert status["the protocol"] == "ok"      # opens at page 1 → valid
    assert status["Section 9.9"] == "unverified"  # out of range → never false-broken
    assert status["Gone"] == "broken"          # missing file is still a real failure
