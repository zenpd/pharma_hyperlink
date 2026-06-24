"""Unit tests for detection/regex_patterns.py.

Each test case is anchored to an example from docs/pattern-catalog.md so
that the catalog and the regex engine remain in lockstep.
"""

from __future__ import annotations

import pytest

from hyperlink_engine.core.detection.regex_patterns import (
    Match,
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

    def test_rejects_statistics_near_weak_cues(self) -> None:
        # Real false positives: decimals (rates / CIs / doses) sit next to weak
        # words like "per"/"see" but are NOT sections. Only "Section"/§ qualifies now.
        reg = default_registry()
        for text in (
            "0.74 per 100 PY with 95% CI 0.36-1.37",      # incidence rate + CI
            "allopurinol (0.60 per 100 PY with 95% CI 0.16-1.53)",
            "incidence of 8.5 to 10.3 per 100,000 live births",
            "approximately 3.9 years (see Figure 2)",     # duration, weak cue "see"
            "0.3, 1, and 4 mg per dose",                  # doses
        ):
            matches = [m for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_DOTTED_V1"]
            assert matches == [], f"statistic wrongly matched as section in: {text!r}"

    def test_matches_enumerated_sections(self) -> None:
        # "Sections 7.4 and 7.5" — 7.5 is not adjacent to the keyword, so the
        # dotted pattern (cued by "Sections") is what catches it.
        reg = default_registry()
        text = "Revisions and clarifications in Sections 7.4 and 7.5"
        nums = {m.text for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_DOTTED_V1"}
        assert "7.5" in nums

    def test_matches_bare_reference_with_prose_cue(self) -> None:
        # Restore real bare dotted section refs that the strong-cue-only version
        # dropped: prose cues ("described in", "refer to", "see") qualify, not
        # just the literal word "Section".
        reg = default_registry()
        for text, want in (
            ("as described in 2.3 for details", "2.3"),
            ("refer to 2.3.1 and 2.3.2", "2.3.1"),
            ("see 2.5 for the schedule", "2.5"),
        ):
            nums = {m.text for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_DOTTED_V1"}
            assert want in nums, f"missed bare section ref in: {text!r}"

    def test_broader_cues_still_reject_statistics(self) -> None:
        # The broadened cue list must NOT re-admit decimals: a statistical marker
        # nearby (unit / CI / % / per-N) rejects even when a cue word is present.
        reg = default_registry()
        for text in (
            "mean 3.9 years (see baseline)",     # unit 'years' + cue 'see'
            "see 1.37 per 100 PY",               # rate + cue 'see'
            "as described, 8.5% reduction",      # percent + cue 'described'
        ):
            matches = [m for m in reg.find_all(text) if m.pattern_id == "SECTION_REF_DOTTED_V1"]
            assert matches == [], f"statistic wrongly matched with cue in: {text!r}"


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

    def test_figure_letter_match(self) -> None:
        """Letter-suffixed figures ('Figure A') must be detected, mirroring the
        appendix-letter pattern. Regression guard for the demo doc that used
        'See Figure A.'."""
        reg = default_registry()
        text = "Patients who did not respond well are shown in Figure A."
        m = next(m for m in reg.find_all(text) if m.pattern_id == "FIGURE_REF_LETTER_V1")
        assert m.text == "Figure A"
        assert m.groups["num"] == "A"

    def test_figure_numbered_not_stolen_by_letter(self) -> None:
        """A numbered figure must still resolve to the NUMBERED pattern (higher
        confidence), so the new letter pattern adds coverage without regressing
        'Figure 1' / 'Figure 2'."""
        reg = default_registry()
        text = "As shown in Figure 1 and Figure 2, the tumor response improved."
        labels = {m.text: m.pattern_id for m in reg.find_all(text)}
        assert labels["Figure 1"] == "FIGURE_REF_NUMBERED_V1"
        assert labels["Figure 2"] == "FIGURE_REF_NUMBERED_V1"

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


class TestCtdLeafPath:
    def test_real_leaf_path_matches(self) -> None:
        reg = default_registry()
        text = "See m5/53-clin-stud-rep/5331/study-001 in the backbone."
        m = next(m for m in reg.find_all(text) if m.pattern_id == "CTD_LEAF_PATH_V1")
        assert m.text == "m5/53-clin-stud-rep/5331/study-001"

    @pytest.mark.parametrize(
        "text",
        [
            "BMI in kg/m2",
            "dose of 5 mg/m2",
            "bare m2 token",
            # dosing units with a TRAILING slash used to slip through ("m2/day");
            # the digit-led subpath now rejects them (units are letter-led).
            "18mg/m2/day or 23 mg/m2/day",
            "expansion part (n=39; 18mg/m2/day)",
        ],
    )
    def test_unit_strings_no_longer_match(self, text: str) -> None:
        # Regression: a bare "m2" (e.g. inside "kg/m2") used to match as an eCTD
        # leaf path on real ClinicalTrials SAPs. The mandatory "/path" suffix
        # plus a DIGIT-LED first segment now requires an actual leaf path.
        reg = default_registry()
        matches = [m for m in reg.find_all(text) if m.pattern_id == "CTD_LEAF_PATH_V1"]
        assert matches == [], f"unit string wrongly matched as CTD leaf in: {text!r}"


# ── EXT_REF family (external / regulatory citations) ─────────────────────


class TestExtRef:
    def test_ich_guideline(self) -> None:
        reg = default_registry()
        for text, expected in [("ICH E6(R2)", "ICH E6(R2)"), ("ICH M4", "ICH M4"), ("ICH E2A", "ICH E2A")]:
            m = next(m for m in reg.find_all(text) if m.pattern_id == "EXT_REF_ICH_V1")
            assert m.text == expected
        # "ICH meeting" must NOT match (needs a letter+digit code).
        assert [m for m in reg.find_all("ICH meeting next week") if m.pattern_id == "EXT_REF_ICH_V1"] == []

    def test_cfr_citation(self) -> None:
        reg = default_registry()
        for text in [
            "21 CFR 312",
            "21 CFR Part 50",
            "21 CFR 312.20",
            "21 Code of Federal Regulations (CFR) Part 56",  # spelled-out form, real protocol
        ]:
            matches = [m for m in reg.find_all(text) if m.pattern_id == "EXT_REF_CFR_V1"]
            assert matches, f"CFR citation not matched: {text!r}"
        # A 4-digit year before CFR is not a title.
        assert [m for m in reg.find_all("in 2014 CFR data") if m.pattern_id == "EXT_REF_CFR_V1"] == []

    def test_declaration_of_helsinki(self) -> None:
        reg = default_registry()
        m = next(m for m in reg.find_all("conducted per the Declaration of Helsinki.") if m.pattern_id == "EXT_REF_HELSINKI_V1")
        assert m.text.lower() == "declaration of helsinki"

    def test_doi(self) -> None:
        reg = default_registry()
        m = next(m for m in reg.find_all("doi:10.1056/NEJMoa1234567 reported") if m.pattern_id == "EXT_REF_DOI_V1")
        assert m.text.startswith("10.1056/")


# ── VISIT_REF family (scheduled-visit cross-references) ──────────────────


class TestVisitRef:
    @pytest.mark.parametrize(
        "text,unit,n",
        [
            ("returned for the Week 2 Visit (±3 days)", "Week", "2"),
            ("on Day 1/Randomization Visit subjects", "Day", "1"),
            ("at the Month 3 visit", "Month", "3"),
            ("missed the Week 10 Visit", "Week", "10"),
        ],
    )
    def test_matches_visit_references(self, text: str, unit: str, n: str, monkeypatch) -> None:
        # VISIT_REF is opt-in (stale on real docs); enable it to test the pattern.
        monkeypatch.setattr(
            "hyperlink_engine.core.detection.regex_patterns._LINK_VISIT_REFS", True
        )
        reg = default_registry()
        m = next(m for m in reg.find_all(text) if m.pattern_id == "VISIT_REF_V1")
        assert m.groups["unit"] == unit
        assert m.groups["n"] == n

    def test_visit_ref_disabled_by_default(self) -> None:
        """DEFAULT: 'Week 2 Visit' must NOT produce a VISIT_REF link (stale on real
        protocols). Re-enable via HYPERLINK_LINK_VISIT_REFS=1."""
        reg = default_registry()
        assert [
            m for m in reg.find_all("returned for the Week 2 Visit (+/-3 days)")
            if m.pattern_id == "VISIT_REF_V1"
        ] == []

    @pytest.mark.parametrize(
        "text",
        [
            "the Week 2 sUA level was measured",   # descriptive, not a visit ref
            "subjects randomized at Week 4",        # bare timepoint
            "over a period of Month 3 to Month 6",  # bare timepoints
        ],
    )
    def test_rejects_bare_timepoints(self, text: str, monkeypatch) -> None:
        # The literal word "Visit" is required — bare timepoints are prose, not
        # cross-references, and there are ~5x as many of them. (VISIT_REF enabled
        # so this exercises the pattern's rejection, not just the off-by-default.)
        monkeypatch.setattr(
            "hyperlink_engine.core.detection.regex_patterns._LINK_VISIT_REFS", True
        )
        reg = default_registry()
        assert [m for m in reg.find_all(text) if m.pattern_id == "VISIT_REF_V1"] == []


def test_canonical_visit_key_matches_resolver() -> None:
    # The detection group → key contract must stay byte-identical between the
    # resolver and the anchor index, or visit citations never find their section.
    from hyperlink_engine.core.injection.anchor_index import canonical_visit_key

    assert canonical_visit_key("Week", "2") == "visit_ref_week_2"
    assert canonical_visit_key("month", "3") == "visit_ref_month_3"


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
