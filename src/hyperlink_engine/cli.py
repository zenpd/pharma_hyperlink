"""Command-line entry point for the hyperlink engine.

Phase 1 ships the W1.5 spike command:

    poetry run hyperlink-engine spike --input <docx> --output <docx>

This loads a Word document, detects references using the regex engine,
injects hyperlinks at every detected location, and writes a "_linked.docx"
copy plus a per-link CSV report.

More commands (batch, validate, dashboard) come online in Phase 2.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from docx import Document

from hyperlink_engine.config.logging_setup import configure_logging, get_logger
from hyperlink_engine.detection.entity_extractor import EntityExtractor, ExtractedReference
from hyperlink_engine.injection.docx_linker import DocxLinker
from hyperlink_engine.models import RunLocation


def _resolve_target(ref: ExtractedReference) -> str:
    """Phase-1 placeholder target resolution.

    Builds a synthetic anchor for internal references and a synthetic URL
    for study IDs. Real resolution against the eCTD backbone graph lands
    in Week 5.
    """
    label = ref.label
    if label in {"SECTION_REF", "TABLE_REF", "FIGURE_REF", "LISTING_REF", "APPENDIX_REF"}:
        num = ref.groups.get("num") or ref.text
        slug = num.replace(".", "_").replace("-", "_")
        return f"{label.lower()}_{slug}"
    if label == "STUDY_ID" and ref.pattern_id == "STUDY_ID_NCT_V1":
        return f"https://clinicaltrials.gov/study/{ref.text}"
    if label == "STUDY_ID":
        slug = ref.text.replace("-", "_")
        return f"study_{slug}"
    if label == "CTD_LEAF":
        mod = ref.groups.get("mod", "?")
        sub = ref.groups.get("sub", "")
        return f"m{mod}" + (f"_{sub.replace('.', '_')}" if sub else "")
    return ref.text  # fallback: not great, flagged later by validation


def _is_external(ref: ExtractedReference) -> bool:
    return ref.pattern_id == "STUDY_ID_NCT_V1"


def _scan_document(path: Path, extractor: EntityExtractor) -> list[tuple[int, int, ExtractedReference]]:
    """Return (paragraph_index, run_index, reference) tuples for every detection."""
    doc = Document(str(path))
    results: list[tuple[int, int, ExtractedReference]] = []
    for p_idx, para in enumerate(doc.paragraphs):
        for r_idx, run in enumerate(para.runs):
            run_text = run.text
            if not run_text.strip():
                continue
            for ref in extractor.extract(run_text):
                results.append((p_idx, r_idx, ref))
    return results


def cmd_spike(args: argparse.Namespace) -> int:
    log = get_logger("cli.spike")
    log.info("spike_start", input=str(args.input), output=str(args.output))

    extractor = EntityExtractor()
    detections = _scan_document(args.input, extractor)
    log.info("spike_detected", count=len(detections))

    linker = DocxLinker(args.input, args.output)
    csv_rows: list[dict[str, str]] = []

    for p_idx, r_idx, ref in detections:
        location = RunLocation(
            paragraph_index=p_idx,
            run_index=r_idx,
            char_start=ref.start,
            char_end=ref.end,
        )
        target = _resolve_target(ref)
        if _is_external(ref):
            linker.add_external_link(location, target)
        else:
            linker.add_internal_link(location, target)

        csv_rows.append(
            {
                "source_doc": str(args.input.name),
                "paragraph": str(p_idx),
                "run": str(r_idx),
                "char_start": str(ref.start),
                "char_end": str(ref.end),
                "text": ref.text,
                "pattern": ref.pattern_id,
                "label": ref.label,
                "confidence": f"{ref.confidence:.2f}",
                "target": target,
                "external": "yes" if _is_external(ref) else "no",
            }
        )

    output_path = linker.save()

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "source_doc",
                    "paragraph",
                    "run",
                    "char_start",
                    "char_end",
                    "text",
                    "pattern",
                    "label",
                    "confidence",
                    "target",
                    "external",
                ],
            )
            writer.writeheader()
            writer.writerows(csv_rows)
        log.info("spike_report_written", report=str(args.report), rows=len(csv_rows))

    print(f"Detected {len(detections)} references")
    print(f"Linked file: {output_path}")
    if args.report:
        print(f"CSV report: {args.report}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Print every reference detected in a document; no injection."""
    extractor = EntityExtractor()
    detections = _scan_document(args.input, extractor)
    for p_idx, r_idx, ref in detections:
        print(
            f"  p{p_idx:>3}.r{r_idx:>2} [{ref.start:>4}-{ref.end:>4}] "
            f"{ref.confidence:.2f}  {ref.pattern_id:<28} {ref.text!r}"
        )
    print(f"\nTotal: {len(detections)} references")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hyperlink-engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    spike = sub.add_parser("spike", help="W1.5 end-to-end spike on a single .docx")
    spike.add_argument("--input", type=Path, required=True, help="Source .docx file")
    spike.add_argument("--output", type=Path, required=True, help="Where to write _linked.docx")
    spike.add_argument("--report", type=Path, default=None, help="Optional CSV report path")
    spike.set_defaults(func=cmd_spike)

    inspect = sub.add_parser("inspect", help="Print all detected references without linking")
    inspect.add_argument("--input", type=Path, required=True)
    inspect.set_defaults(func=cmd_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
