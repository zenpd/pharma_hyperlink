"""W10.1 — Health Authority (HA) Rules Engine.

Loads the YAML rule definitions from ``config/ha_rules.yaml`` and evaluates
them against a :class:`DossierContext` (a lightweight collection of the
artefacts a rule may need: backbone snapshot, list of PDF paths, parsed
docx documents, etc.).

Each rule names a ``validator`` string that the engine looks up in
:data:`HA_RULE_VALIDATORS`.  A validator returns ``None`` (rule passed)
or an :class:`models.HaViolation`.

Example
-------
>>> ctx = DossierContext(...)
>>> engine = HaRuleEngine()
>>> violations = engine.evaluate(ctx, regions=[HaRegion.US])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import yaml

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import (
    AnomalySeverity,
    BackboneSnapshot,
    HaRegion,
    HaViolation,
    PdfDocument,
)

_log = get_logger("validation.ha_rule_engine")

# ─────────────────────────────────────────────────────────────────────────────
# Default rules file lookup
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "ha_rules.yaml"


# ─────────────────────────────────────────────────────────────────────────────
# DossierContext — input to every validator
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DossierContext:
    """Bundle of artefacts an HA rule may inspect.

    Every field is optional; validators must guard for missing inputs.
    """

    backbone: BackboneSnapshot | None = None
    pdf_docs: list[PdfDocument] = field(default_factory=list)
    docx_blue_runs_by_path: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Rule + RuleSet dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HaRule:
    """One rule loaded from the YAML config."""

    id: str
    region: HaRegion
    description: str
    severity: AnomalySeverity
    validator: str
    applicable_modules: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Validator implementations
# ─────────────────────────────────────────────────────────────────────────────


def _violation(
    rule: HaRule, *, target: str, detail: str | None = None
) -> HaViolation:
    return HaViolation(
        rule_id=rule.id,
        region=rule.region,
        severity=rule.severity,
        description=rule.description,
        target=target,
        detail=detail,
    )


def _bookmark_depth(pdf: PdfDocument) -> int:
    """Maximum level in the PDF's bookmark outline (1 = no nested levels)."""
    if not pdf.bookmarks:
        return 0
    return max(level for level, _title, _page in pdf.bookmarks)


def _check_bookmark_depth_min(
    rule: HaRule, ctx: DossierContext, *, min_depth: int
) -> list[HaViolation]:
    out: list[HaViolation] = []
    for pdf in ctx.pdf_docs:
        depth = _bookmark_depth(pdf)
        if depth < min_depth:
            out.append(
                _violation(
                    rule,
                    target=str(pdf.provenance.source_path),
                    detail=f"max bookmark depth = {depth}, required ≥ {min_depth}",
                )
            )
    return out


def fda_bookmark_depth_min_3(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    return _check_bookmark_depth_min(rule, ctx, min_depth=rule.params.get("min_depth", 3))


def ema_bookmark_depth_min_2(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    return _check_bookmark_depth_min(rule, ctx, min_depth=rule.params.get("min_depth", 2))


def pmda_bookmark_depth_min_3(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    return _check_bookmark_depth_min(rule, ctx, min_depth=rule.params.get("min_depth", 3))


def hc_bookmark_depth_min_3(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    return _check_bookmark_depth_min(rule, ctx, min_depth=rule.params.get("min_depth", 3))


def _pdf_a_check(
    rule: HaRule, ctx: DossierContext, *, accepted: set[str]
) -> list[HaViolation]:
    """Verify each PDF carries a PDF/A flag that matches ``accepted``.

    Parsing the exact PDF/A part / conformance level requires inspecting
    the XMP metadata.  PyMuPDF exposes a simple ``is_pdf_a`` boolean in
    our :class:`PdfDocument`; richer checks live in Phase 4.
    """
    out: list[HaViolation] = []
    for pdf in ctx.pdf_docs:
        if not pdf.is_pdf_a:
            out.append(
                _violation(
                    rule,
                    target=str(pdf.provenance.source_path),
                    detail=f"file is not PDF/A — required: any of {sorted(accepted)}",
                )
            )
    return out


def pdf_a_2b_compliance(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    return _pdf_a_check(rule, ctx, accepted={"PDF/A-2b"})


def pdf_a_1b_or_2b_compliance(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    return _pdf_a_check(rule, ctx, accepted={"PDF/A-1b", "PDF/A-2b"})


def hyperlink_color_blue(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    """Warn when a docx contains blue-coloured runs WITHOUT a hyperlink.

    Re-uses the anomaly-detector's blue-run scan via the context's
    pre-computed ``docx_blue_runs_by_path`` map (populated by the caller).
    The FDA convention is for hyperlinks to be blue — orphan blue runs
    suggest the author intended a link but forgot to attach one.
    """
    out: list[HaViolation] = []
    for path, blue_runs in ctx.docx_blue_runs_by_path.items():
        if blue_runs:
            out.append(
                _violation(
                    rule,
                    target=path,
                    detail=f"{len(blue_runs)} blue run(s) without hyperlink",
                )
            )
    return out


def espre_filename_convention(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    """ESPRE filename rules: lowercase ASCII, hyphen-separated, no leading underscore."""
    out: list[HaViolation] = []
    if ctx.backbone is None:
        return out
    for leaf in ctx.backbone.leaves:
        name = Path(leaf.relative_path).name
        problems: list[str] = []
        if name != name.lower():
            problems.append("contains uppercase characters")
        if " " in name:
            problems.append("contains spaces")
        if name.startswith("_"):
            problems.append("starts with underscore")
        try:
            name.encode("ascii")
        except UnicodeEncodeError:
            problems.append("contains non-ASCII characters")
        if problems:
            out.append(
                _violation(
                    rule,
                    target=leaf.leaf_id,
                    detail="; ".join(problems),
                )
            )
    return out


def leaf_title_max_length(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    """Generic leaf-title length check (per-region max via rule params)."""
    out: list[HaViolation] = []
    if ctx.backbone is None:
        return out
    max_len = int(rule.params.get("max_length", 256))
    for leaf in ctx.backbone.leaves:
        if leaf.title and len(leaf.title) > max_len:
            out.append(
                _violation(
                    rule,
                    target=leaf.leaf_id,
                    detail=f"title length {len(leaf.title)} > max {max_len}",
                )
            )
    return out


def pmda_sjis_round_trip(rule: HaRule, ctx: DossierContext) -> list[HaViolation]:
    """Reject titles that cannot round-trip through Shift-JIS encoding."""
    out: list[HaViolation] = []
    if ctx.backbone is None:
        return out
    for leaf in ctx.backbone.leaves:
        if not leaf.title:
            continue
        try:
            encoded = leaf.title.encode("shift_jis")
            decoded = encoded.decode("shift_jis")
            if decoded != leaf.title:
                out.append(
                    _violation(
                        rule,
                        target=leaf.leaf_id,
                        detail="title round-trip through Shift-JIS lost characters",
                    )
                )
        except (UnicodeEncodeError, UnicodeDecodeError) as exc:
            out.append(
                _violation(
                    rule,
                    target=leaf.leaf_id,
                    detail=f"Shift-JIS encoding failed: {exc.reason}",
                )
            )
    return out


# Registry — must be updated whenever a new validator is added above
HA_RULE_VALIDATORS: dict[
    str, Callable[[HaRule, DossierContext], list[HaViolation]]
] = {
    "fda_bookmark_depth_min_3": fda_bookmark_depth_min_3,
    "ema_bookmark_depth_min_2": ema_bookmark_depth_min_2,
    "pmda_bookmark_depth_min_3": pmda_bookmark_depth_min_3,
    "hc_bookmark_depth_min_3": hc_bookmark_depth_min_3,
    "pdf_a_2b_compliance": pdf_a_2b_compliance,
    "pdf_a_1b_or_2b_compliance": pdf_a_1b_or_2b_compliance,
    "hyperlink_color_blue": hyperlink_color_blue,
    "espre_filename_convention": espre_filename_convention,
    "leaf_title_max_length": leaf_title_max_length,
    "pmda_sjis_round_trip": pmda_sjis_round_trip,
}


# ─────────────────────────────────────────────────────────────────────────────
# Loader + engine
# ─────────────────────────────────────────────────────────────────────────────


def load_rules(path: Path | None = None) -> list[HaRule]:
    """Parse the YAML rules file into :class:`HaRule` instances."""
    path = Path(path) if path else _DEFAULT_RULES_PATH
    if not path.exists():
        _log.warning("ha_rules_missing", path=str(path))
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _log.warning("ha_rules_malformed", path=str(path))
        return []

    out: list[HaRule] = []
    for ha_key, ha_block in raw.items():
        if not isinstance(ha_block, dict):
            continue
        region_str = ha_block.get("region")
        try:
            region = HaRegion(region_str)
        except ValueError:
            _log.warning(
                "ha_rules_skip_unknown_region",
                ha_key=ha_key,
                region=region_str,
            )
            continue
        for rule_dict in ha_block.get("rules", []):
            if not isinstance(rule_dict, dict) or "id" not in rule_dict:
                continue
            try:
                severity = AnomalySeverity(rule_dict.get("severity", "warning"))
            except ValueError:
                severity = AnomalySeverity.WARNING
            out.append(
                HaRule(
                    id=rule_dict["id"],
                    region=region,
                    description=rule_dict.get("description", "").strip(),
                    severity=severity,
                    validator=rule_dict.get("validator", ""),
                    applicable_modules=tuple(rule_dict.get("applicable_modules", []) or []),
                    params=dict(rule_dict.get("params", {}) or {}),
                )
            )
    _log.info("ha_rules_loaded", path=str(path), count=len(out))
    return out


@dataclass
class HaRuleReport:
    """Aggregated violations after evaluating an HA rule set."""

    violations: list[HaViolation] = field(default_factory=list)
    rules_run: int = 0
    rules_skipped_missing_validator: int = 0

    @property
    def blocker_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == AnomalySeverity.BLOCKER)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == AnomalySeverity.WARNING)

    @property
    def passed(self) -> bool:
        """True when no BLOCKER violations were emitted."""
        return self.blocker_count == 0

    def by_region(self, region: HaRegion) -> list[HaViolation]:
        return [v for v in self.violations if v.region == region]


class HaRuleEngine:
    """Evaluate a loaded rule set against a :class:`DossierContext`."""

    def __init__(self, rules: Sequence[HaRule] | None = None) -> None:
        self.rules: list[HaRule] = list(rules) if rules is not None else load_rules()

    def evaluate(
        self,
        context: DossierContext,
        *,
        regions: Iterable[HaRegion] | None = None,
    ) -> HaRuleReport:
        """Run every applicable rule against ``context``.

        Parameters
        ----------
        context:
            The dossier artefacts to inspect.
        regions:
            Filter to a subset of HA regions; defaults to all configured.
        """
        wanted_regions = set(regions) if regions else None
        report = HaRuleReport()
        for rule in self.rules:
            if wanted_regions and rule.region not in wanted_regions:
                continue
            validator = HA_RULE_VALIDATORS.get(rule.validator)
            if validator is None:
                report.rules_skipped_missing_validator += 1
                _log.warning(
                    "ha_rule_skipped_missing_validator",
                    rule_id=rule.id,
                    validator=rule.validator,
                )
                continue
            try:
                violations = validator(rule, context)
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning(
                    "ha_rule_validator_raised",
                    rule_id=rule.id,
                    error=str(exc),
                )
                continue
            report.rules_run += 1
            report.violations.extend(violations)
        _log.info(
            "ha_rules_evaluated",
            rules_run=report.rules_run,
            violations=len(report.violations),
            blockers=report.blocker_count,
            warnings=report.warning_count,
        )
        return report
