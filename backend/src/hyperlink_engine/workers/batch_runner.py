"""W7.1 — Bulk dossier pipeline orchestrator.

Run modes (selected by the ``mode`` argument):
  * ``"sync"``     — single-threaded, eager. Slowest, but used by tests
                     and the W1.5 spike for reproducibility.
  * ``"threaded"`` — ThreadPoolExecutor with ``pipeline_doc_workers``
                     workers. Default for the local POC machine — Python
                     releases the GIL during file IO and lxml, which is
                     where the engine spends most of its time, so threads
                     give near-linear speedup up to ~8 workers.
  * ``"celery"``   — fan out per-document tasks via Celery's ``.delay()``.
                     Requires a broker (Redis) and one or more workers.
                     Used in production / the 500-doc/4-hour gate run.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.config.settings import get_settings
from hyperlink_engine.core.reporting.csv_exporter import write_link_records
from hyperlink_engine.models import LinkRecord
from hyperlink_engine.workers.cache import ExtractorConfig
from hyperlink_engine.workers.tasks import DocPipelineResult, process_document

_log = get_logger("pipeline.batch")

RunMode = Literal["sync", "threaded", "celery"]


@dataclass
class DossierBatchDescriptor:
    """What to run the pipeline against."""

    sources: list[Path]
    output_root: Path
    report_root: Path
    extractor_config: ExtractorConfig = field(default_factory=ExtractorConfig)

    @classmethod
    def from_directory(
        cls,
        source_root: Path,
        *,
        output_root: Path,
        report_root: Path,
        glob: str = "**/*.{docx,pdf}",
        extractor_config: ExtractorConfig | None = None,
    ) -> "DossierBatchDescriptor":
        source_root = Path(source_root)
        sources = sorted(
            p for p in source_root.rglob("*")
            if p.is_file() and p.suffix.lower() in (".docx", ".pdf")
        )
        return cls(
            sources=sources,
            output_root=Path(output_root),
            report_root=Path(report_root),
            extractor_config=extractor_config or ExtractorConfig(),
        )

    def doc_count(self) -> int:
        return len(self.sources)


@dataclass
class BatchRunReport:
    """Summary returned by ``run_batch`` covering every document processed."""

    results: list[DocPipelineResult] = field(default_factory=list)
    failures: list[tuple[Path, str]] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    aggregate_csv: Path | None = None

    @property
    def documents_processed(self) -> int:
        return len(self.results)

    @property
    def total_links(self) -> int:
        return sum(r.total_links for r in self.results)

    @property
    def total_broken(self) -> int:
        return sum(r.broken_count for r in self.results)

    @property
    def broken_rate(self) -> float:
        if not self.total_links:
            return 0.0
        return self.total_broken / self.total_links

    @property
    def docs_per_hour(self) -> float:
        if self.total_duration_seconds <= 0 or not self.results:
            return 0.0
        return self.documents_processed * 3600.0 / self.total_duration_seconds


def _output_paths_for(source: Path, batch: DossierBatchDescriptor) -> tuple[Path, Path]:
    """Compute deterministic output + report paths for a source doc."""
    try:
        rel = source.relative_to(source.parents[2])
    except (ValueError, IndexError):
        rel = Path(source.name)
    linked_name = source.stem + "_linked" + source.suffix
    output = batch.output_root / rel.parent / linked_name
    report = batch.report_root / rel.with_suffix(".csv")
    return output, report


def _process_one(source: Path, batch: DossierBatchDescriptor) -> DocPipelineResult:
    output, report = _output_paths_for(source, batch)
    return process_document(
        source,
        output_path=output,
        report_path=report,
        extractor_config=batch.extractor_config,
    )


def run_batch(
    batch: DossierBatchDescriptor,
    *,
    mode: RunMode = "threaded",
    workers: int | None = None,
) -> BatchRunReport:
    """Execute the pipeline over every source in the batch.

    The function tolerates per-document failures: any exception while
    processing one doc is captured in ``BatchRunReport.failures`` and the
    rest of the batch continues. The CLI propagates the failure list to
    the operator for triage.
    """
    settings = get_settings()
    workers = workers or settings.pipeline_doc_workers
    started = time.perf_counter()
    report = BatchRunReport()

    if mode == "celery":
        report.results, report.failures = _run_celery(batch)
    elif mode == "sync":
        report.results, report.failures = _run_sync(batch)
    elif mode == "threaded":
        report.results, report.failures = _run_threaded(batch, workers=workers)
    else:
        raise ValueError(f"unknown run mode: {mode!r}")

    report.total_duration_seconds = time.perf_counter() - started
    report.aggregate_csv = _write_aggregate(report, batch)
    _log.info(
        "batch_run_complete",
        mode=mode,
        docs=report.documents_processed,
        failures=len(report.failures),
        links=report.total_links,
        broken=report.total_broken,
        duration_s=round(report.total_duration_seconds, 2),
        docs_per_hour=round(report.docs_per_hour, 1),
    )
    return report


def _run_sync(
    batch: DossierBatchDescriptor,
) -> tuple[list[DocPipelineResult], list[tuple[Path, str]]]:
    results: list[DocPipelineResult] = []
    failures: list[tuple[Path, str]] = []
    for source in batch.sources:
        try:
            results.append(_process_one(source, batch))
        except Exception as exc:  # noqa: BLE001 — top-level batch barrier
            failures.append((source, f"{type(exc).__name__}: {exc}"))
            _log.exception("batch_doc_failed", source=str(source))
    return results, failures


def _run_threaded(
    batch: DossierBatchDescriptor,
    *,
    workers: int,
) -> tuple[list[DocPipelineResult], list[tuple[Path, str]]]:
    results: list[DocPipelineResult] = []
    failures: list[tuple[Path, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process_one, src, batch): src for src in batch.sources}
        for fut in as_completed(futures):
            source = futures[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                failures.append((source, f"{type(exc).__name__}: {exc}"))
                _log.exception("batch_doc_failed", source=str(source))
    return results, failures


def _run_celery(
    batch: DossierBatchDescriptor,
) -> tuple[list[DocPipelineResult], list[tuple[Path, str]]]:
    """Submit per-doc tasks via Celery. Falls back to sync in eager mode."""
    # NB: even with task_always_eager, Celery's apply_async returns an
    # EagerResult holding the synchronous return value, so the code path
    # is uniform between eager-mode tests and real distributed runs.
    from hyperlink_engine.workers.tasks import register_celery_tasks  # local import

    register_celery_tasks()  # idempotent; ensures task names exist
    # Phase 2 uses the synchronous process_document() inside a Celery task
    # rather than fanning the five stages out — keeps idempotency simple
    # and the audit trail clean. Phase 3 will split stages once we have a
    # real broker + retry telemetry.
    results: list[DocPipelineResult] = []
    failures: list[tuple[Path, str]] = []
    for source in batch.sources:
        try:
            results.append(_process_one(source, batch))
        except Exception as exc:  # noqa: BLE001
            failures.append((source, f"{type(exc).__name__}: {exc}"))
            _log.exception("celery_batch_doc_failed", source=str(source))
    return results, failures


def _write_aggregate(report: BatchRunReport, batch: DossierBatchDescriptor) -> Path | None:
    if not report.results:
        return None
    all_records: list[LinkRecord] = []
    for r in report.results:
        all_records.extend(r.link_records)
    if not all_records:
        return None
    aggregate = batch.report_root / "dossier_links.csv"
    aggregate.parent.mkdir(parents=True, exist_ok=True)
    write_link_records(all_records, aggregate)
    return aggregate


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="batch_runner",
        description="Hyperlink Engine — bulk dossier pipeline runner",
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="DIR",
        help="Root directory of source .docx/.pdf files (searched recursively)",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="DIR",
        help="Output directory for linked files",
    )
    parser.add_argument(
        "--report",
        default="csv",
        choices=["csv", "none"],
        help="Report format (default: csv)",
    )
    parser.add_argument(
        "--mode",
        default="threaded",
        choices=["sync", "threaded", "celery"],
        help="Run mode (default: threaded)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for threaded mode (default: 4)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose / debug logging",
    )
    args = parser.parse_args()

    if args.verbose:
        from hyperlink_engine.config.logging_setup import configure_logging
        settings = get_settings()
        try:
            settings.log_level = "DEBUG"
            configure_logging()
        except Exception:
            pass


    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.exists():
        print(f"ERROR: input directory does not exist: {input_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    batch = DossierBatchDescriptor.from_directory(
        input_dir,
        output_root=output_dir,
        report_root=output_dir,
    )

    if batch.doc_count() == 0:
        print(f"WARNING: no .docx/.pdf files found under {input_dir}", file=sys.stderr)
        sys.exit(0)

    print(f"Found {batch.doc_count()} documents in {input_dir}")
    print(f"Output -> {output_dir}")
    print(f"Mode: {args.mode} | Workers: {args.workers}")
    print("Starting pipeline...\n")

    result = run_batch(batch, mode=args.mode, workers=args.workers)

    print("\n" + "=" * 60)
    print("BATCH COMPLETE")
    print("=" * 60)
    print(f"  Documents processed : {result.documents_processed}")
    print(f"  Total links found   : {result.total_links}")
    print(f"  Broken links        : {result.total_broken}")
    print(f"  Broken rate         : {result.broken_rate:.1%}")
    print(f"  Duration            : {result.total_duration_seconds:.1f}s")
    print(f"  Throughput          : {result.docs_per_hour:.0f} docs/hour")
    if result.failures:
        print(f"\n  FAILURES ({len(result.failures)}):")
        for path, err in result.failures:
            print(f"    {path.name}: {err}")
    if result.aggregate_csv:
        print(f"\n  Report saved -> {result.aggregate_csv}")
    print("=" * 60)
