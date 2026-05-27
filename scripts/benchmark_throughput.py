"""W7.2 / W7.3 — throughput benchmark + 500-doc / 4-hour gate driver.

Usage::

    poetry run python -m scripts.benchmark_throughput \
        --synthetic data/synthetic \
        --output output/bench \
        --mode threaded \
        --workers 4 \
        --target-docs 500 \
        --target-hours 4

The script runs the W7.1 batch pipeline against the synthetic dossier
(repeated to reach ``--target-docs`` if necessary) and reports:

  * elapsed wall-clock time
  * documents / hour throughput
  * pass/fail against the configured gate
  * per-mode comparison (``--compare`` runs sync, threaded, celery in turn)

Designed to be safe to run repeatedly: every iteration writes into a
timestamped subdirectory under ``--output`` so existing outputs are
preserved for diffing.
"""

from __future__ import annotations

import argparse
import shutil
import time
from datetime import datetime
from pathlib import Path

from hyperlink_engine.config.logging_setup import configure_logging, get_logger
from hyperlink_engine.pipeline.batch_runner import (
    BatchRunReport,
    DossierBatchDescriptor,
    RunMode,
    run_batch,
)
from hyperlink_engine.pipeline.cache import ExtractorConfig

_log = get_logger("scripts.benchmark_throughput")


def _materialize_docs(
    synthetic_root: Path,
    target_docs: int,
    *,
    staging_root: Path,
) -> list[Path]:
    """Copy the synthetic .docx files into ``staging_root`` to reach ``target_docs``.

    The synthetic dossier ships with 20 docs; replicating them produces
    a fair throughput sample for the 500-doc gate without needing a
    massive corpus on disk.
    """
    real_docs = sorted(synthetic_root.rglob("*.docx"))
    if not real_docs:
        raise SystemExit(
            f"no .docx files under {synthetic_root}. Run `make synthetic` first."
        )
    staging_root.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    idx = 0
    while len(staged) < target_docs:
        for src in real_docs:
            if len(staged) >= target_docs:
                break
            dst = staging_root / f"copy-{idx:04d}-{src.name}"
            if not dst.exists():
                shutil.copy2(src, dst)
            staged.append(dst)
            idx += 1
    return staged


def _print_scoreboard(
    mode: RunMode,
    report: BatchRunReport,
    *,
    target_docs: int,
    target_seconds: float,
) -> bool:
    """Pretty-print the benchmark scoreboard. Returns True on pass."""
    passed = (
        report.documents_processed >= target_docs
        and report.total_duration_seconds <= target_seconds
        and not report.failures
    )
    print()
    print(f"--- throughput scoreboard ({mode}) ---")
    print(f"  documents processed     : {report.documents_processed}")
    print(f"  failures                : {len(report.failures)}")
    print(f"  links injected          : {report.total_links}")
    print(f"  broken links            : {report.total_broken}")
    print(f"  broken-link rate        : {report.broken_rate*100:.2f}%")
    print(f"  total elapsed (seconds) : {report.total_duration_seconds:.1f}")
    print(f"  throughput (docs/hour)  : {report.docs_per_hour:.1f}")
    print()
    print(
        f"  gate: >={target_docs} docs in <={target_seconds/3600:.2f} h   "
        f"{'PASS' if passed else 'FAIL'}"
    )
    if report.aggregate_csv:
        print(f"  aggregate report        : {report.aggregate_csv}")
    return passed


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="benchmark-throughput")
    parser.add_argument("--synthetic", type=Path, default=Path("data/synthetic"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/bench") / datetime.utcnow().strftime("%Y%m%dT%H%M%S"),
    )
    parser.add_argument(
        "--mode",
        choices=["sync", "threaded", "celery"],
        default="threaded",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--target-docs", type=int, default=500)
    parser.add_argument("--target-hours", type=float, default=4.0)
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run sync, threaded, and celery in sequence and compare.",
    )
    args = parser.parse_args(argv)

    if not args.synthetic.exists():
        raise SystemExit(
            f"{args.synthetic} does not exist — run `make synthetic` first."
        )

    args.output.mkdir(parents=True, exist_ok=True)
    staging = args.output / "staging"
    staged_docs = _materialize_docs(
        args.synthetic, args.target_docs, staging_root=staging
    )
    descriptor = DossierBatchDescriptor(
        sources=staged_docs,
        output_root=args.output / "linked",
        report_root=args.output / "reports",
        # Regex-only keeps the spaCy load out of the throughput number so
        # we measure the pipeline's true ceiling. Switch to regex_plus_ner
        # for end-to-end realism once W7.2 NER warm-load is in place.
        extractor_config=ExtractorConfig.regex_only(),
    )

    modes_to_run: list[RunMode] = (
        ["sync", "threaded", "celery"] if args.compare else [args.mode]
    )
    target_seconds = args.target_hours * 3600.0

    all_passed = True
    for mode in modes_to_run:
        started = time.perf_counter()
        report = run_batch(descriptor, mode=mode, workers=args.workers)
        elapsed = time.perf_counter() - started
        _log.info(
            "benchmark_mode_complete",
            mode=mode,
            docs=report.documents_processed,
            elapsed_s=round(elapsed, 2),
        )
        passed = _print_scoreboard(
            mode,
            report,
            target_docs=args.target_docs,
            target_seconds=target_seconds,
        )
        all_passed = all_passed and passed

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
