"""Unit tests for detection/entity_extractor.py — the full cascade."""

from __future__ import annotations

import pytest

from hyperlink_engine.detection.entity_extractor import (
    EntityExtractor,
    full_cascade,
    regex_only,
    regex_plus_ner,
    source_summary,
)


@pytest.fixture(scope="module")
def realistic_paragraph() -> str:
    return (
        "Per Section 2.5.3 of the Clinical Overview, study MED-2020-026 "
        "(NCT46913810) supports efficacy. See Table 14.2.1.1 and Figure 11 "
        "in Module 5.3.1 for primary endpoint results. Refer to Appendix 16.1.1 "
        "and Listing 16.2.5 for line listings. §5.3.2 covers safety."
    )


def test_regex_only_finds_expected_types(realistic_paragraph: str) -> None:
    refs = regex_only().extract(realistic_paragraph)
    labels = {r.label for r in refs}
    assert {
        "SECTION_REF",
        "STUDY_ID",
        "TABLE_REF",
        "FIGURE_REF",
        "CTD_LEAF",
        "APPENDIX_REF",
        "LISTING_REF",
    }.issubset(labels)


def test_regex_plus_ner_does_not_lose_recall(realistic_paragraph: str) -> None:
    pytest.importorskip("spacy")
    regex_refs = regex_only().extract(realistic_paragraph)
    cascade_refs = regex_plus_ner().extract(realistic_paragraph)
    regex_labels = {r.label for r in regex_refs}
    cascade_labels = {r.label for r in cascade_refs}
    # Adding NER must never *drop* a regex-detected label type.
    assert regex_labels.issubset(cascade_labels)


def test_full_cascade_with_stub_llm(realistic_paragraph: str) -> None:
    pytest.importorskip("spacy")
    refs = full_cascade(prefer_stub=True).extract(realistic_paragraph)
    assert refs, "cascade should still detect references"
    # Source-layer histogram must be a valid subset
    summary = source_summary(refs)
    assert set(summary.keys()).issubset({"regex", "ner", "llm", "merged"})


def test_empty_text_returns_empty_list() -> None:
    assert regex_only().extract("") == []
    assert EntityExtractor().extract("") == []


def test_low_confidence_runs_through_llm() -> None:
    """A candidate below threshold should get rewritten by the LLM stub."""
    from hyperlink_engine.detection.entity_extractor import EntityExtractor
    from hyperlink_engine.detection.llm_disambiguator import (
        DeterministicStubTransport,
        DisambiguatorConfig,
        LlmDisambiguator,
    )

    # SECTION_REF_DOTTED_V1 is a low-confidence pattern (0.55) that fires only
    # when a context cue word ("section") is present. We feed exactly that.
    text = "Refer to section 2.5.3 for the rationale."
    disamb = LlmDisambiguator(
        DeterministicStubTransport(),
        DisambiguatorConfig(confidence_threshold=0.95),  # force LLM to fire
    )
    extractor = EntityExtractor(llm_disambiguator=disamb)
    refs = extractor.extract(text)
    # At least one ref should now carry an llm_rationale group key.
    assert any("llm_rationale" in r.groups for r in refs)
