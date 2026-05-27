"""Layer 4: Hyperlink injection - Word, PDF, eCTD backbone XML."""

from hyperlink_engine.injection.docx_linker import (
    DocxLinker,
    HyperlinkSpec,
)

__all__ = ["DocxLinker", "HyperlinkSpec"]
