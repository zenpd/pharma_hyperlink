"""W3.5 — Accuracy benchmark for the detection pipeline.

Loads the labeled JSONL produced by ``scripts/label_references.py`` and runs
the configured EntityExtractor over every example. Reports per-label
precision, recall, F1, and a global F1.

Phase 1 gate: ≥90% F1 on the dev split before leaving Week 3.

Usage:
    python -m scripts.benchmark                           # regex-only
    python -m scripts.benchmark --mode regex_plus_ner
    python -m scripts.benchmark --mode full_cascade
    python -m scripts.benchmark --gold data/training/refs.dev.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hyperlink_engine.core.detection.entity_extractor import (
    EntityExtractor,
    full_cascade,
    regex_only,
    regex_plus_ner,
)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str

    def overlaps(self, other: "Span") -> bool:
        return not (self.end <= other.start or other.end <= self.start)


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _load_gold(path: Path) -> Iterable[tuple[str, list[Span]]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            spans = [Span(int(s), int(e), str(label)) for s, e, label in row["entities"]]
            yield row["text"], spans


def _score(gold: list[Span], pred: list[Span]) -> dict[str, Counts]:
    """Match by (label, overlap) — the standard relaxed NER metric.

    A predicted span counts as a TP for its label iff it overlaps a gold
    span with the same label; matched gold spans are consumed so each gold
    contributes to at most one TP.
    """
    counts: dict[str, Counts] = defaultdict(Counts)
    remaining_gold = list(gold)
    for p in pred:
        match_idx = -1
        for i, g in enumerate(remaining_gold):
            if g.label == p.label and p.overlaps(g):
                match_idx = i
                break
        if match_idx >= 0:
            counts[p.label].tp += 1
            remaining_gold.pop(match_idx)
        else:
            counts[p.label].fp += 1
    for g in remaining_gold:
        counts[g.label].fn += 1
    return counts


def _aggregate(per_doc: list[dict[str, Counts]]) -> dict[str, Counts]:
    total: dict[str, Counts] = defaultdict(Counts)
    for doc in per_doc:
        for label, c in doc.items():
            total[label].tp += c.tp
            total[label].fp += c.fp
            total[label].fn += c.fn
    return total


def _build_extractor(mode: str) -> EntityExtractor:
    if mode == "regex_only":
        return regex_only()
    if mode == "regex_plus_ner":
        return regex_plus_ner()
    if mode == "full_cascade":
        return full_cascade(prefer_stub=True)
    raise SystemExit(f"unknown mode {mode!r}")


def _print_table(totals: dict[str, Counts], gate: float) -> bool:
    labels = sorted(totals.keys())
    width = max(14, max(len(label) for label in labels))
    print(f"{'label'.ljust(width)}  {'P':>6}  {'R':>6}  {'F1':>6}  {'TP':>5}  {'FP':>5}  {'FN':>5}")
    print("-" * (width + 44))
    macro_f1 = 0.0
    for label in labels:
        c = totals[label]
        print(
            f"{label.ljust(width)}  {c.precision:6.3f}  {c.recall:6.3f}  "
            f"{c.f1:6.3f}  {c.tp:5d}  {c.fp:5d}  {c.fn:5d}"
        )
        macro_f1 += c.f1
    macro_f1 /= max(1, len(labels))
    global_counts = Counts()
    for c in totals.values():
        global_counts.tp += c.tp
        global_counts.fp += c.fp
        global_counts.fn += c.fn
    print("-" * (width + 44))
    print(
        f"{'micro'.ljust(width)}  {global_counts.precision:6.3f}  "
        f"{global_counts.recall:6.3f}  {global_counts.f1:6.3f}  "
        f"{global_counts.tp:5d}  {global_counts.fp:5d}  {global_counts.fn:5d}"
    )
    print(f"{'macro F1'.ljust(width)}  {'':>6}  {'':>6}  {macro_f1:6.3f}")
    passed = global_counts.f1 >= gate
    flag = "PASS" if passed else "FAIL"
    print(f"\nGate (>={gate:.2f} micro F1): {flag}")
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark")
    parser.add_argument(
        "--mode",
        choices=("regex_only", "regex_plus_ner", "full_cascade"),
        default="regex_only",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=Path("data/training/refs.dev.jsonl"),
    )
    parser.add_argument("--gate", type=float, default=0.90)
    args = parser.parse_args(argv)

    if not args.gold.exists():
        raise SystemExit(
            f"{args.gold} does not exist — run `python -m scripts.label_references` first."
        )

    extractor = _build_extractor(args.mode)
    per_doc: list[dict[str, Counts]] = []
    for text, gold in _load_gold(args.gold):
        refs = extractor.extract(text)
        pred = [Span(r.start, r.end, r.label) for r in refs]
        per_doc.append(_score(gold, pred))

    totals = _aggregate(per_doc)
    print(f"mode={args.mode}  gold={args.gold}  examples={len(per_doc)}\n")
    passed = _print_table(totals, args.gate)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
