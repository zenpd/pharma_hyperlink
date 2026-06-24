"""Throwaway diagnostic (DOCX) — PLAN TEN-bis.

Parallel to diag_anchor_fallback.py but for Word. Per caption-label key, report
anchored-at-DEFINITION vs FELL-BACK-to-citation, and for fall-backs show the
per-run ``context`` that failed _is_caption_definition AND the full paragraph
text — exposing whether the full paragraph would have passed (run fragmentation /
number-doesn't-lead) vs the definition being genuinely absent.

Run:  .venv/Scripts/python.exe scripts/diag_anchor_fallback_docx.py <docx> [...]
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from docx import Document

from hyperlink_engine.core.injection.anchor_index import (
    _CAPTION_LABELS,
    _is_caption_definition,
    build_anchor_index,
    canonical_anchor_key,
)
from hyperlink_engine.workers.tasks import detect_references


def _para_texts(path: str) -> list[str]:
    return [p.text for p in Document(path).paragraphs]


def diagnose(docx: Path) -> tuple[int, int]:
    rec = {"source_path": str(docx), "filename": docx.name}
    det_record = detect_references(rec)
    detections = det_record["detections"]
    index = build_anchor_index(detections, str(docx), is_pdf=False)
    paras = _para_texts(str(docx))

    by_key: dict[str, list[dict]] = defaultdict(list)
    for det in detections:
        if det.get("label") not in _CAPTION_LABELS:
            continue
        num = (det.get("groups") or {}).get("num") or det.get("text", "")
        if not num:
            continue
        by_key[canonical_anchor_key(det["label"], num)].append(det)

    anchored = sum(1 for k in by_key if k in index)
    fellback = sum(1 for k in by_key if k not in index)

    print(f"\n=== {docx.name} ===")
    print(f"  caption-label keys referenced : {len(by_key)}")
    print(f"  anchored at DEFINITION         : {anchored}")
    print(f"  FELL BACK to citation          : {fellback}")

    if fellback:
        print("  --- fall-backs (key | run context | full paragraph) ---")
        shown = 0
        for key in sorted(by_key):
            if key in index:
                continue
            det = max(by_key[key], key=lambda d: len(d.get("context", "")))
            ctx = (det.get("context") or "").strip()
            p_idx = det.get("paragraph_index", -1)
            para = paras[p_idx].strip() if 0 <= p_idx < len(paras) else ctx
            passes_para = _is_caption_definition(para, det["label"])
            flag = "  <-- full PARAGRAPH would pass" if passes_para else ""
            print(f"    {key}")
            print(f"        run ctx  : {ctx[:90]!r}")
            print(f"        para     : {para[:90]!r}{flag}")
            shown += 1
            if shown >= 25:
                print(f"    … (+{fellback - shown} more)")
                break
    return anchored, fellback


def main(argv: list[str]) -> int:
    tot_a = tot_f = 0
    for a in argv:
        p = Path(a)
        if not p.exists():
            print(f"!! missing: {p}")
            continue
        ay, fy = diagnose(p)
        tot_a += ay
        tot_f += fy
    print("\n==================  TOTAL  ==================")
    print(f"  anchored at DEFINITION : {tot_a}")
    print(f"  FELL BACK to citation  : {tot_f}")
    denom = tot_a + tot_f
    if denom:
        print(f"  definition rate        : {100 * tot_a / denom:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
