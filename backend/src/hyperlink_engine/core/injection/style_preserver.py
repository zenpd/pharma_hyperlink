"""Layer 4 — Dosscriber-aware style preservation.

The publishing team authors documents in Dosscriber. Those documents carry
custom paragraph + character styles ("Dosscriber_Heading", "DSC_Body",
template-derived ad-hoc styles) that the engine must NOT mutate.

This module:

1. Snapshots every paragraph + run's style fingerprint before injection.
2. Re-takes the snapshot after injection.
3. Diffs them and reports any mutation that wasn't an intentional link.

The validation layer (W4.4) consumes the diff to surface STYLE_MUTATION
anomalies. Phase 1 reports them; Phase 4 / production may auto-reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import AnomalyKind, AnomalySeverity

_log = get_logger("injection.style_preserver")


# Style-name prefixes that signal a Dosscriber-template style. Treated as
# read-only by the injector — touching one of these is a hard anomaly even
# at WARNING severity.
_DOSSCRIBER_PREFIXES = ("Dosscriber", "DSC_", "DSC-", "Celegence_", "CLG_")


@dataclass(frozen=True)
class RunFingerprint:
    """Minimal style signature captured per run."""

    paragraph_index: int
    run_index: int
    text: str
    bold: bool
    italic: bool
    underline: bool
    font_name: str | None
    font_size_pt: float | None
    color_rgb: str | None
    style_name: str | None


@dataclass(frozen=True)
class StyleSnapshot:
    """Fingerprint of every run in a document at a point in time."""

    runs: tuple[RunFingerprint, ...]

    def by_location(self) -> dict[tuple[int, int], RunFingerprint]:
        return {(r.paragraph_index, r.run_index): r for r in self.runs}


@dataclass(frozen=True)
class StyleMutation:
    """One row in the post-injection diff."""

    paragraph_index: int
    run_index: int
    field: str  # "bold" | "color_rgb" | "style_name" | ...
    before: object
    after: object
    is_dosscriber_style: bool
    severity: AnomalySeverity
    kind: AnomalyKind = AnomalyKind.STYLE_MUTATION


# ─────────────────────────────────────────────────────────────────────────


def _is_dosscriber_style(style_name: str | None) -> bool:
    if not style_name:
        return False
    return any(style_name.startswith(prefix) for prefix in _DOSSCRIBER_PREFIXES)


def _run_fingerprint(p_idx: int, r_idx: int, run) -> RunFingerprint:  # type: ignore[no-untyped-def]
    rgb = None
    try:
        if run.font.color is not None and run.font.color.rgb is not None:
            rgb = str(run.font.color.rgb).upper()
    except (AttributeError, ValueError):
        rgb = None
    size_pt: float | None
    try:
        size_pt = float(run.font.size.pt) if run.font.size is not None else None
    except (AttributeError, ValueError):
        size_pt = None
    style_name = None
    try:
        if run.style is not None:
            style_name = run.style.name
    except AttributeError:
        style_name = None
    return RunFingerprint(
        paragraph_index=p_idx,
        run_index=r_idx,
        text=run.text,
        bold=bool(run.bold),
        italic=bool(run.italic),
        underline=bool(run.underline),
        font_name=run.font.name,
        font_size_pt=size_pt,
        color_rgb=rgb,
        style_name=style_name,
    )


def snapshot(path: Path) -> StyleSnapshot:
    """Take a style snapshot of every run in the document at `path`."""
    document = Document(str(path))
    runs: list[RunFingerprint] = []
    for p_idx, para in enumerate(document.paragraphs):
        for r_idx, run in enumerate(para.runs):
            runs.append(_run_fingerprint(p_idx, r_idx, run))
    return StyleSnapshot(runs=tuple(runs))


_FIELDS_TO_DIFF: tuple[str, ...] = (
    "bold",
    "italic",
    "underline",
    "font_name",
    "font_size_pt",
    "color_rgb",
    "style_name",
)


def diff(
    before: StyleSnapshot,
    after: StyleSnapshot,
    *,
    intentional_runs: set[tuple[int, int]] | None = None,
) -> list[StyleMutation]:
    """Compare two snapshots and return every unexpected style change.

    ``intentional_runs`` lists ``(paragraph_index, run_index)`` pairs the
    injector deliberately rewrote (the actual link spans). Mutations on
    those runs are not reported.
    """
    intentional = intentional_runs or set()
    before_idx = before.by_location()
    after_idx = after.by_location()
    mutations: list[StyleMutation] = []

    for key, before_run in before_idx.items():
        if key in intentional:
            continue
        after_run = after_idx.get(key)
        if after_run is None:
            # Run vanished — that's a structural change. Phase 1 records it
            # as a STYLE_MUTATION; later phases may upgrade severity.
            mutations.append(
                StyleMutation(
                    paragraph_index=key[0],
                    run_index=key[1],
                    field="(deleted)",
                    before=before_run.text,
                    after=None,
                    is_dosscriber_style=_is_dosscriber_style(before_run.style_name),
                    severity=AnomalySeverity.BLOCKER,
                )
            )
            continue
        for field in _FIELDS_TO_DIFF:
            b = getattr(before_run, field)
            a = getattr(after_run, field)
            if b != a:
                is_dsc = _is_dosscriber_style(before_run.style_name) or _is_dosscriber_style(after_run.style_name)
                severity = AnomalySeverity.BLOCKER if is_dsc else AnomalySeverity.WARNING
                mutations.append(
                    StyleMutation(
                        paragraph_index=key[0],
                        run_index=key[1],
                        field=field,
                        before=b,
                        after=a,
                        is_dosscriber_style=is_dsc,
                        severity=severity,
                    )
                )

    _log.info(
        "style_diff",
        before_runs=len(before.runs),
        after_runs=len(after.runs),
        mutations=len(mutations),
        intentional_count=len(intentional),
    )
    return mutations
