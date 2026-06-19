"""Unit tests for reporting/csv_exporter.py."""

from __future__ import annotations

import csv
from pathlib import Path

from hyperlink_engine.core.reporting.csv_exporter import (
    CSV_COLUMNS,
    write_dossier_report,
    write_link_records,
    write_validation_report,
)
from hyperlink_engine.models import LinkRecord, LinkStatus, ValidationReport


def _record(source: str, status: LinkStatus) -> LinkRecord:
    return LinkRecord(
        source_doc=source,
        link_text="Section 2.5.3",
        link_location_descriptor="p1.r2:c0-13",
        target_doc="target.docx",
        target_anchor="section_2_5_3",
        status=status,
        confidence=0.95,
        error_msg=None if status == LinkStatus.OK else "n/a",
    )


def test_columns_are_stable() -> None:
    assert CSV_COLUMNS == (
        "source_doc",
        "link_text",
        "link_location",
        "target_doc",
        "target_anchor",
        "status",
        "confidence",
        "error_msg",
        "detected_by",
        "ner_pattern",
        "llm_called",
        "llm_confidence_before",
        "llm_confidence_after",
    )


def test_write_link_records_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "report.csv"
    write_link_records(
        [_record("a.docx", LinkStatus.OK), _record("b.docx", LinkStatus.BROKEN)],
        out,
    )
    assert out.exists()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 2


def test_broken_links_sorted_first(tmp_path: Path) -> None:
    out = tmp_path / "report.csv"
    write_link_records(
        [
            _record("a.docx", LinkStatus.OK),
            _record("b.docx", LinkStatus.BROKEN),
            _record("c.docx", LinkStatus.SUSPICIOUS),
        ],
        out,
    )
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    statuses = [r["status"] for r in rows]
    assert statuses[0] == "broken"
    assert statuses[1] == "suspicious"
    assert statuses[2] == "ok"


def test_write_validation_report(tmp_path: Path) -> None:
    report = ValidationReport(
        document="a.docx",
        document_hash_before="x" * 64,
        links=[_record("a.docx", LinkStatus.OK)],
    )
    out = tmp_path / "report.csv"
    write_validation_report(report, out)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 1


def test_write_dossier_report_aggregates(tmp_path: Path) -> None:
    reports = [
        ValidationReport(
            document="a.docx",
            document_hash_before="x" * 64,
            links=[_record("a.docx", LinkStatus.OK)],
        ),
        ValidationReport(
            document="b.docx",
            document_hash_before="y" * 64,
            links=[
                _record("b.docx", LinkStatus.OK),
                _record("b.docx", LinkStatus.BROKEN),
            ],
        ),
    ]
    out = tmp_path / "dossier.csv"
    write_dossier_report(reports, out)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == 3
