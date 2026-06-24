"""Author-year citation → bibliography ENTRY locator (Reference View scroll).

Clicking an author citation in the Reference View used to land on the *same line*
(the first in-text mention, which also starts with the surname) instead of the
References entry. ``_locate_author_entry`` picks the entry — preferring the match
after a References heading — and handles short ("Xu") / compound ("O'Brien")
surnames via the ``ref_<surname>_<year>`` slug.
"""

from __future__ import annotations

from hyperlink_engine.api.app import _locate_author_entry


def test_lands_on_entry_not_intext_mention() -> None:
    paras = [
        "Introduction",
        "Tankere et al. (2022) reported a durable response in the cohort.",  # in-text, starts w/ surname
        "6 References",
        "Tankere, P.; Dupont, J. Afatinib outcomes. Lung Cancer 2022, 12, 33-40.",  # ENTRY
    ]
    assert _locate_author_entry(paras, "ref_tankere_2022") == 3


def test_short_surname_xu_from_slug() -> None:
    # "Xu" is two letters — a [A-Z][a-z]{2,} name regex would miss it; the slug carries it.
    paras = [
        "Xu, H 2022 demonstrated the effect in the validation set.",  # in-text mention
        "6 References",
        "Xu, H.; Yang, G. EGFR alterations. Front Pharmacol 2022, 13, 976731.",  # ENTRY
    ]
    assert _locate_author_entry(paras, "ref_xu_2022") == 2


def test_compound_obrien_apostrophe() -> None:
    # Slug surname "obrien" (apostrophe stripped) must still match body "O'Brien".
    paras = [
        "References",
        "O'Brien, M.; Kelly, P. Afatinib in NSCLC. Ann Oncol 2019, 30, 1245-1252.",
    ]
    assert _locate_author_entry(paras, "ref_obrien_2019") == 1


def test_numbered_references_heading_form() -> None:
    paras = [
        "Smith et al. 2020 showed improvement over the prior standard.",  # in-text
        "11. REFERENCES",  # numbered heading must still be recognised
        "Smith, J. Trial results. JAMA 2020, 5, 1.",  # ENTRY
    ]
    assert _locate_author_entry(paras, "ref_smith_2020") == 2


def test_short_surname_word_boundary_no_likewise_match() -> None:
    # "li" must NOT match a body word "Likewise" — the entry "Li, Q." is the target.
    paras = [
        "Likewise 2020 the trend continued across every site in the study.",
        "References",
        "Li, Q. Cohort study. Oncology 2020, 7, 9.",  # ENTRY
    ]
    assert _locate_author_entry(paras, "ref_li_2020") == 2


def test_human_text_anchor_also_supported() -> None:
    # When the anchor is the human link text rather than the slug.
    paras = [
        "Chiu, C.H. 2015 confirmed the treatment response in the subgroup.",  # in-text
        "References",
        "Chiu, C.H.; Yang, C.T. Treatment Response. J Thorac Oncol 2015, 10, 793-799.",  # ENTRY
    ]
    assert _locate_author_entry(paras, "Chiu, CH 2015") == 2


def test_returns_none_for_non_author_anchor() -> None:
    paras = ["Section 6.1 Study Design", "Body text mentioning 6.1 again."]
    assert _locate_author_entry(paras, "section_ref_6_1") is None
    assert _locate_author_entry(paras, "Table 14.2.1.1") is None
    assert _locate_author_entry(paras, "") is None


def test_returns_none_when_no_matching_entry() -> None:
    paras = ["Some unrelated paragraph.", "Another one without the author."]
    assert _locate_author_entry(paras, "ref_nguyen_2021") is None
