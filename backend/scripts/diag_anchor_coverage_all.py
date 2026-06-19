"""Per-label anchor coverage: for EVERY internal-anchor label (Section / Table /
Figure / Listing / Appendix), how many cited keys resolve to a definition in the
anchor index vs. fall back to the citation. Honest, type-by-type picture."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from hyperlink_engine.core.injection.anchor_index import build_anchor_index, canonical_anchor_key
from hyperlink_engine.workers.tasks import detect_references

_ANCHOR_LABELS = {"SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"}


def diagnose(path: Path, is_pdf: bool) -> dict[str, list[int]]:
    rec = {"source_path": str(path), "filename": path.name}
    detections = detect_references(rec)["detections"]
    index = build_anchor_index(detections, str(path), is_pdf=is_pdf)

    keys_by_label: dict[str, set[str]] = defaultdict(set)
    for det in detections:
        lab = det.get("label")
        if lab not in _ANCHOR_LABELS:
            continue
        num = (det.get("groups") or {}).get("num") or det.get("text", "")
        if num:
            keys_by_label[lab].add(canonical_anchor_key(lab, num))

    out: dict[str, list[int]] = {}
    for lab, keys in keys_by_label.items():
        anchored = sum(1 for k in keys if k in index)
        out[lab] = [anchored, len(keys)]
    return out


def main(argv: list[str]) -> int:
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for a in argv:
        p = Path(a)
        if not p.exists():
            print(f"!! missing: {p}")
            continue
        is_pdf = p.suffix.lower() == ".pdf"
        res = diagnose(p, is_pdf)
        print(f"\n=== {p.name} ===")
        for lab in ("SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"):
            if lab in res:
                a_n, tot = res[lab]
                print(f"  {lab:13} {a_n:3}/{tot:<3} to definition")
                totals[lab][0] += a_n
                totals[lab][1] += tot
    print("\n==================  TOTAL by label  ==================")
    for lab in ("SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"):
        a_n, tot = totals[lab]
        if tot:
            print(f"  {lab:13} {a_n:3}/{tot:<3}  ({100*a_n/tot:.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
