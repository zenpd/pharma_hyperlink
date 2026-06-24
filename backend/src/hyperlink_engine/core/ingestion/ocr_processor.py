"""OCR processing layer — Layer 1.5.

Sits between raw PDF/image ingestion and structured parsing. Triggered when
standard text extraction (PyMuPDF → pdfplumber) yields no text on a page,
indicating a scanned or image-only document.

Supports two engines, selectable via HYPERLINK_OCR_ENGINE:
  "tesseract" (default) — pytesseract + Pillow; requires the system Tesseract binary
  "easyocr"             — EasyOCR; deep-learning, no system binary needed

Configuration keys (see settings.py):
  ocr_enabled               : master switch (default False)
  ocr_engine                : "tesseract" | "easyocr"
  ocr_language              : Tesseract lang code e.g. "eng" / EasyOCR list e.g. "en"
  ocr_dpi                   : render DPI for PDF page → image conversion (default 300)
  ocr_min_confidence        : drop per-word results below this (default 0.5)
  ocr_fallback_on_empty_page: auto-trigger OCR when a page has no extractable text (default True)
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hyperlink_engine.config.logging_setup import get_logger

if TYPE_CHECKING:
    import fitz  # PyMuPDF — type hints only

_log = get_logger("ingestion.ocr")


class OcrNotAvailableError(RuntimeError):
    """Raised when the requested OCR engine is not installed."""


class OcrError(RuntimeError):
    """Raised when OCR processing fails on an individual page."""


@dataclass
class OcrPageResult:
    """OCR output for a single page or image."""

    page_index: int
    text: str
    confidence: float  # 0.0 – 1.0 averaged across detected words
    engine: str  # "tesseract" | "easyocr"
    word_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────


def _fitz_page_to_pil(page: "fitz.Page", dpi: int = 300):  # type: ignore[return]
    """Render a PyMuPDF page to a PIL Image at the given DPI.

    Uses PyMuPDF's built-in pixmap renderer — no poppler dependency.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise OcrNotAvailableError("Pillow is not installed (pip install Pillow)") from exc

    scale = dpi / 72.0  # PDF default unit = 1/72 inch
    import fitz as _fitz  # noqa: PLC0415

    mat = _fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_bytes = pix.tobytes("png")
    return Image.open(io.BytesIO(img_bytes))


def _image_path_to_pil(path: Path):  # type: ignore[return]
    try:
        from PIL import Image
    except ImportError as exc:
        raise OcrNotAvailableError("Pillow is not installed (pip install Pillow)") from exc
    return Image.open(str(path))


# ─────────────────────────────────────────────────────────────────────────
# Tesseract engine
# ─────────────────────────────────────────────────────────────────────────


def _ocr_tesseract(image: Any, language: str, min_confidence: float) -> tuple[str, float, int]:
    """Run pytesseract on a PIL Image; return (text, avg_confidence, word_count)."""
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrNotAvailableError(
            "pytesseract is not installed (pip install pytesseract). "
            "Also ensure Tesseract is installed: https://github.com/UB-Mannheim/tesseract/wiki"
        ) from exc

    try:
        # TSV output gives per-word confidence scores
        tsv_data = pytesseract.image_to_data(
            image,
            lang=language,
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        raise OcrError(f"Tesseract failed: {exc}") from exc

    words: list[str] = []
    confidences: list[float] = []
    for i, conf in enumerate(tsv_data.get("conf", [])):
        try:
            conf_val = float(conf)
        except (TypeError, ValueError):
            continue
        if conf_val < 0:  # Tesseract uses -1 for non-word rows
            continue
        word = tsv_data["text"][i].strip()
        if not word:
            continue
        norm_conf = conf_val / 100.0  # Tesseract reports 0–100
        if norm_conf >= min_confidence:
            words.append(word)
            confidences.append(norm_conf)

    text = " ".join(words)
    avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
    return text, avg_conf, len(words)


# ─────────────────────────────────────────────────────────────────────────
# EasyOCR engine
# ─────────────────────────────────────────────────────────────────────────

# Module-level cache so we only initialise the GPU/CPU model once per process.
_easyocr_readers: dict[str, Any] = {}


def _get_easyocr_reader(language: str) -> Any:
    global _easyocr_readers  # noqa: PLW0603
    if language not in _easyocr_readers:
        try:
            import easyocr
        except ImportError as exc:
            raise OcrNotAvailableError(
                "easyocr is not installed (pip install easyocr)"
            ) from exc
        lang_list = [l.strip() for l in language.split(",")]
        _log.info("easyocr_init", languages=lang_list)
        _easyocr_readers[language] = easyocr.Reader(lang_list, gpu=False)
    return _easyocr_readers[language]


def _ocr_easyocr(image: Any, language: str, min_confidence: float) -> tuple[str, float, int]:
    """Run EasyOCR on a PIL Image; return (text, avg_confidence, word_count)."""
    import numpy as np  # EasyOCR requires numpy arrays

    reader = _get_easyocr_reader(language)
    img_array = np.array(image)
    try:
        results = reader.readtext(img_array, detail=1)
    except Exception as exc:
        raise OcrError(f"EasyOCR failed: {exc}") from exc

    words: list[str] = []
    confidences: list[float] = []
    for (_bbox, text, conf) in results:
        if conf < min_confidence:
            continue
        word = text.strip()
        if word:
            words.append(word)
            confidences.append(float(conf))

    text = " ".join(words)
    avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
    return text, avg_conf, len(words)


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────


def ocr_pdf_page(
    page: "fitz.Page",
    page_index: int,
    *,
    engine: str = "tesseract",
    language: str = "eng",
    dpi: int = 300,
    min_confidence: float = 0.5,
) -> OcrPageResult:
    """OCR a single fitz.Page.

    Renders the page to an image at ``dpi`` dots-per-inch and then runs the
    selected OCR engine. Returns an OcrPageResult; callers should check
    ``result.has_text`` before using ``result.text``.
    """
    image = _fitz_page_to_pil(page, dpi=dpi)
    return _run_ocr(image, page_index=page_index, engine=engine, language=language, min_confidence=min_confidence)


def ocr_image_file(
    path: Path,
    *,
    engine: str = "tesseract",
    language: str = "eng",
    min_confidence: float = 0.5,
) -> OcrPageResult:
    """OCR a standalone image file (PNG, JPEG, TIFF, BMP …).

    Returns an OcrPageResult with page_index=0 (single-page convention for images).
    """
    image = _image_path_to_pil(path)
    return _run_ocr(image, page_index=0, engine=engine, language=language, min_confidence=min_confidence)


def _run_ocr(
    image: Any,
    *,
    page_index: int,
    engine: str,
    language: str,
    min_confidence: float,
) -> OcrPageResult:
    _log.debug("ocr_start", engine=engine, page_index=page_index)
    try:
        if engine == "tesseract":
            text, avg_conf, word_count = _ocr_tesseract(image, language, min_confidence)
        elif engine == "easyocr":
            text, avg_conf, word_count = _ocr_easyocr(image, language, min_confidence)
        else:
            raise OcrError(f"Unknown OCR engine: {engine!r}. Choose 'tesseract' or 'easyocr'.")
    except OcrNotAvailableError:
        raise
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"OCR failed on page {page_index}: {exc}") from exc

    result = OcrPageResult(
        page_index=page_index,
        text=text,
        confidence=avg_conf,
        engine=engine,
        word_count=word_count,
    )
    _log.info(
        "ocr_done",
        engine=engine,
        page_index=page_index,
        word_count=word_count,
        confidence=round(avg_conf, 3),
        has_text=result.has_text,
    )
    return result


def is_ocr_available(engine: str = "tesseract") -> bool:
    """Check whether the requested OCR engine is fully available (no-raise probe).

    For "tesseract" this checks both the Python wrapper *and* the Tesseract system
    binary so callers get an honest answer before attempting real OCR.
    """
    try:
        if engine == "tesseract":
            import shutil

            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            # Probe the binary path — pytesseract lets you override it via
            # pytesseract.pytesseract.tesseract_cmd; honour that if set.
            cmd = getattr(
                getattr(pytesseract, "pytesseract", pytesseract),
                "tesseract_cmd",
                "tesseract",
            )
            return shutil.which(str(cmd)) is not None
        if engine == "easyocr":
            import easyocr  # noqa: F401
            return True
        return False
    except ImportError:
        return False
