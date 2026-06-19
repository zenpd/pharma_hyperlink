"""Unit tests for scripts/benchmark.py — score math is the critical bit."""

from __future__ import annotations

from scripts.benchmark import Counts, Span, _aggregate, _score


def test_perfect_match_yields_full_f1() -> None:
    gold = [Span(0, 5, "STUDY_ID"), Span(10, 15, "TABLE_REF")]
    pred = [Span(0, 5, "STUDY_ID"), Span(10, 15, "TABLE_REF")]
    counts = _score(gold, pred)
    assert counts["STUDY_ID"].f1 == 1.0
    assert counts["TABLE_REF"].f1 == 1.0


def test_false_positive_drops_precision() -> None:
    gold = [Span(0, 5, "STUDY_ID")]
    pred = [Span(0, 5, "STUDY_ID"), Span(10, 15, "STUDY_ID")]
    counts = _score(gold, pred)
    c = counts["STUDY_ID"]
    assert c.tp == 1
    assert c.fp == 1
    assert c.fn == 0
    assert 0.0 < c.precision < 1.0
    assert c.recall == 1.0


def test_false_negative_drops_recall() -> None:
    gold = [Span(0, 5, "STUDY_ID"), Span(10, 15, "STUDY_ID")]
    pred = [Span(0, 5, "STUDY_ID")]
    counts = _score(gold, pred)
    c = counts["STUDY_ID"]
    assert c.tp == 1
    assert c.fn == 1
    assert c.precision == 1.0
    assert 0.0 < c.recall < 1.0


def test_label_mismatch_is_fp_and_fn() -> None:
    gold = [Span(0, 5, "STUDY_ID")]
    pred = [Span(0, 5, "TABLE_REF")]
    counts = _score(gold, pred)
    assert counts["TABLE_REF"].fp == 1
    assert counts["STUDY_ID"].fn == 1


def test_partial_overlap_counts_as_match() -> None:
    gold = [Span(0, 10, "STUDY_ID")]
    pred = [Span(5, 15, "STUDY_ID")]
    counts = _score(gold, pred)
    assert counts["STUDY_ID"].tp == 1


def test_aggregate_sums_across_documents() -> None:
    docs = [
        {"STUDY_ID": Counts(tp=2, fp=1, fn=0)},
        {"STUDY_ID": Counts(tp=3, fp=0, fn=2)},
        {"TABLE_REF": Counts(tp=1, fp=0, fn=0)},
    ]
    totals = _aggregate(docs)
    assert totals["STUDY_ID"].tp == 5
    assert totals["STUDY_ID"].fp == 1
    assert totals["STUDY_ID"].fn == 2
    assert totals["TABLE_REF"].tp == 1


def test_counts_with_zero_denominators() -> None:
    c = Counts()
    assert c.precision == 0.0
    assert c.recall == 0.0
    assert c.f1 == 0.0
