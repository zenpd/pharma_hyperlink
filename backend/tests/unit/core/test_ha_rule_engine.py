"""Unit tests for validation/ha_rule_engine.py (W10.1)."""

from __future__ import annotations

from pathlib import Path

import yaml

from hyperlink_engine.core.validation.ha_rule_engine import (
    HA_RULE_VALIDATORS,
    DossierContext,
    HaRule,
    HaRuleEngine,
    HaRuleReport,
    ema_bookmark_depth_min_2,
    espre_filename_convention,
    fda_bookmark_depth_min_3,
    hyperlink_color_blue,
    leaf_title_max_length,
    load_rules,
    pdf_a_1b_or_2b_compliance,
    pdf_a_2b_compliance,
    pmda_sjis_round_trip,
)
from hyperlink_engine.models import (
    AnomalySeverity,
    BackboneLeaf,
    BackboneSnapshot,
    DocumentProvenance,
    HaRegion,
    LeafOperation,
    PdfDocument,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _provenance(name: str = "x.pdf") -> DocumentProvenance:
    return DocumentProvenance(
        source_path=Path(name),
        sha256="0" * 64,
        file_size_bytes=100,
    )


def _backbone(leaves: list[BackboneLeaf]) -> BackboneSnapshot:
    return BackboneSnapshot(
        provenance=_provenance("index.xml"),
        schema_version="v3.2",
        leaves=leaves,
    )


def _leaf(
    leaf_id: str = "leaf-001",
    relative_path: str = "m2/2-5.pdf",
    title: str | None = "Clinical Overview",
    module: str = "m2.5",
) -> BackboneLeaf:
    return BackboneLeaf(
        leaf_id=leaf_id,
        relative_path=Path(relative_path),
        module=module,
        operation=LeafOperation.NEW,
        title=title,
    )


def _pdf(bookmarks: list[tuple[int, str, int]], *, is_pdf_a: bool = True) -> PdfDocument:
    return PdfDocument(
        provenance=_provenance("rendition.pdf"),
        page_count=10,
        pages=[],
        bookmarks=bookmarks,
        is_pdf_a=is_pdf_a,
    )


def _rule(
    rule_id: str = "TEST_RULE",
    validator: str = "fda_bookmark_depth_min_3",
    region: HaRegion = HaRegion.US,
    severity: AnomalySeverity = AnomalySeverity.BLOCKER,
    params: dict | None = None,
) -> HaRule:
    return HaRule(
        id=rule_id,
        region=region,
        description="test rule",
        severity=severity,
        validator=validator,
        params=params or {},
    )


# ── Bookmark depth validators ────────────────────────────────────────────────


def test_fda_bookmark_depth_passes_when_deep_enough() -> None:
    pdf = _pdf(bookmarks=[(1, "A", 0), (2, "B", 1), (3, "C", 2)])
    ctx = DossierContext(pdf_docs=[pdf])
    violations = fda_bookmark_depth_min_3(_rule(), ctx)
    assert violations == []


def test_fda_bookmark_depth_fails_when_too_shallow() -> None:
    pdf = _pdf(bookmarks=[(1, "A", 0), (2, "B", 1)])
    ctx = DossierContext(pdf_docs=[pdf])
    violations = fda_bookmark_depth_min_3(_rule(), ctx)
    assert len(violations) == 1
    assert "max bookmark depth = 2" in violations[0].detail


def test_fda_bookmark_depth_empty_bookmarks() -> None:
    pdf = _pdf(bookmarks=[])
    ctx = DossierContext(pdf_docs=[pdf])
    violations = fda_bookmark_depth_min_3(_rule(), ctx)
    assert len(violations) == 1


def test_ema_bookmark_depth_min_2() -> None:
    pdf = _pdf(bookmarks=[(1, "A", 0)])
    ctx = DossierContext(pdf_docs=[pdf])
    violations = ema_bookmark_depth_min_2(
        _rule(validator="ema_bookmark_depth_min_2", region=HaRegion.EU), ctx
    )
    assert len(violations) == 1


# ── PDF/A validators ──────────────────────────────────────────────────────────


def test_pdf_a_2b_passes_when_compliant() -> None:
    pdf = _pdf(bookmarks=[(1, "A", 0)], is_pdf_a=True)
    ctx = DossierContext(pdf_docs=[pdf])
    assert pdf_a_2b_compliance(_rule(validator="pdf_a_2b_compliance"), ctx) == []


def test_pdf_a_2b_fails_when_not_pdfa() -> None:
    pdf = _pdf(bookmarks=[], is_pdf_a=False)
    ctx = DossierContext(pdf_docs=[pdf])
    violations = pdf_a_2b_compliance(_rule(validator="pdf_a_2b_compliance"), ctx)
    assert len(violations) == 1


def test_pdf_a_1b_or_2b_accepts_pdfa() -> None:
    pdf = _pdf(bookmarks=[], is_pdf_a=True)
    ctx = DossierContext(pdf_docs=[pdf])
    assert pdf_a_1b_or_2b_compliance(_rule(), ctx) == []


# ── Hyperlink-color (blue) validator ─────────────────────────────────────────


def test_hyperlink_color_blue_warns_on_orphan_blue_runs() -> None:
    ctx = DossierContext(docx_blue_runs_by_path={"x.docx": [(0, 3), (1, 5)]})
    violations = hyperlink_color_blue(_rule(validator="hyperlink_color_blue"), ctx)
    assert len(violations) == 1
    assert "2 blue run(s)" in violations[0].detail


def test_hyperlink_color_blue_no_orphans_no_warnings() -> None:
    ctx = DossierContext(docx_blue_runs_by_path={"x.docx": []})
    assert hyperlink_color_blue(_rule(validator="hyperlink_color_blue"), ctx) == []


# ── ESPRE filename convention ────────────────────────────────────────────────


def test_espre_filename_passes_for_lowercase_hyphen_separated() -> None:
    leaf = _leaf(relative_path="m1/eu/cover-letter.pdf")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="espre_filename_convention", region=HaRegion.EU)
    assert espre_filename_convention(rule, ctx) == []


def test_espre_filename_flags_uppercase() -> None:
    leaf = _leaf(relative_path="m1/eu/CoverLetter.pdf")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="espre_filename_convention", region=HaRegion.EU)
    violations = espre_filename_convention(rule, ctx)
    assert len(violations) == 1
    assert "uppercase" in violations[0].detail


def test_espre_filename_flags_leading_underscore() -> None:
    leaf = _leaf(relative_path="m1/eu/_letter.pdf")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="espre_filename_convention", region=HaRegion.EU)
    violations = espre_filename_convention(rule, ctx)
    assert violations
    assert "underscore" in violations[0].detail


def test_espre_filename_no_backbone_returns_empty() -> None:
    ctx = DossierContext()
    rule = _rule(validator="espre_filename_convention", region=HaRegion.EU)
    assert espre_filename_convention(rule, ctx) == []


# ── Leaf title length ────────────────────────────────────────────────────────


def test_leaf_title_length_within_limit() -> None:
    leaf = _leaf(title="A short title")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="leaf_title_max_length", params={"max_length": 64})
    assert leaf_title_max_length(rule, ctx) == []


def test_leaf_title_length_too_long() -> None:
    leaf = _leaf(title="x" * 100)
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="leaf_title_max_length", params={"max_length": 64})
    violations = leaf_title_max_length(rule, ctx)
    assert len(violations) == 1
    assert "title length 100 > max 64" in violations[0].detail


def test_leaf_title_length_skips_empty_titles() -> None:
    leaf = _leaf(title=None)
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="leaf_title_max_length", params={"max_length": 64})
    assert leaf_title_max_length(rule, ctx) == []


# ── PMDA Shift-JIS validator ─────────────────────────────────────────────────


def test_pmda_sjis_passes_ascii() -> None:
    leaf = _leaf(title="Clinical Overview")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="pmda_sjis_round_trip", region=HaRegion.JP)
    assert pmda_sjis_round_trip(rule, ctx) == []


def test_pmda_sjis_passes_jis_japanese() -> None:
    # Standard JIS-X-0208 characters round-trip cleanly
    leaf = _leaf(title="臨床概要")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="pmda_sjis_round_trip", region=HaRegion.JP)
    assert pmda_sjis_round_trip(rule, ctx) == []


def test_pmda_sjis_fails_emoji() -> None:
    leaf = _leaf(title="Clinical 📋 Overview")
    ctx = DossierContext(backbone=_backbone([leaf]))
    rule = _rule(validator="pmda_sjis_round_trip", region=HaRegion.JP)
    violations = pmda_sjis_round_trip(rule, ctx)
    assert len(violations) == 1


# ── HaRuleEngine orchestrator ────────────────────────────────────────────────


def test_engine_evaluates_with_default_rules() -> None:
    engine = HaRuleEngine()
    pdf = _pdf(bookmarks=[(1, "a", 0), (2, "b", 1), (3, "c", 2)])
    leaf = _leaf(relative_path="m1/us/cover-letter.pdf", title="Cover Letter")
    ctx = DossierContext(backbone=_backbone([leaf]), pdf_docs=[pdf])
    report = engine.evaluate(ctx)
    assert isinstance(report, HaRuleReport)
    assert report.rules_run > 0


def test_engine_filters_by_region() -> None:
    engine = HaRuleEngine()
    ctx = DossierContext()
    us_report = engine.evaluate(ctx, regions=[HaRegion.US])
    eu_report = engine.evaluate(ctx, regions=[HaRegion.EU])
    # Only rules for the requested region should run
    assert us_report.rules_run > 0
    assert eu_report.rules_run > 0
    # Without any backbone/pdf data most rules produce no violations.
    assert not any(v.region != HaRegion.US for v in us_report.violations)


def test_engine_skips_missing_validator() -> None:
    fake_rule = HaRule(
        id="GHOST",
        region=HaRegion.US,
        description="missing validator",
        severity=AnomalySeverity.WARNING,
        validator="this_does_not_exist",
    )
    engine = HaRuleEngine(rules=[fake_rule])
    report = engine.evaluate(DossierContext())
    assert report.rules_skipped_missing_validator == 1
    assert report.rules_run == 0


def test_engine_report_helpers() -> None:
    pdf = _pdf(bookmarks=[(1, "a", 0)], is_pdf_a=False)
    ctx = DossierContext(pdf_docs=[pdf])
    engine = HaRuleEngine()
    report = engine.evaluate(ctx, regions=[HaRegion.US])
    assert report.blocker_count >= 1
    assert not report.passed
    us_violations = report.by_region(HaRegion.US)
    assert len(us_violations) == len(report.violations)


# ── load_rules ───────────────────────────────────────────────────────────────


def test_load_rules_from_default_path() -> None:
    rules = load_rules()
    assert rules
    rule_ids = {r.id for r in rules}
    assert "FDA_BOOKMARK_DEPTH" in rule_ids
    assert "EMA_ESPRE_NAMING" in rule_ids


def test_load_rules_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_rules(tmp_path / "missing.yaml") == []


def test_load_rules_skips_unknown_region(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        yaml.dump(
            {
                "weird": {
                    "region": "atlantis",
                    "rules": [
                        {
                            "id": "X",
                            "description": "y",
                            "severity": "blocker",
                            "validator": "z",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    assert load_rules(bad) == []


def test_validator_registry_lists_all_referenced_validators() -> None:
    """Every YAML-referenced validator string must resolve."""
    rules = load_rules()
    referenced = {r.validator for r in rules}
    missing = referenced - set(HA_RULE_VALIDATORS.keys())
    assert not missing, f"YAML references missing validators: {missing}"
