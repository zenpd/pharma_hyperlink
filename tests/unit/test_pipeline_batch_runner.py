"""Unit tests for pipeline/batch_runner.py (W7.1 + W7.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from hyperlink_engine.pipeline.batch_runner import (
    BatchRunReport,
    DossierBatchDescriptor,
    _output_paths_for,
    run_batch,
)
from hyperlink_engine.pipeline.cache import ExtractorConfig
from hyperlink_engine.pipeline.celery_app import reset_app


def _make_docx_with_refs(path: Path, text: str) -> None:
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))


@pytest.fixture(autouse=True)
def _reset_celery_state() -> None:
    reset_app()
    yield
    reset_app()


@pytest.fixture
def small_batch(tmp_path: Path) -> DossierBatchDescriptor:
    source_root = tmp_path / "src"
    source_root.mkdir()
    for i in range(3):
        _make_docx_with_refs(source_root / f"doc-{i}.docx", f"See Section 2.{i}.1")
    return DossierBatchDescriptor(
        sources=sorted(source_root.glob("*.docx")),
        output_root=tmp_path / "out",
        report_root=tmp_path / "reports",
        extractor_config=ExtractorConfig.regex_only(),
    )


# ── DossierBatchDescriptor ─────────────────────────────────────────────


def test_descriptor_from_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_docx_with_refs(src / "a.docx", "x")
    _make_docx_with_refs(src / "b.docx", "x")
    desc = DossierBatchDescriptor.from_directory(
        src,
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
    )
    assert desc.doc_count() == 2


def test_descriptor_carries_extractor_config(tmp_path: Path) -> None:
    desc = DossierBatchDescriptor(
        sources=[],
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
        extractor_config=ExtractorConfig.regex_only(),
    )
    assert desc.extractor_config.with_ner is False


# ── Output path resolution ─────────────────────────────────────────────


def test_output_paths_for_uses_relative_layout(tmp_path: Path) -> None:
    desc = DossierBatchDescriptor(
        sources=[],
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
    )
    # Deep enough path that .parents[2] is a real ancestor.
    source = tmp_path / "a" / "b" / "c" / "d.docx"
    output, report = _output_paths_for(source, desc)
    assert output.suffix == ".docx"
    assert output.name == "d.linked.docx"
    assert report.suffix == ".csv"


def test_output_paths_for_shallow_path_falls_back_to_name(tmp_path: Path) -> None:
    desc = DossierBatchDescriptor(
        sources=[], output_root=tmp_path / "out", report_root=tmp_path / "rep"
    )
    source = tmp_path / "shallow.docx"
    output, report = _output_paths_for(source, desc)
    assert output.name == "shallow.linked.docx"


# ── run_batch — sync mode ──────────────────────────────────────────────


def test_run_batch_sync_processes_every_doc(small_batch: DossierBatchDescriptor) -> None:
    report = run_batch(small_batch, mode="sync")
    assert isinstance(report, BatchRunReport)
    assert report.documents_processed == 3
    assert not report.failures
    assert report.aggregate_csv is not None
    assert report.aggregate_csv.exists()


def test_run_batch_sync_aggregates_csv(small_batch: DossierBatchDescriptor) -> None:
    report = run_batch(small_batch, mode="sync")
    text = report.aggregate_csv.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "source_doc" in text
    # Each doc emits at least one section-ref link.
    assert text.count("\n") >= 1 + report.total_links


def test_run_batch_sync_records_per_doc_reports(small_batch: DossierBatchDescriptor) -> None:
    report = run_batch(small_batch, mode="sync")
    for result in report.results:
        assert result.report_path.exists()
        assert result.output_path.exists()


# ── run_batch — threaded mode ──────────────────────────────────────────


def test_run_batch_threaded_processes_every_doc(small_batch: DossierBatchDescriptor) -> None:
    report = run_batch(small_batch, mode="threaded", workers=2)
    assert report.documents_processed == 3
    assert not report.failures


def test_run_batch_threaded_speeds_up_smoke(small_batch: DossierBatchDescriptor) -> None:
    """Smoke test: threaded run completes without error with 2 workers."""
    report = run_batch(small_batch, mode="threaded", workers=2)
    assert report.documents_processed == 3


# ── run_batch — celery mode (eager) ────────────────────────────────────


def test_run_batch_celery_eager_mode(small_batch: DossierBatchDescriptor) -> None:
    report = run_batch(small_batch, mode="celery")
    assert report.documents_processed == 3
    assert not report.failures


# ── Failure tolerance ──────────────────────────────────────────────────


def test_run_batch_continues_past_broken_docs(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    _make_docx_with_refs(src / "good.docx", "Section 2.5.3")
    # A non-DOCX file with .docx extension → ingestion succeeds but
    # detect_references will fail (python-docx can't open non-zip text).
    (src / "broken.docx").write_text("not a real docx", encoding="utf-8")

    desc = DossierBatchDescriptor(
        sources=sorted(src.glob("*.docx")),
        output_root=tmp_path / "out",
        report_root=tmp_path / "rep",
        extractor_config=ExtractorConfig.regex_only(),
    )
    report = run_batch(desc, mode="sync")
    assert report.documents_processed == 1  # only 'good.docx' succeeds
    assert len(report.failures) == 1
    failure_path, reason = report.failures[0]
    assert failure_path.name == "broken.docx"
    assert reason


# ── BatchRunReport helpers ────────────────────────────────────────────


def test_batch_report_metrics(small_batch: DossierBatchDescriptor) -> None:
    report = run_batch(small_batch, mode="sync")
    assert report.total_links > 0
    assert report.broken_rate == 0.0  # bookmarks are auto-declared
    assert report.docs_per_hour > 0


def test_batch_report_zero_metrics_when_empty() -> None:
    report = BatchRunReport()
    assert report.documents_processed == 0
    assert report.total_links == 0
    assert report.broken_rate == 0.0
    assert report.docs_per_hour == 0.0


def test_run_batch_unknown_mode_raises(small_batch: DossierBatchDescriptor) -> None:
    with pytest.raises(ValueError):
        run_batch(small_batch, mode="not_a_mode")  # type: ignore[arg-type]
