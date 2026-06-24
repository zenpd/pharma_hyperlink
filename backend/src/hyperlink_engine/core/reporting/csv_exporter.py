"""Layer 6 — CSV exporter for validation reports.

One row per link. Columns are stable across phases; new columns get
appended, never re-ordered, so downstream consumers (dashboard, BI tools)
don't break.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger
from hyperlink_engine.models import LinkRecord, LinkStatus, ValidationReport

_log = get_logger("reporting.csv")


CSV_COLUMNS = (
    "source_doc",
    "link_text",
    "link_location",
    "target_doc",
    "target_anchor",
    "status",
    "confidence",
    "error_msg",
    # Traceability columns (Phase 2 extended test set)
    "detected_by",
    "ner_pattern",
    "llm_called",
    "llm_confidence_before",
    "llm_confidence_after",
)


_STATUS_SORT_KEY = {
    LinkStatus.BROKEN: 0,
    LinkStatus.SUSPICIOUS: 1,
    LinkStatus.UNVERIFIED: 2,
    LinkStatus.OK: 3,
}


def _row(record: LinkRecord) -> dict[str, str]:
    return {
        "source_doc": record.source_doc,
        "link_text": record.link_text,
        "link_location": record.link_location_descriptor,
        "target_doc": record.target_doc or "",
        "target_anchor": record.target_anchor or "",
        "status": record.status.value,
        "confidence": f"{record.confidence:.3f}",
        "error_msg": record.error_msg or "",
        # Traceability columns
        "detected_by": record.detected_by or "",
        "ner_pattern": record.ner_pattern or "",
        "llm_called": "yes" if record.llm_called else "no",
        "llm_confidence_before": f"{record.llm_confidence_before:.3f}" if record.llm_confidence_before is not None else "",
        "llm_confidence_after": f"{record.llm_confidence_after:.3f}" if record.llm_confidence_after is not None else "",
    }


def write_link_records(records: Iterable[LinkRecord], path: Path) -> Path:
    """Write LinkRecord rows to a CSV sorted by severity (broken first)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(records, key=lambda r: (_STATUS_SORT_KEY.get(r.status, 4), r.source_doc))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in rows:
            writer.writerow(_row(record))
    _log.info("csv_report_written", path=str(path), rows=len(rows))
    return path


def write_validation_report(report: ValidationReport, path: Path) -> Path:
    """Convenience: dump a single document's ValidationReport to CSV."""
    return write_link_records(report.links, path)


def write_dossier_report(reports: Iterable[ValidationReport], path: Path) -> Path:
    """Aggregate a list of ValidationReports into a single CSV."""
    all_links: list[LinkRecord] = []
    for report in reports:
        all_links.extend(report.links)
    return write_link_records(all_links, path)
