"""Gold-set evaluation for reference-name detection (PLAN NINETEEN, Phase C).

Measures regex vs GLiNER vs hybrid on a hand-labelled gold set BEFORE flipping the
default detector. A wrong author link is worse than a miss, so the gate to enable
GLiNER is: recall >= regex AND precision >= regex.

Gold format (``scripts/eval_data/references_gold.json``): a list of cases, each
``{"name", "body", "gold": [[surname, year], ...]}`` where ``gold`` is every IN-TEXT
author-year citation that SHOULD be detected (the body mentions — NOT the References
entries). Surnames are compared case-insensitively.

Run (regex always; GLiNER only if the optional ``gliner`` package is installed):
    python -m scripts.eval_references
"""

from __future__ import annotations

import json
from pathlib import Path

from hyperlink_engine.core.detection.gliner_refs import available as _gliner_available
from hyperlink_engine.core.detection.gliner_refs import gliner_ref_cites
from hyperlink_engine.core.injection.ref_index import _AUTHOR_YEAR, _MONTHS

GOLD = Path(__file__).resolve().parent / "eval_data" / "references_gold.json"


def _norm(pairs) -> set[tuple[str, str]]:
    return {(s.lower(), str(y)) for s, y in pairs}


def _regex_pred(text: str) -> set[tuple[str, str]]:
    return {
        (m.group("surname").lower(), m.group("year"))
        for m in _AUTHOR_YEAR.finditer(text or "")
        if m.group("surname").lower() not in _MONTHS
    }


def _gliner_pred(text: str) -> set[tuple[str, str]]:
    return {(c.group("surname").lower(), c.group("year")) for c in gliner_ref_cites(text or "")}


def _score(pred: set, gold: set) -> tuple[float, float, float, int, int, int]:
    tp = len(pred & gold)
    fp = len(pred - gold)
    fn = len(gold - pred)
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1, tp, fp, fn


def main() -> None:
    cases = json.loads(GOLD.read_text(encoding="utf-8"))
    have_gliner = _gliner_available()
    detectors = {"regex": _regex_pred}
    if have_gliner:
        detectors["gliner"] = _gliner_pred
        detectors["hybrid"] = lambda t: _regex_pred(t) | _gliner_pred(t)
    else:
        print("NOTE: gliner not installed → only the regex column is real.\n")

    agg: dict[str, set] = {k: set() for k in detectors}
    agg_gold: set = set()
    print(f"{'case':<22}{'detector':<10}{'P':>6}{'R':>6}{'F1':>6}   tp/fp/fn")
    print("-" * 66)
    for c in cases:
        gold = _norm(c["gold"])
        agg_gold |= {(c["name"], s, y) for s, y in gold}
        for name, fn in detectors.items():
            pred = fn(c["body"])
            agg[name] |= {(c["name"], s, y) for s, y in pred}
            p, r, f1, tp, fp, fnn = _score(pred, gold)
            print(f"{c['name'][:21]:<22}{name:<10}{p:>6.2f}{r:>6.2f}{f1:>6.2f}   {tp}/{fp}/{fnn}")
        print()

    print("=" * 66, "\nOVERALL (micro-averaged across all cases):")
    for name in detectors:
        p, r, f1, tp, fp, fnn = _score(agg[name], agg_gold)
        print(f"  {name:<8} P={p:.2f}  R={r:.2f}  F1={f1:.2f}   (tp={tp} fp={fp} fn={fnn})")
    if not have_gliner:
        print("\nInstall gliner in the backend venv to get the gliner/hybrid columns.")


if __name__ == "__main__":
    main()
