"""Throwaway diagnostic — PLAN TEN-bis.

For each PDF, run detection + build_anchor_index and report, per caption-label
key (Table/Figure/Listing/Appendix), whether the link anchors at the DEFINITION
(caption/heading) or FALLS BACK to the citation page. For every fall-back, show
the per-span ``context`` that failed _is_caption_definition AND the reconstructed
full text line, so we can see the real cause (number-doesn't-lead, fragmentation,
TOC line, lowercase title, …) rather than guessing.

Run:  .venv/Scripts/python.exe scripts/diag_anchor_fallback.py <pdf> [<pdf> ...]
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import fitz  # PyMuPDF

from hyperlink_engine.core.injection.anchor_index import (
    _CAPTION_LABELS,
    _is_caption_definition,
    build_anchor_index,
    canonical_anchor_key,
)
from hyperlink_engine.workers.tasks import detect_references


def _lines_by_page(path: str) -> dict[int, list[str]]:
    """Reconstruct full text lines per page (span texts joined)."""
    out: dict[int, list[str]] = defaultdict(list)
    doc = fitz.open(path)
    try:
        for pi in range(doc.page_count):
            page = doc.load_page(pi)
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type", 0) != 0:
                    continue
                for line in block.get("lines", []):
                    txt = "".join(s.get("text", "") for s in line.get("spans", []))
                    if txt.strip():
                        out[pi].append(txt.strip())
    finally:
        doc.close()
    return out


def _find_line(lines: list[str], span_text: str) -> str:
    span_text = (span_text or "").strip()
    for ln in lines:
        if span_text and span_text in ln:
            return ln
    return span_text


def diagnose(pdf: Path) -> tuple[int, int]:
    rec = {"source_path": str(pdf), "filename": pdf.name}
    det_record = detect_references(rec)
    detections = det_record["detections"]
    index = build_anchor_index(detections, str(pdf), is_pdf=True)
    lines = _lines_by_page(str(pdf))

    # Group caption-label detections by canonical key.
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

    print(f"\n=== {pdf.name} ===")
    print(f"  caption-label keys referenced : {len(by_key)}")
    print(f"  anchored at DEFINITION         : {anchored}")
    print(f"  FELL BACK to citation          : {fellback}")

    if fellback:
        print("  --- fall-backs (key | span context | reconstructed line) ---")
        shown = 0
        for key in sorted(by_key):
            if key in index:
                continue
            # Show the most caption-looking occurrence (longest context).
            det = max(by_key[key], key=lambda d: len(d.get("context", "")))
            ctx = (det.get("context") or "").strip()
            line = _find_line(lines.get(det.get("page_index", -1), []), ctx)
            passes_line = _is_caption_definition(line, det["label"])
            flag = "  <-- full LINE would pass" if passes_line else ""
            print(f"    {key}")
            print(f"        span ctx : {ctx[:90]!r}")
            print(f"        line     : {line[:90]!r}{flag}")
            shown += 1
            if shown >= 25:
                print(f"    … (+{fellback - shown} more)")
                break
    return anchored, fellback


def main(argv: list[str]) -> int:
    pdfs = [Path(a) for a in argv]
    tot_anchored = tot_fellback = 0
    for pdf in pdfs:
        if not pdf.exists():
            print(f"!! missing: {pdf}")
            continue
        a, f = diagnose(pdf)
        tot_anchored += a
        tot_fellback += f
    print("\n==================  TOTAL  ==================")
    print(f"  anchored at DEFINITION : {tot_anchored}")
    print(f"  FELL BACK to citation  : {tot_fellback}")
    denom = tot_anchored + tot_fellback
    if denom:
        print(f"  definition rate        : {100 * tot_anchored / denom:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
