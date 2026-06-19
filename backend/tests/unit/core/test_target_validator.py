"""Unit tests for validation/target_validator.py."""

from __future__ import annotations

from hyperlink_engine.core.validation.target_validator import (
    TargetValidator,
    jaccard_similarity,
)
from hyperlink_engine.models import LinkRecord, LinkStatus


def test_jaccard_identical_is_one() -> None:
    assert jaccard_similarity("Section 2.5.3", "Section 2.5.3") == 1.0


def test_jaccard_disjoint_is_zero() -> None:
    assert jaccard_similarity("alpha bravo", "delta echo") == 0.0


def test_jaccard_partial_overlap() -> None:
    score = jaccard_similarity("Section 2.5.3 Clinical Overview", "Section 2.5.3")
    assert 0.0 < score < 1.0


def test_jaccard_empty_both_strings() -> None:
    assert jaccard_similarity("", "") == 1.0


def test_jaccard_one_empty() -> None:
    assert jaccard_similarity("anything", "") == 0.0
    assert jaccard_similarity("", "anything") == 0.0


def test_validator_defaults_to_jaccard_mode() -> None:
    validator = TargetValidator()
    assert validator.mode == "jaccard"


def test_validator_check_passes() -> None:
    validator = TargetValidator(threshold=0.4)
    result = validator.check("Section 2.5.3", "Section 2.5.3 Clinical Overview")
    assert result.passed
    assert result.score >= 0.4


def test_validator_check_fails() -> None:
    validator = TargetValidator(threshold=0.9)
    result = validator.check("Table 14.2.1.1", "Figure 11")
    assert not result.passed


def test_annotate_marks_suspicious() -> None:
    validator = TargetValidator(threshold=0.9)
    record_ok = LinkRecord(
        source_doc="doc.docx",
        link_text="Table 14.2.1.1",
        link_location_descriptor="p0.r0",
        target_doc="target.docx",
        target_anchor="table_14_2_1_1",
        status=LinkStatus.OK,
        confidence=1.0,
    )

    def provider(record: LinkRecord) -> str:
        return "Completely Unrelated Heading"

    annotated = validator.annotate([record_ok], provider)
    assert annotated[0].status == LinkStatus.SUSPICIOUS
    assert "score=" in (annotated[0].error_msg or "")


def test_annotate_keeps_non_ok_records_untouched() -> None:
    validator = TargetValidator(threshold=0.9)
    record_broken = LinkRecord(
        source_doc="doc.docx",
        link_text="Table 14.2.1.1",
        link_location_descriptor="p0.r0",
        target_doc=None,
        target_anchor=None,
        status=LinkStatus.BROKEN,
        confidence=0.0,
        error_msg="missing",
    )

    def provider(record: LinkRecord) -> str:
        return "Something"

    annotated = validator.annotate([record_broken], provider)
    assert annotated[0].status == LinkStatus.BROKEN


def test_annotate_skips_when_no_target_text() -> None:
    validator = TargetValidator(threshold=0.9)
    record = LinkRecord(
        source_doc="doc.docx",
        link_text="X",
        link_location_descriptor="p0.r0",
        target_doc="t.docx",
        target_anchor="a",
        status=LinkStatus.OK,
        confidence=1.0,
    )

    def provider(record: LinkRecord) -> str | None:
        return None

    annotated = validator.annotate([record], provider)
    assert annotated[0].status == LinkStatus.OK
