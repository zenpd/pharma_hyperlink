"""PLAN NINETEEN — GLiNER author-name detection + hybrid dispatch.

These run WITHOUT the optional ``gliner`` package (the model itself was validated
in the spike). They lock the pure-Python logic, the graceful fallback, regex
parity when the flag is off, and the short-surname index fix.
"""

from __future__ import annotations

from hyperlink_engine.core.detection import gliner_refs
from hyperlink_engine.core.injection import ref_index
from hyperlink_engine.core.injection.ref_index import parse_ref_entry_key


def test_year_adjacency_keeps_citation_drops_coauthor() -> None:
    # "Xu, H" is an in-text citation (year right after); "Boidot, R." is a co-author
    # inside a References entry (year far away) → dropped. This is how GLiNER's
    # name-detection becomes citation-detection without a co-author flood.
    text = "See Xu, H 2022 for data. Tankere, P.; Boidot, R.; Bonniaud, P. J. Dis. 2022."
    ents = [
        {"text": "Xu, H", "start": 4, "end": 9},
        {"text": "Boidot, R.", "start": 37, "end": 47},
    ]
    keys = [(c.group("surname"), c.group("year")) for c in gliner_refs._cites_from_entities(text, ents)]
    assert ("Xu", "2022") in keys
    assert all(s != "Boidot" for s, _ in keys)


def test_month_name_is_not_an_author() -> None:
    text = "data from March 2020 onward"
    assert gliner_refs._cites_from_entities(text, [{"text": "March", "start": 10, "end": 15}]) == []


def test_citematch_is_re_match_compatible() -> None:
    text = "See Ng, K 2020 here"
    c = gliner_refs._cites_from_entities(text, [{"text": "Ng, K", "start": 4, "end": 9}])[0]
    assert c.group("surname") == "Ng"          # SHORT surname kept (regex misses it)
    assert c.group("year") == "2020"
    assert c.group(0) == "Ng, K"
    assert text[c.start() : c.end()] == "Ng, K"


def test_gliner_unavailable_returns_empty(monkeypatch) -> None:
    # When gliner is unavailable, detection degrades to [] so the regex path stays
    # the source of truth. Mock availability so this holds whether or not gliner is
    # actually installed in the venv (it is, once Phase C is activated).
    monkeypatch.setattr(gliner_refs, "available", lambda: False)
    assert gliner_refs.gliner_ref_cites("See Xu, H 2022") == []


def test_dispatch_default_is_pure_regex() -> None:
    out = ref_index.author_year_cites("See Tankere, P 2022 and Helget LN, 2024")
    keys = sorted((m.group("surname"), m.group("year")) for m in out)
    assert keys == [("Helget", "2024"), ("Tankere", "2022")]


def test_dispatch_hybrid_without_gliner_falls_back_to_regex(monkeypatch) -> None:
    monkeypatch.setattr(ref_index, "_REFERENCE_DETECTOR", "hybrid")
    out = ref_index.author_year_cites("See Tankere, P 2022")
    assert [(m.group("surname"), m.group("year")) for m in out] == [("Tankere", "2022")]


def test_lead_surname_indexes_short_surnames() -> None:
    # the References-index side must key short surnames, else a GLiNER "Xu, H 2022"
    # citation has no entry to resolve to.
    assert parse_ref_entry_key("Xu H, Yang G. EGFR alterations. Front Pharmacol. 2022, 13, 976731.") == "ref_xu_2022"
    # western lead surname unchanged (no regression)
    assert parse_ref_entry_key("Helget LN, et al. Am J Kidney Dis. 2024;83:1-9.") == "ref_helget_2024"
