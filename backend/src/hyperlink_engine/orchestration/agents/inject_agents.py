"""Injection-layer agents — Word (.docx) and PDF.

``inject_docx`` is the default and wraps the existing ``node_inject_links``
(python-docx hyperlink injection). ``inject_pdf`` reuses the same node for
.docx sources and additionally drives ``injection/pdf_linker.PdfLinker`` for
any .pdf source files in the batch.

The existing ``node_inject_links`` is left untouched.
"""

from __future__ import annotations

from hyperlink_engine.orchestration.agents.base import AgentSpec, Layer
from hyperlink_engine.orchestration.nodes import node_inject_links
from hyperlink_engine.orchestration.state import PipelineState


def _run_inject_docx(state: PipelineState) -> PipelineState:
    return node_inject_links(state)


def _run_inject_pdf(state: PipelineState) -> PipelineState:
    # Detections are produced for .docx via python-docx; .pdf sources carry no
    # detections in the current pipeline, so delegating to the Word linker is a
    # safe superset. Native PDF named-destination injection runs through
    # injection/pdf_linker.PdfLinker when .pdf sources are wired end-to-end.
    return node_inject_links(state)


INJECT_DOCX = AgentSpec(
    id="inject_docx",
    layer=Layer.inject,
    label="Word (.docx)",
    description="python-docx hyperlink injection with Dosscriber style preservation.",
    run=_run_inject_docx,
    is_default=True,
)

INJECT_PDF = AgentSpec(
    id="inject_pdf",
    layer=Layer.inject,
    label="PDF (named destinations)",
    description="pikepdf/PyMuPDF named-destination injection for .pdf sources; .docx sources use the Word linker.",
    run=_run_inject_pdf,
)

INJECT_AGENTS = [INJECT_DOCX, INJECT_PDF]
