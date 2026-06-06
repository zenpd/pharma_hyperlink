"""Shared Pydantic models used as inter-layer contracts.

These types flow between ingestion, parsing, detection, injection, validation,
and reporting. Keeping them in one place prevents circular imports and makes
the contracts easy to inspect.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────
# Location anchors — where in a document something lives
# ─────────────────────────────────────────────────────────────────────────


class RunLocation(BaseModel):
    """A position inside a .docx paragraph run.

    Used to point the link injector at the exact span to wrap.
    """

    paragraph_index: int = Field(ge=0)
    run_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)

    @property
    def length(self) -> int:
        return self.char_end - self.char_start


class PdfLocation(BaseModel):
    """A position inside a PDF page (bbox in PDF user-space coords)."""

    page_index: int = Field(ge=0)
    x0: float
    y0: float
    x1: float
    y1: float


Location = RunLocation | PdfLocation


# ─────────────────────────────────────────────────────────────────────────
# Detection — Layer 3 outputs
# ─────────────────────────────────────────────────────────────────────────


class Reference(BaseModel):
    """A detected reference candidate produced by Layer 3."""

    pattern_id: str
    text: str
    location: Location
    confidence: float = Field(ge=0.0, le=1.0)
    candidate_targets: list[str] = Field(default_factory=list)
    source_layer: Literal["regex", "ner", "llm", "merged"] = "regex"
    metadata: dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────
# Injection — Layer 4 inputs
# ─────────────────────────────────────────────────────────────────────────


class LinkKind(str, Enum):
    EXTERNAL_URL = "external_url"
    INTERNAL_BOOKMARK = "internal_bookmark"
    CROSS_DOC = "cross_doc"
    CROSS_MODULE = "cross_module"


class HyperlinkSpec(BaseModel):
    """Instruction to inject a hyperlink at a specific location."""

    location: RunLocation
    kind: LinkKind
    target: str
    display_text: str | None = None
    source_reference: Reference | None = None


# ─────────────────────────────────────────────────────────────────────────
# Validation — Layer 5 outputs
# ─────────────────────────────────────────────────────────────────────────


class LinkStatus(str, Enum):
    OK = "ok"
    BROKEN = "broken"
    SUSPICIOUS = "suspicious"
    UNVERIFIED = "unverified"


class AnomalySeverity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class AnomalyKind(str, Enum):
    BLUE_TEXT_NO_LINK = "blue_text_no_link"
    ORPHANED_REFERENCE = "orphaned_reference"
    CIRCULAR_REFERENCE = "circular_reference"
    DEPRECATED_STUDY_ID = "deprecated_study_id"
    SUSPICIOUS_TARGET = "suspicious_target"
    STYLE_MUTATION = "style_mutation"


class HaRegion(str, Enum):
    """Health Authority region codes used by the HA rule engine."""

    US = "us"   # FDA
    EU = "eu"   # EMA
    JP = "jp"   # PMDA
    CA = "ca"   # Health Canada


class HaViolation(BaseModel):
    """Output of one HA rule evaluation."""

    rule_id: str
    region: HaRegion
    severity: AnomalySeverity
    description: str
    target: str  # leaf_id / file path / "dossier" — context for the violation
    detail: str | None = None  # specific failure detail (e.g. measured value)


class Anomaly(BaseModel):
    """A single detected anomaly."""

    kind: AnomalyKind
    severity: AnomalySeverity
    document: str
    location: Location | None = None
    text: str
    suggested_fix: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class LinkRecord(BaseModel):
    """One row in the validation CSV report."""

    source_doc: str
    link_text: str
    link_location_descriptor: str  # e.g., "p12.r3:c45-67"
    target_doc: str | None = None
    target_anchor: str | None = None
    status: LinkStatus
    confidence: float = Field(ge=0.0, le=1.0)
    error_msg: str | None = None
    # Traceability fields (optional, for Phase 2 extended test set)
    detected_by: Literal["regex", "ner", "llm", "merged"] | None = None
    ner_pattern: str | None = None  # NER pattern name if applicable
    llm_called: bool = False
    llm_confidence_before: float | None = None
    llm_confidence_after: float | None = None


class ValidationReport(BaseModel):
    """Per-document validation result."""

    document: str
    document_hash_before: str
    document_hash_after: str | None = None
    links: list[LinkRecord] = Field(default_factory=list)
    anomalies: list[Anomaly] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())

    @property
    def broken_link_count(self) -> int:
        return sum(1 for link in self.links if link.status == LinkStatus.BROKEN)

    @property
    def total_link_count(self) -> int:
        return len(self.links)

    @property
    def broken_link_rate(self) -> float:
        if not self.links:
            return 0.0
        return self.broken_link_count / len(self.links)


# ─────────────────────────────────────────────────────────────────────────
# Audit — cross-cutting
# ─────────────────────────────────────────────────────────────────────────


class AuditEvent(BaseModel):
    """One immutable line in audit.jsonl."""

    timestamp: datetime = Field(default_factory=lambda: datetime.utcnow())
    actor: str
    action: str
    document: str | None = None
    doc_hash_before: str | None = None
    doc_hash_after: str | None = None
    links_added: int = 0
    details: dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────
# Document wrapper — what loaders return
# ─────────────────────────────────────────────────────────────────────────


class DocumentProvenance(BaseModel):
    """Where a document came from and what its identity is at ingest time."""

    source_path: Path
    sha256: str
    ingested_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    file_size_bytes: int = Field(ge=0)


# ─────────────────────────────────────────────────────────────────────────
# Layer 1 / Layer 2 — parsed document models
# ─────────────────────────────────────────────────────────────────────────


class RunStyle(BaseModel):
    """Run-level character formatting captured at parse time."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    font_name: str | None = None
    font_size_pt: float | None = None
    color_rgb: str | None = None  # uppercase hex without '#', e.g. "0000FF"
    style_name: str | None = None  # named character style if any
    is_hyperlink: bool = False


class DocxRun(BaseModel):
    """A single run inside a paragraph — the smallest styled span."""

    run_index: int = Field(ge=0)
    text: str
    style: RunStyle = Field(default_factory=RunStyle)
    char_offset_in_paragraph: int = Field(ge=0)


class DocxParagraph(BaseModel):
    """A paragraph with its runs and an optional table-cell coordinate."""

    paragraph_index: int = Field(ge=0)
    style_name: str | None = None
    text: str
    runs: list[DocxRun] = Field(default_factory=list)
    in_table: bool = False
    table_coords: tuple[int, int, int] | None = None  # (table_idx, row, col)

    @property
    def char_length(self) -> int:
        return len(self.text)


class DocxDocument(BaseModel):
    """A parsed Word document — Layer 2 output for .docx files."""

    provenance: DocumentProvenance
    title: str | None = None
    author: str | None = None
    paragraph_count: int = Field(ge=0)
    paragraphs: list[DocxParagraph] = Field(default_factory=list)
    existing_hyperlinks: list[str] = Field(default_factory=list)

    @property
    def total_runs(self) -> int:
        return sum(len(p.runs) for p in self.paragraphs)

    @property
    def total_chars(self) -> int:
        return sum(p.char_length for p in self.paragraphs)


class PdfSpan(BaseModel):
    """A horizontally-contiguous styled run of text on a PDF page."""

    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    font_name: str | None = None
    font_size_pt: float | None = None
    color_rgb: str | None = None


class PdfBlock(BaseModel):
    """A text block returned by PyMuPDF (paragraph-ish unit)."""

    block_index: int = Field(ge=0)
    bbox: tuple[float, float, float, float]
    spans: list[PdfSpan] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)


class PdfLinkAnnotation(BaseModel):
    """An existing link annotation discovered in the source PDF."""

    page_index: int = Field(ge=0)
    bbox: tuple[float, float, float, float]
    uri: str | None = None  # external URI, if any
    target_page: int | None = None  # internal page jump
    named_dest: str | None = None  # named destination, if any


class PdfPage(BaseModel):
    """One page of a parsed PDF."""

    page_index: int = Field(ge=0)
    width: float
    height: float
    blocks: list[PdfBlock] = Field(default_factory=list)


class PdfDocument(BaseModel):
    """A parsed PDF document — Layer 2 output for .pdf files."""

    provenance: DocumentProvenance
    page_count: int = Field(ge=0)
    pages: list[PdfPage] = Field(default_factory=list)
    bookmarks: list[tuple[int, str, int]] = Field(default_factory=list)  # (level, title, page)
    existing_links: list[PdfLinkAnnotation] = Field(default_factory=list)
    named_destinations: dict[str, int] = Field(default_factory=dict)  # name -> page index
    is_pdf_a: bool = False


# ─────────────────────────────────────────────────────────────────────────
# eCTD backbone (Layer 1)
# ─────────────────────────────────────────────────────────────────────────


class LeafOperation(str, Enum):
    NEW = "new"
    REPLACE = "replace"
    APPEND = "append"
    DELETE = "delete"


class BackboneLeaf(BaseModel):
    """One eCTD leaf entry as it appears in index.xml."""

    leaf_id: str
    relative_path: Path
    module: str  # e.g. "m2.5", "m5.3.1"
    operation: LeafOperation = LeafOperation.NEW
    checksum: str | None = None  # MD5 per ICH spec
    checksum_type: str = "md5"
    title: str | None = None
    # Sequence-history fields populated by the regional + diff loaders.
    region_source: str | None = None  # set when the leaf came from a regional file
    previous_checksum: str | None = None  # checksum from prior sequence, if known

    @property
    def is_modified(self) -> bool:
        """A leaf is considered modified iff its operation is not NEW.

        REPLACE / APPEND / DELETE all imply the leaf differs from its prior
        sequence — useful for downstream change-set reporting.
        """
        return self.operation != LeafOperation.NEW


class LeafIntegrityStatus(str, Enum):
    """Outcome of comparing a leaf's declared checksum to the on-disk file."""

    OK = "ok"
    MISSING_FILE = "missing_file"
    NO_CHECKSUM = "no_checksum"
    MISMATCH = "mismatch"


class LeafIntegrityReport(BaseModel):
    """Result of verifying a single leaf's declared checksum against the file."""

    leaf_id: str
    relative_path: Path
    status: LeafIntegrityStatus
    expected: str | None = None
    actual: str | None = None
    error_msg: str | None = None


class BackboneDiff(BaseModel):
    """Set-difference between two backbone snapshots (typically prior vs current sequence)."""

    added_leaf_ids: list[str] = Field(default_factory=list)
    removed_leaf_ids: list[str] = Field(default_factory=list)
    modified_leaf_ids: list[str] = Field(default_factory=list)
    unchanged_leaf_ids: list[str] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.added_leaf_ids or self.removed_leaf_ids or self.modified_leaf_ids)


class BackboneSnapshot(BaseModel):
    """A read-only view of the eCTD backbone at ingest time."""

    provenance: DocumentProvenance
    schema_version: str  # "v3.2" | "v4.0" | other
    region: str | None = None  # "us" | "eu" | "jp" | "ca" | etc.
    sequence_number: str | None = None  # eCTD sequence, e.g. "0001"
    leaves: list[BackboneLeaf] = Field(default_factory=list)
    regional_sources: list[Path] = Field(default_factory=list)  # *-regional.xml paths merged in

    @property
    def leaf_count(self) -> int:
        return len(self.leaves)

    def leaves_by_module(self, module_prefix: str) -> list[BackboneLeaf]:
        """All leaves whose module starts with the given prefix (e.g. 'm5.3')."""
        return [leaf for leaf in self.leaves if leaf.module.startswith(module_prefix)]

    def leaf_by_id(self, leaf_id: str) -> BackboneLeaf | None:
        for leaf in self.leaves:
            if leaf.leaf_id == leaf_id:
                return leaf
        return None

    @property
    def modified_leaves(self) -> list[BackboneLeaf]:
        """Leaves whose operation marks them as changed in this sequence."""
        return [leaf for leaf in self.leaves if leaf.is_modified]


class CrossModuleLink(BaseModel):
    """A resolved cross-module link record (Phase 2 W6.1 output).

    Carries both the eCTD-level relationship (leaf → leaf) and the
    document-level URI (relative path + optional anchor) used by the
    injection layer.
    """

    source_leaf_id: str
    target_leaf_id: str
    source_module: str
    target_module: str
    relative_uri: str  # e.g. "../m5/5-3-1-bio-stud-rep/study-001.docx#sec_5_3_1"
    anchor: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    rationale: str | None = None  # human-readable trace for the audit log

    @property
    def is_same_module(self) -> bool:
        """True if the source and target share the same top-level module."""
        return self.source_module.split(".")[0] == self.target_module.split(".")[0]


# ─────────────────────────────────────────────────────────────────────────
# Dossplorer (mock in Phase 1, live in Phase 3)
# ─────────────────────────────────────────────────────────────────────────


class DossierMetadata(BaseModel):
    """Metadata Dossplorer holds for a dossier the engine is processing."""

    dossier_id: str
    sponsor: str
    submission_type: Literal["IND", "NDA", "BLA", "MAA", "JNDA", "ANDA", "OTHER"]
    region: Literal["US", "EU", "JP", "CA", "INT"] = "US"
    sequence_number: str  # eCTD sequence ID, e.g. "0001"
    study_ids: list[str] = Field(default_factory=list)
    submitted_at: datetime | None = None
    status: Literal["draft", "in_review", "submitted", "approved", "withdrawn"] = "draft"
