"""Unit tests for detection/ner_model.py."""

from __future__ import annotations

import pytest

from hyperlink_engine.detection.ner_model import (
    SpacyNerExtractor,
    labels_in_fallback,
)

# Skip the whole module if spaCy isn't installed (CI without ML deps).
pytest.importorskip("spacy")


def test_fallback_labels_cover_catalog() -> None:
    labels = labels_in_fallback()
    expected = {
        "STUDY_ID",
        "SECTION_REF",
        "TABLE_REF",
        "FIGURE_REF",
        "LISTING_REF",
        "APPENDIX_REF",
        "CTD_LEAF",
    }
    assert expected.issubset(labels)


def test_extractor_runs_in_fallback_mode() -> None:
    ex = SpacyNerExtractor()
    assert ex.mode == "rule_fallback"


def test_extractor_finds_section_refs() -> None:
    ex = SpacyNerExtractor()
    hits = ex.extract("See Section 2.5.3 for the rationale.")
    labels = {h.groups["label"] for h in hits}
    assert "SECTION_REF" in labels


def test_extractor_finds_table_and_figure() -> None:
    ex = SpacyNerExtractor()
    hits = ex.extract("Refer to Table 14.2.1 and Figure 11 below.")
    labels = [h.groups["label"] for h in hits]
    assert "TABLE_REF" in labels
    assert "FIGURE_REF" in labels


def test_extractor_finds_nct_and_sponsor_id() -> None:
    ex = SpacyNerExtractor()
    hits = ex.extract("Studies MED-2020-026 and NCT46913810 are listed.")
    labels = [h.groups["label"] for h in hits]
    # NCT is single-token; MED-2020-026 is multi-token — both must match.
    assert labels.count("STUDY_ID") >= 2


def test_extractor_finds_module_ref() -> None:
    ex = SpacyNerExtractor()
    hits = ex.extract("See Module 5.3.1 for the clinical study report.")
    assert any(h.groups["label"] == "CTD_LEAF" for h in hits)


def test_empty_text_returns_empty() -> None:
    ex = SpacyNerExtractor()
    assert ex.extract("") == []


def test_label_filter_drops_others() -> None:
    from hyperlink_engine.detection.ner_model import NerConfig

    ex = SpacyNerExtractor(NerConfig(label_filter=("STUDY_ID",)))
    hits = ex.extract("Section 2.5.3 and NCT46913810.")
    assert all(h.groups["label"] == "STUDY_ID" for h in hits)
    assert hits  # at least the NCT id should make it through


def test_label_for_unknown_pattern_id_returns_unknown() -> None:
    ex = SpacyNerExtractor()
    assert ex.label_for("NER_NOPE_V1") == "NOPE"
    assert ex.label_for("not_a_real_pattern") == "UNKNOWN"
