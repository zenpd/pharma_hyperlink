"""Layer 4: Hyperlink injection - Word, PDF, eCTD backbone XML."""

from hyperlink_engine.core.injection.docx_linker import DocxLinker
from hyperlink_engine.models import HyperlinkSpec

__all__ = ["DocxLinker", "HyperlinkSpec"]
