"""PLAN NINE — production-PDF cross-document referencing.

Locks in two behaviours that make customer-supplied Protocol/SAP PDFs link to
each other (the Word path used study-id citations; real PDFs reference by
document type in prose, e.g. "the protocol"):

* Detection: ``DOC_REF`` fires on genuine document references and is **not**
  tricked by the statistical noun-phrases ("protocol deviation", "per protocol
  set"); ``APPENDIX_REF`` now also catches letter-suffixed appendices.
* Resolution: a ``DOC_REF`` routes to the **same study's** sibling of the named
  type (``NCT04089566_SAP`` → ``NCT04089566_Protocol``) and never guesses across
  studies when the sibling is absent.
"""

from __future__ import annotations

import pytest

from hyperlink_engine.core.detection.regex_patterns import default_registry
from hyperlink_engine.orchestration.nodes import _build_file_index, _resolve_one


# ── Detection (Fix A) ────────────────────────────────────────────────────────


def _doc_ref_hits(text: str) -> list[str]:
    reg = default_registry()
    return [m.text for m in reg.find_all(text) if reg.get(m.pattern_id).label == "DOC_REF"]


@pytest.mark.parametrize(
    "text",
    [
        "This SAP is based on Version 7 of the protocol, dated 14Jun2024",
        "references to the protocol refer to Version 7",
        "In a change from protocol V7, the dose was adjusted",
        "as described in the Statistical Analysis Plan",
    ],
)
def test_doc_ref_matches_genuine_document_references(text: str) -> None:
    assert _doc_ref_hits(text), f"expected a DOC_REF in: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "Protocol deviations identified during site monitoring",
        "A Per Protocol Set will include the subset of the ITT Set",
        "significant protocol deviations will be determined prior to lock",
    ],
)
def test_doc_ref_rejects_statistical_noun_phrases(text: str) -> None:
    assert _doc_ref_hits(text) == [], f"false-positive DOC_REF in: {text!r}"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("see SAP Section 5 for the analysis", "SAP"),
        ("as reported in the CSR for safety", "CSR"),
        ("Protocol TMX-67_301 Section 6.1", "Protocol"),
        ("summarized in the Clinical Study Report", "Clinical Study Report"),
        ("per the Statistical Analysis Plan", "Statistical Analysis Plan"),
    ],
)
def test_doc_ref_bare_word_is_detected(text: str, expected: str) -> None:
    """Issue #9: the BARE doc-type word must be the link span (not 'the CSR')."""
    hits = _doc_ref_hits(text)
    assert any(h.lower() == expected.lower() for h in hits), f"{expected!r} not in {hits!r}"


@pytest.mark.parametrize("text", ["maple sap was collected", "the csr value rose"])
def test_doc_ref_lowercase_acronym_not_matched(text: str) -> None:
    """Acronyms are case-sensitive: lowercase 'sap'/'csr' are not document refs."""
    assert _doc_ref_hits(text) == [], f"false-positive DOC_REF in: {text!r}"


@pytest.mark.parametrize(
    "text,expected",
    [
        # 'FullName (ACR)' de-dupes to ONE link on the ACRONYM (publishing preference:
        # link the short tag, not the spelled-out phrase).
        ("results presented in the Clinical Study Report (CSR) for", ["CSR"]),
        ("detailed in the Statistical Analysis Plan (SAP), and", ["SAP"]),
        # A standalone acronym (no spelled-out form just before) still links.
        ("analyzed as described in SAP Section 6.2", ["SAP"]),
        ("as reported in the CSR for safety", ["CSR"]),
    ],
)
def test_doc_ref_parenthetical_acronym_deduped(text: str, expected: list[str]) -> None:
    """'Clinical Study Report (CSR)' produces ONE DOC_REF link, on the acronym."""
    assert _doc_ref_hits(text) == expected, f"{text!r} -> {_doc_ref_hits(text)!r}"


def test_qualified_section_routes_cross_doc() -> None:
    """'SAP Section 6.2' in ISS routes the SECTION ref to the SAP sibling (issue 1/5)."""
    idx = _index("CSR", "SAP", "Protocol", "ISS")
    det = {
        "label": "SECTION_REF",
        "text": "Section 6.2",
        "context": "analyzed as described in SAP Section 6.2",
        "groups": {"num": "6.2"},
    }
    target = _resolve_one(det, idx, r"C:\u\ISS.pdf")
    assert target is not None and target.endswith("SAP.pdf")


def test_qualified_section_unqualified_stays_internal() -> None:
    """A plain 'Section 6.2' with no doc-type qualifier does NOT route cross-doc."""
    idx = _index("CSR", "SAP", "Protocol", "ISS")
    det = {
        "label": "SECTION_REF",
        "text": "Section 6.2",
        "context": "the results in Section 6.2 were significant",
        "groups": {"num": "6.2"},
    }
    assert _resolve_one(det, idx, r"C:\u\ISS.pdf") is None


def _doc_id_hits(text: str) -> list[str]:
    reg = default_registry()
    return [m.text for m in reg.find_all(text) if reg.get(m.pattern_id).label == "DOC_ID"]


def test_doc_id_detects_protocol_code() -> None:
    assert "TMX-67_301" in _doc_id_hits("see Protocol TMX-67_301 Section 6.1")


@pytest.mark.parametrize(
    "text",
    [
        "Study SP-2024-001 enrolled patients",  # a study id (no underscore), not a doc id
        "the protocol was amended in 2024",
        "values ranged from 2-3 per day",
    ],
)
def test_doc_id_does_not_overfire(text: str) -> None:
    assert _doc_id_hits(text) == [], f"false-positive DOC_ID in: {text!r}"


def test_doc_id_resolves_to_matching_uploaded_file() -> None:
    """File-gated: the id links only because its document is in the batch."""
    idx = _index("CSR", "Protocol", "TMX-67_301")
    det = {"label": "DOC_ID", "text": "TMX-67_301", "pattern_id": "DOC_ID_V1", "groups": {}, "context": ""}
    target = _resolve_one(det, idx, r"C:\u\CSR.pdf")
    assert target is not None and target.endswith("TMX-67_301.pdf")


def test_doc_id_without_matching_file_is_unresolved() -> None:
    """An id with no matching upload → None → skipped before injection (no FP link)."""
    idx = _index("CSR", "Protocol", "SAP")
    det = {"label": "DOC_ID", "text": "TMX-67_301", "pattern_id": "DOC_ID_V1", "groups": {}, "context": ""}
    assert _resolve_one(det, idx, r"C:\u\CSR.pdf") is None


@pytest.mark.parametrize("text,expected", [("See Appendix A for the schedule", "Appendix A"),
                                           ("refer to Appendix B", "Appendix B")])
def test_appendix_letter_is_detected(text: str, expected: str) -> None:
    reg = default_registry()
    hits = [m.text for m in reg.find_all(text) if m.pattern_id == "APPENDIX_REF_LETTER_V1"]
    assert expected in hits


# ── Resolution (Fix B) ───────────────────────────────────────────────────────


def _index(*names: str):
    return _build_file_index([{"source_path": rf"C:\u\{n}.pdf"} for n in names])


def test_doc_ref_routes_to_same_study_sibling() -> None:
    idx = _index("NCT04089566_SAP", "NCT04089566_Protocol", "NCT01101035_Protocol")
    det = {"label": "DOC_REF", "text": "the protocol", "context": ""}
    target = _resolve_one(det, idx, r"C:\u\NCT04089566_SAP.pdf")
    assert target is not None and target.endswith("NCT04089566_Protocol.pdf")


def test_doc_ref_self_type_is_dropped_even_with_another_same_type_file() -> None:
    """A bare 'SAP' inside SAP.docx is a SELF-reference and must NOT route to a
    different SAP that happens to be in the batch (NCT01101035_SAP.pdf)."""
    idx = _index("SAP", "NCT01101035_SAP", "CSR", "Protocol")
    sap_self = {"label": "DOC_REF", "text": "SAP", "context": "this SAP describes"}
    assert _resolve_one(sap_self, idx, r"C:\u\SAP.pdf") is None
    # but a cross-type reference from the SAP still resolves
    csr_ref = {"label": "DOC_REF", "text": "CSR", "context": "presented in the CSR"}
    target = _resolve_one(csr_ref, idx, r"C:\u\SAP.pdf")
    assert target is not None and target.endswith("CSR.pdf")


def test_doc_ref_does_not_guess_across_studies() -> None:
    # Source study's protocol is absent; two unrelated protocols exist → ambiguous.
    idx = _index("NCT04851873_SAP", "NCT04089566_Protocol", "NCT01101035_Protocol")
    det = {"label": "DOC_REF", "text": "the protocol", "context": ""}
    assert _resolve_one(det, idx, r"C:\u\NCT04851873_SAP.pdf") is None


def test_doc_ref_unique_type_fallback_resolves() -> None:
    # Source study's protocol absent, but exactly one protocol in the batch → link it.
    idx = _index("NCT04851873_SAP", "NCT04089566_Protocol")
    det = {"label": "DOC_REF", "text": "the protocol", "context": ""}
    target = _resolve_one(det, idx, r"C:\u\NCT04851873_SAP.pdf")
    assert target is not None and target.endswith("NCT04089566_Protocol.pdf")


def test_sponsor_id_study_resolution_unchanged() -> None:
    # Synthetic CSR parity: a study-id citation still routes to the CSR body
    # (the legacy path is untouched by the DOC_REF addition).
    idx = _index("csr-sp-2026-002-body", "csr-sp-2026-002-listings", "csr-sp-2026-001-body")
    det = {"label": "STUDY_ID", "text": "SP-2026-002", "context": "see CSR SP-2026-002"}
    target = _resolve_one(det, idx, r"C:\u\csr-sp-2026-001-body.pdf")
    assert target is not None and target.endswith("csr-sp-2026-002-body.pdf")
