"""Tests for the per-document anchor index (PLAN TEN — precise reference targeting)."""

from __future__ import annotations

import pytest

from hyperlink_engine.core.injection.anchor_index import (
    _caption_def_num,
    _is_caption_definition,
    _is_toc_line,
    _section_heading_num,
    _section_num,
    build_anchor_index,
    canonical_anchor_key,
)
from hyperlink_engine.workers.tasks import _resolve_target


# ── canonical key parity with the injector's _resolve_target ────────────────


def test_canonical_key_shape():
    assert canonical_anchor_key("TABLE_REF", "14.2.1.1") == "table_ref_14_2_1_1"
    assert canonical_anchor_key("SECTION_REF", "6.3") == "section_ref_6_3"
    assert canonical_anchor_key("APPENDIX_REF", "B") == "appendix_ref_B"


def test_canonical_key_matches_resolve_target():
    """The definition key must equal the citation key, or links never connect."""
    det = {
        "label": "TABLE_REF",
        "text": "Table 14.2.1.1",
        "groups": {"num": "14.2.1.1"},
        "pattern_id": "TABLE_REF_NUMBERED_V1",
    }
    _kind, citation_key = _resolve_target(det)
    assert citation_key == canonical_anchor_key("TABLE_REF", "14.2.1.1")


# ── definition vs citation discrimination ───────────────────────────────────


def test_caption_definition_accepts_real_captions():
    assert _is_caption_definition("Table 14.2.1.1: Subject Demographics", "TABLE_REF")
    assert _is_caption_definition("Table 14.2.1.1", "TABLE_REF")  # number alone in its run
    assert _is_caption_definition("Figure 11 — Kaplan-Meier Curve", "FIGURE_REF")
    assert _is_caption_definition("Appendix B Schedule of Assessments", "APPENDIX_REF")


def test_caption_definition_rejects_citations():
    assert not _is_caption_definition("as shown in Table 14.2.1.1 the data", "TABLE_REF")
    assert not _is_caption_definition("see Table 1", "TABLE_REF")
    assert not _is_caption_definition("Table 1 shows the demographics", "TABLE_REF")  # lower-case verb
    assert not _is_caption_definition("refer to Appendix B for details", "APPENDIX_REF")


def test_section_num_parsing():
    assert _section_num("6.3 Statistical Methods") == "6.3"
    assert _section_num("Section 6.3 Analysis") == "6.3"
    assert _section_num("6 SAFETY") == "6"
    assert _section_num("No number here") is None


# ── index construction from detections ──────────────────────────────────────


def _det(label, text, num, *, page=None, para=None, context=None, is_caption=False):
    ctx = context if context is not None else (text if is_caption else f"see {text} for data")
    d = {"label": label, "text": text, "groups": {"num": num}, "context": ctx}
    if page is not None:
        d["page_index"] = page
        d["bbox"] = [72.0, 100.0, 300.0, 112.0]
    if para is not None:
        d["paragraph_index"] = para
    return d


def test_build_index_pdf_captures_definitions_not_citations():
    detections = [
        _det("TABLE_REF", "Table 1", "1", page=5, context="see Table 1 above"),   # citation
        _det("TABLE_REF", "Table 1", "1", page=40, is_caption=True, context="Table 1: Demographics"),  # definition
        _det("TABLE_REF", "Table 1", "1", page=88, context="as in Table 1"),       # citation
    ]
    idx = build_anchor_index(detections, "nonexistent.pdf", is_pdf=True)
    assert "table_ref_1" in idx
    # First *definition* wins — page 40, not the earlier citation on page 5.
    assert idx["table_ref_1"]["page_index"] == 40


def test_build_index_docx_records_paragraph():
    detections = [
        _det("FIGURE_REF", "Figure 2", "2", para=12, is_caption=True, context="Figure 2: Trial Profile"),
    ]
    idx = build_anchor_index(detections, "nonexistent.docx", is_pdf=False)
    assert idx["figure_ref_2"]["paragraph_index"] == 12


def test_build_index_ignores_pure_citations():
    detections = [
        _det("TABLE_REF", "Table 9", "9", page=3, context="values in Table 9 confirm"),
    ]
    idx = build_anchor_index(detections, "nonexistent.pdf", is_pdf=True)
    assert "table_ref_9" not in idx  # no definition seen → no anchor (falls back at inject)


def test_build_index_first_definition_wins():
    detections = [
        _det("APPENDIX_REF", "Appendix A", "A", page=10, is_caption=True, context="Appendix A: Protocol"),
        _det("APPENDIX_REF", "Appendix A", "A", page=99, is_caption=True, context="Appendix A: Duplicate"),
    ]
    idx = build_anchor_index(detections, "nonexistent.pdf", is_pdf=True)
    assert idx["appendix_ref_A"]["page_index"] == 10


# ── PLAN TEN-bis: case-tolerance, ToC exclusion, number normalisation ────────


def test_caption_def_num_case_insensitive_allcaps_heading():
    # Real clinical headings are all-caps; the citation regex is case-sensitive and
    # never fires on them, so the index must recognise them itself.
    assert _caption_def_num("APPENDIX A. Derivation of the Dates", "APPENDIX_REF") == "A"
    assert _caption_def_num("APPENDIX B.", "APPENDIX_REF") == "B"
    assert _caption_def_num("TABLE 19 Summary of Lab Abnormalities", "TABLE_REF") == "19"


def test_caption_def_num_appendix_letter_normalised_to_match_citation():
    # A lone appendix letter must upper-case so the definition key equals the
    # citation key (APPENDIX_REF_LETTER_V1 emits [A-Z]); else links never connect.
    assert _caption_def_num("appendix b Schedule of Assessments", "APPENDIX_REF") == "B"
    _kind, citation_key = _resolve_target(
        {"label": "APPENDIX_REF", "text": "Appendix B", "groups": {"num": "B"},
         "pattern_id": "APPENDIX_REF_LETTER_V1"}
    )
    assert canonical_anchor_key("APPENDIX_REF", _caption_def_num("APPENDIX B.", "APPENDIX_REF")) == citation_key


def test_is_toc_line_detects_dot_leaders():
    assert _is_toc_line("Table 5: Demographics .......... 42")
    assert _is_toc_line("APPENDIX A. ………… 124")  # unicode ellipsis leader
    assert _is_toc_line("Section 6.3 Statistical Methods . . . . . 88")
    assert not _is_toc_line("Table 5: Demographics and Baseline Characteristics")


def test_caption_def_num_rejects_toc_lines():
    # A List-of-Tables entry repeats the caption but must not become the anchor.
    assert _caption_def_num("Table 5: Demographics .......... 42", "TABLE_REF") is None
    assert _caption_def_num("APPENDIX A. ............... 124", "APPENDIX_REF") is None


def test_caption_def_num_rejects_long_prose_starting_with_keyword():
    prose = "Table 1 Summary statistics were computed for every visit " + ("x " * 90)
    assert len(prose) > 200
    assert _caption_def_num(prose, "TABLE_REF") is None  # running sentence, not a caption


def test_caption_def_num_listing_with_dash_title():
    assert _caption_def_num("Listing 16.2 — Adverse Events by Subject", "LISTING_REF") == "16.2"


# ── PLAN TEN-bis: structure scan recovers definitions the detector missed ────


def test_docx_scan_recovers_allcaps_and_run_fragmented_captions(tmp_path):
    docx = pytest.importorskip("docx")
    Document = docx.Document
    doc = Document()
    doc.add_paragraph("Intro paragraph with no references.")           # p0
    doc.add_paragraph("APPENDIX A. Derivation of the Dates")           # p1 all-caps heading
    p = doc.add_paragraph()                                            # p2 fragmented caption
    p.add_run("Table ")
    p.add_run("14.2.1.1")
    p.add_run(": Subject Demographics")
    doc.add_paragraph("Table 9: Old Layout ............... 5")         # p3 ToC line (excluded)
    path = tmp_path / "scan.docx"
    doc.save(str(path))

    # No detections at all → only the structure scan can populate these.
    idx = build_anchor_index([], str(path), is_pdf=False)
    assert idx["appendix_ref_A"]["paragraph_index"] == 1
    assert idx["table_ref_14_2_1_1"]["paragraph_index"] == 2
    assert "table_ref_9" not in idx  # ToC line must never be picked as a definition


def test_pdf_scan_recovers_caption_and_excludes_toc(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "scan.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 700), "Table 3 ................... 9")        # ToC line, page 0
    page2 = doc.new_page()
    page2.insert_text((72, 100), "APPENDIX B. Schedule of Assessments")  # real heading, page 1
    doc.save(str(path))
    doc.close()

    idx = build_anchor_index([], str(path), is_pdf=True)
    assert "table_ref_3" not in idx                      # ToC excluded
    assert idx["appendix_ref_B"]["page_index"] == 1      # heading on page 1
    assert idx["appendix_ref_B"]["bbox"] is not None     # caption line rectangle captured


def test_scan_never_overrides_a_definition_from_detections(tmp_path):
    docx = pytest.importorskip("docx")
    Document = docx.Document
    doc = Document()
    doc.add_paragraph("filler")                                   # p0
    doc.add_paragraph("Table 7: Real Caption In Body")            # p1 (scan would find here)
    path = tmp_path / "nooverride.docx"
    doc.save(str(path))

    # A detection already pinned table_ref_7 to paragraph 5; the additive scan
    # must NOT relocate it (first definition wins).
    dets = [_det("TABLE_REF", "Table 7", "7", para=5, is_caption=True, context="Table 7: Pinned")]
    idx = build_anchor_index(dets, str(path), is_pdf=False)
    assert idx["table_ref_7"]["paragraph_index"] == 5


# ── PLAN TEN-bis: section-heading shape gate (precision-critical) ────────────


def test_section_heading_num_accepts_real_headings():
    assert _section_heading_num("6.3 Statistical Methods") == "6.3"
    assert _section_heading_num("5.2. Participant Accountability") == "5.2"
    assert _section_heading_num("2.7.3 Clinical Summary") == "2.7.3"


def test_section_heading_num_rejects_numbered_sentences_and_footnotes():
    # The exact false positives seen in real clinical PDFs — must NOT be headings.
    assert _section_heading_num("12 Videotaping of physical examinations is optional.") is None
    assert _section_heading_num("24 Assessment will be performed on Day 121 only.") is None
    assert _section_heading_num("225 Binney Street") is None        # bounded number (>2 digits)
    assert _section_heading_num("13. Gestational age of 37 to 42 weeks for births, etc.") is None
    assert _section_heading_num("6.3 statistical methods") is None  # lower-case title → prose
    assert _section_heading_num("Section 6.3 of the protocol") is None  # citation, no leading number


def test_section_heading_num_excludes_toc_and_overlong():
    assert _section_heading_num("6.3 Statistical Methods ........... 88") is None
    assert _section_heading_num("6.3 " + "Very Long Heading Title " * 6) is None  # > 80 chars


def test_docx_section_scan_recovers_bold_unstyled_heading(tmp_path):
    docx = pytest.importorskip("docx")
    Document = docx.Document
    doc = Document()
    doc.add_paragraph("Body text citing Section 6.3 with no heading style.")  # p0
    p = doc.add_paragraph()                                                    # p1 bold heading
    run = p.add_run("6.3 Statistical Methods")
    run.bold = True
    doc.add_paragraph("9.9 footnote-like sentence that should not anchor.")    # p2 not bold
    path = tmp_path / "sect.docx"
    doc.save(str(path))

    idx = build_anchor_index([], str(path), is_pdf=False)
    assert idx["section_ref_6_3"]["paragraph_index"] == 1   # bold numbered heading captured
    assert "section_ref_9_9" not in idx                     # un-bold numbered sentence excluded


def test_caption_def_num_require_title_rejects_bare_fragment():
    # A PDF citation ("…contemplated in Appendix D of this protocol.") fragments to
    # a lone "Appendix D" span — indistinguishable from a heading by text alone, so
    # the per-span detection pass (require_title=True) must NOT treat it as a def.
    assert _caption_def_num("Appendix D", "APPENDIX_REF", require_title=True) is None
    assert _caption_def_num("Table 5", "TABLE_REF", require_title=True) is None
    # …but a title-bearing caption still qualifies, and bare is fine when allowed.
    assert _caption_def_num("Appendix D Investigator Consent", "APPENDIX_REF", require_title=True) == "D"
    assert _caption_def_num("Appendix D", "APPENDIX_REF", require_title=False) == "D"


def test_detection_pass_does_not_anchor_bare_citation_fragment():
    # The NCT01101035 bug: a bare "Appendix D" citation span must not claim the key
    # at the citation page (file absent → scan no-ops, so only the detection pass runs).
    dets = [{"label": "APPENDIX_REF", "text": "Appendix D", "groups": {"num": "D"},
             "context": "Appendix D", "page_index": 5, "bbox": [0, 0, 1, 1]}]
    idx = build_anchor_index(dets, "nonexistent.pdf", is_pdf=True)
    assert "appendix_ref_D" not in idx  # not anchored at the citation


def test_pdf_scan_bare_heading_needs_font_signal_not_citation(tmp_path):
    # Reproduces NCT01101035 Appendix D: a bare "Appendix D" appears as plain body
    # text early (citation/ToC) and as a BOLD heading later — the bold one wins.
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "appx.pdf"
    doc = fitz.open()
    p0 = doc.new_page()
    p0.insert_text((72, 200), "Appendix D", fontsize=11, fontname="helv")   # plain → skip
    p1 = doc.new_page()
    p1.insert_text((72, 120), "Appendix D", fontsize=11, fontname="hebo")   # bold → heading
    doc.save(str(path))
    doc.close()

    idx = build_anchor_index([], str(path), is_pdf=True)
    assert idx["appendix_ref_D"]["page_index"] == 1  # the bold heading, not the plain one


def test_pdf_section_scan_requires_larger_font(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "sect.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 120), "6.3 Statistical Methods", fontsize=16)  # heading, larger font
    page.insert_text((72, 300), "12 This footnote sentence is body size.", fontsize=11)  # body
    doc.save(str(path))
    doc.close()

    idx = build_anchor_index([], str(path), is_pdf=True)
    assert idx["section_ref_6_3"]["page_index"] == 0   # larger-font heading captured
    assert "section_ref_12" not in idx                 # body-size numbered line excluded
