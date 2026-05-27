"""Unit tests for detection/regex_patterns.py.

Each test case is anchored to an example from docs/pattern-catalog.md so
that the catalog and the regex engine remain in lockstep.
"""

from __future__ import annotations

import pytest

from hyperlink_engine.detection.regex_patterns import (
    Match,
    PatternRegistry,
    default_registry,
    resolve_overlaps,
)


# ── STUDY_ID family ──────────────────────────────────────────────────────


class TestStudyIdSponsor:
    @pytest.mark.parametrize(
        "text",
        ["SP-2024-001", "SUNP-2023-042", "SPL-2025-1001", "ABC-2022-007", "XYZ-2024-9999"],
    )
    def test_matches_canonical_examples(self, text: str) -> None:
        reg = default_registry()
        matches = [m for m in reg.find_all(text) if m.pattern_id == "STUDY_ID_SPONSOR_V1"]
        assert len(matches) == 1
        assert matches[0].text == text

    @pytest.mark.parametrize(
        "text",
        ["SP-24-1", "sp-2024-001", "X-2024-001"],  # too short / lowercase / 1-char sponsor
    )
    def test_rejects_invalid_variants(self, text: str) -> None:
        reg = default_registry()
        matches = [m for m in reg.find_all(text) if m.pattern_id == "STUDY_ID_SPONSOR_V1"]
        assert matches == []


class TestStudyIdNct:
    @pytest.mark.parametrize(
        "text", ["NCT01234567", "NCT00000001", "NCT99999999", "NCT04567890"]
    )
    def test_matches_canonical(self, text: str) -> None:
        reg = default_registry()
        matches = [m for m in reg.find_all(text) if m.pattern_id == "STUDY_ID_NCT_V1"]
        assert len(matches) == 1

    def test_rejects_wrong_digit_count(self) -> None:
        reg = default_registry()
        for bad in ["NCT1234567", "NCT123456789", "NCT-01234567"]:
            assert [m for m in reg.find_all(bad) if m.pattern_id == "STUDY_ID_NCT_V1"] == []


# ── SECTION_REF family ───────────────────────────────────────────────────


class TestSectionRefDotted:
    def test_matches_with_context_cue(self) -> None:
        reg = default_registry()
        text = "Please see Section 2.5.3 for the rationale."
        # Bare dotted pattern requires a context cue — "Section" qualifies
        matches = [m for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_DOTTED_V1"]
        assert any(m.text == "2.5.3" for m in matches)

    def test_rejects_without_context(self) -> None:
        reg = default_registry()
        # A bare "2.5.3" in isolation should not match (no cue word)
        text = "The value 2.5.3 appeared in the dataset."
        matches = [m for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_DOTTED_V1"]
        assert matches == []


class TestSectionRefLabeled:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Section 2.5.3", "Section 2.5.3"),
            ("Section 5", "Section 5"),
            ("Sect. 11.4", "Sect. 11.4"),
            ("see sec 14.2.1 below", "sec 14.2.1"),
        ],
    )
    def test_canonical(self, text: str, expected: str) -> None:
        reg = default_registry()
        matches = [m for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_LABELED_V1"]
        assert any(m.text == expected for m in matches)


class TestSectionRefSigil:
    def test_matches_sigil(self) -> None:
        reg = default_registry()
        text = "Per §2.5.3, the threshold is fixed."
        matches = [m for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_SIGIL_V1"]
        assert len(matches) == 1
        assert matches[0].groups["num"] == "2.5.3"


# ── TABLE / FIGURE / LISTING ─────────────────────────────────────────────


class TestTableFigureListing:
    def test_table_match(self) -> None:
        reg = default_registry()
        text = "Demographic data are summarized in Table 14.2.1.1 below."
        m = next(m for m in reg.find_all(text) if m.pattern_id == "TABLE_REF_NUMBERED_V1")
        assert m.text == "Table 14.2.1.1"
        assert m.groups["num"] == "14.2.1.1"

    def test_figure_match(self) -> None:
        reg = default_registry()
        text = "See Figure 11 for the dose-response curve."
        m = next(m for m in reg.find_all(text) if m.pattern_id == "FIGURE_REF_NUMBERED_V1")
        assert m.text == "Figure 11"

    def test_listing_match(self) -> None:
        reg = default_registry()
        text = "Adverse events are in Listing 16.2.5."
        m = next(m for m in reg.find_all(text) if m.pattern_id == "LISTING_REF_NUMBERED_V1")
        assert m.text == "Listing 16.2.5"


# ── CTD_LEAF family ──────────────────────────────────────────────────────


class TestCtdLeafModule:
    def test_module_reference(self) -> None:
        reg = default_registry()
        text = "Refer to Module 5.3.1 for the CSR."
        m = next(m for m in reg.find_all(text) if m.pattern_id == "CTD_LEAF_MODULE_V1")
        assert m.text == "Module 5.3.1"
        assert m.groups["mod"] == "5"

    def test_module_invalid_number_rejected(self) -> None:
        reg = default_registry()
        text = "Module 6 does not exist"
        matches = [m for m in reg.find_all(text) if m.pattern_id == "CTD_LEAF_MODULE_V1"]
        assert matches == []


# ── Conflict resolution ──────────────────────────────────────────────────


class TestResolveOverlaps:
    def test_higher_confidence_wins(self) -> None:
        # Both patterns match "Section 2.5.3"; labeled (0.92) beats dotted (0.55)
        reg = default_registry()
        text = "See Section 2.5.3 for details."
        all_matches = reg.find_all(text)
        resolved = resolve_overlaps(all_matches)

        # Labeled pattern's match should be kept; bare dotted should be suppressed
        kept_ids = {m.pattern_id for m in resolved}
        assert "SECTION_REF_LABELED_V1" in kept_ids
        # The bare dotted match overlaps with labeled and has lower confidence
        labeled = next(m for m in resolved if m.pattern_id == "SECTION_REF_LABELED_V1")
        # Confirm no SECTION_REF_DOTTED_V1 match was kept inside the labeled span
        assert not any(
            m.pattern_id == "SECTION_REF_DOTTED_V1"
            and m.start >= labeled.start
            and m.end <= labeled.end
            for m in resolved
        )

    def test_empty_input(self) -> None:
        assert resolve_overlaps([]) == []

    def test_non_overlapping_all_kept(self) -> None:
        a = Match("A", "x", 0, 1, 0.5)
        b = Match("B", "y", 5, 6, 0.5)
        assert resolve_overlaps([a, b]) == [a, b]

    def test_overlap_keeps_higher_confidence(self) -> None:
        low = Match("L", "longer text", 0, 11, 0.5)
        high = Match("H", "short", 3, 8, 0.9)
        result = resolve_overlaps([low, high])
        assert result == [high]


# ── Registry contracts ───────────────────────────────────────────────────


class TestRegistryContract:
    def test_default_registry_populated(self) -> None:
        reg = default_registry()
        assert len(reg) >= 12

    def test_cannot_register_duplicate_id(self) -> None:
        reg = default_registry()
        with pytest.raises(ValueError, match="already registered"):
            reg.register(reg.get("STUDY_ID_NCT_V1"))

    def test_find_all_sorted_is_ordered(self) -> None:
        reg = default_registry()
        text = "Table 1 appears before Section 2.5.3. NCT01234567 also."
        results = reg.find_all_sorted(text)
        positions = [m.start for m in results]
        assert positions == sorted(positions)


# ── Integration smoke test ───────────────────────────────────────────────


def test_realistic_paragraph_finds_multiple_references() -> None:
    """Mimics a sentence from a Module 2.5 clinical overview."""
    reg = default_registry()
    text = (
        "As described in Section 2.5.3 and shown in Table 14.2.1.1, "
        "study SP-2024-001 (NCT01234567) demonstrated efficacy. "
        "Refer to Module 5.3.1 for the full CSR and Listing 16.2.5 for "
        "adverse events. Per §2.7.4, the safety profile was acceptable."
    )
    raw = reg.find_all(text)
    resolved = resolve_overlaps(raw)
    pattern_ids = {m.pattern_id for m in resolved}

    # All major families should be represented
    assert "SECTION_REF_LABELED_V1" in pattern_ids
    assert "TABLE_REF_NUMBERED_V1" in pattern_ids
    assert "STUDY_ID_SPONSOR_V1" in pattern_ids
    assert "STUDY_ID_NCT_V1" in pattern_ids
    assert "CTD_LEAF_MODULE_V1" in pattern_ids
    assert "LISTING_REF_NUMBERED_V1" in pattern_ids
    assert "SECTION_REF_SIGIL_V1" in pattern_ids
