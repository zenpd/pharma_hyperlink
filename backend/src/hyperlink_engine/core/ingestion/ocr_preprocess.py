"""Optional OCR preprocessing — turn scanned / image-only PDFs into *searchable*
PDFs so detection can find references in them.

Design (heavyweight + optional, must never regress the default path):
  * ``ocrmypdf`` is an OPTIONAL dependency and shells out to system Tesseract +
    Ghostscript. If any of those is missing, this module is a no-op.
  * It runs ONLY on PDFs with no extractable text (scanned) AND only when the
    caller opts in (``HYPERLINK_OCR_ENABLED``). Text PDFs are never touched — a
    text-length guard skips them.
  * Best-effort: any failure (missing binary, error) returns the ORIGINAL path,
    so the pipeline degrades to today's behaviour (0 links on that scan) rather
    than crashing.
  * The original file is never mutated — a new searchable copy is written into a
    per-run ``ocr/`` directory, keeping the same filename so downstream
    stem-based routing is unchanged.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from functools import lru_cache
from pathlib import Path

from hyperlink_engine.config.logging_setup import get_logger

_log = get_logger("ingestion.ocr")

# A PDF with fewer than this many extractable characters across all pages is
# treated as scanned / image-only. A genuine text PDF is far above this.
_SCANNED_TEXT_THRESHOLD = 32


def _content_sha(path: Path) -> str:
    """SHA-256 of the file bytes (streamed) — the identity key for the global,
    content-addressed OCR cache. Two uploads with identical bytes map to the same
    key regardless of filename or which run produced them."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_valid_pdf(path: Path) -> bool:
    """Cheap structural check that ``path`` is a readable PDF with >=1 page.

    Used to reject a truncated/corrupt OCR artifact (e.g. from a crash or a
    kill mid-write) before it is cached or served — so the content cache can
    never hand back a broken searchable PDF and self-heals by re-OCR'ing.
    """
    try:
        import fitz

        doc = fitz.open(str(path))
        try:
            return doc.page_count > 0
        finally:
            doc.close()
    except Exception:  # noqa: BLE001 — anything unreadable is treated as invalid
        return False


@lru_cache(maxsize=1)
def available() -> bool:
    """True when ocrmypdf + its system deps (Tesseract, Ghostscript) are usable."""
    try:
        import ocrmypdf  # noqa: F401
    except Exception:
        return False
    has_tesseract = shutil.which("tesseract") is not None
    has_ghostscript = any(
        shutil.which(b) for b in ("gs", "gswin64c", "gswin32c")
    )
    return has_tesseract and bool(has_ghostscript)


def needs_ocr(pdf_path: Path) -> bool:
    """True when a PDF has (near-)zero extractable text — i.e. it is scanned.

    Cheap PyMuPDF text sum with early-exit; a genuine text PDF returns above the
    threshold on the first page or two, so text PDFs are never sent to OCR.
    Any read failure returns False (do not OCR what we can't inspect).
    """
    try:
        import fitz
    except Exception:
        return False
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return False
    try:
        chars = 0
        for i in range(doc.page_count):
            chars += len(doc.load_page(i).get_text().strip())
            if chars >= _SCANNED_TEXT_THRESHOLD:
                return False
        return True
    except Exception:  # noqa: BLE001 — never raise from a guard
        return False
    finally:
        try:
            doc.close()
        except Exception:  # pragma: no cover
            pass


def ocr_pdf(src: Path, dst: Path, *, language: str = "eng") -> Path | None:
    """Run OCRmyPDF on ``src``, writing a searchable copy to ``dst``.

    Returns ``dst`` on success, or ``None`` on any failure (never raises).
    ``skip_text`` keeps pages that already carry text and only OCRs image pages,
    so it is safe on mixed documents and idempotent.
    """
    if not available():
        return None
    try:
        import ocrmypdf

        dst.parent.mkdir(parents=True, exist_ok=True)
        # Write to a unique temp path and atomically promote on success. A reader
        # (concurrent run/worker) or a re-run after a crash therefore only ever
        # sees a fully-written, validated PDF at ``dst`` — never a torn/partial
        # file. os.replace is atomic on the same filesystem (POSIX and Windows).
        tmp = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
        try:
            ocrmypdf.ocr(
                str(src),
                str(tmp),
                language=language,
                skip_text=True,      # don't re-OCR pages that already have text
                deskew=True,         # straighten scans → better OCR accuracy
                progress_bar=False,
            )
            if tmp.exists() and tmp.stat().st_size > 0 and _is_valid_pdf(tmp):
                os.replace(tmp, dst)
                return dst
            return None
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:  # pragma: no cover — best-effort temp cleanup
                    pass
    except Exception as exc:  # noqa: BLE001 — OCR is best-effort; fall back to original
        _log.warning("ocr_failed", src=str(src), error=str(exc))
        return None


def maybe_ocr(
    pdf_path: Path,
    out_dir: Path,
    *,
    language: str = "eng",
    cache_root: Path | None = None,
) -> Path:
    """Return a searchable copy of ``pdf_path`` when it is a scanned PDF and OCR
    is available; otherwise return the original path unchanged. Never raises.

    Idempotent: an existing searchable copy in ``out_dir`` (same filename) is
    reused instead of re-OCR'ing.

    ``cache_root`` (optional) enables a **machine-global, content-addressed**
    cache so an identical scan is OCR'd once *per machine* — not once per run.
    The global copy lives at ``cache_root/<sha16>/<language>/<original_name>`` (the
    content-hash **and** language make the key collision-safe across runs and never
    serve a wrong-language text layer), but the result is always
    **materialized back into ``out_dir/<name>``** and THAT per-run path is what is
    returned — so every downstream path convention (e.g. the compare view's
    ``<run>/ocr/<name>`` lookup) is byte-identical to the non-cached path. The
    global cache only skips the expensive Tesseract/Ghostscript *compute*; it never
    changes the returned location. When ``cache_root`` is None the behavior is
    exactly the legacy per-``out_dir`` path, so existing callers/tests are unchanged.
    """
    try:
        if (
            pdf_path.suffix.lower() != ".pdf"
            or not available()
            or not needs_ocr(pdf_path)
        ):
            return pdf_path
        dst = out_dir / pdf_path.name
        # Already materialized for this run → reuse (idempotent, unchanged).
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        # Machine-global content cache (opt-in): fill it once, then materialize the
        # result into the per-run dir so downstream sees the same <out_dir>/<name>.
        if cache_root is not None:
            try:
                digest = _content_sha(pdf_path)
                # Key on the OCR-output-determining params too, so switching
                # HYPERLINK_OCR_LANGUAGE never serves a wrong-language text layer.
                # Sanitize the language for use as a path segment ("eng+deu",
                # "en,de" -> a safe folder name).
                lang_key = re.sub(r"[^A-Za-z0-9+._-]", "_", language) or "eng"
                cached = Path(cache_root) / digest[:16] / lang_key / pdf_path.name
                # Reuse only a COMPLETE, valid cached PDF; a truncated/corrupt entry
                # (from an earlier crash/kill mid-write) is re-OCR'd rather than
                # served — the content cache self-heals instead of poisoning runs.
                if not (cached.exists() and cached.stat().st_size > 0 and _is_valid_pdf(cached)):
                    ocr_pdf(pdf_path, cached, language=language)  # compute once per machine
                if cached.exists() and cached.stat().st_size > 0 and _is_valid_pdf(cached):
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cached, dst)  # materialize into the per-run location
                    _log.info("ocr_from_cache", src=str(pdf_path), cached=str(cached), dst=str(dst))
                    return dst
                # Global OCR produced nothing → fall through to a direct per-run OCR.
            except Exception as exc:  # noqa: BLE001 — cache is best-effort, degrade
                _log.warning("ocr_cache_error", src=str(pdf_path), error=str(exc))
        result = ocr_pdf(pdf_path, dst, language=language)
        if result is not None:
            _log.info("ocr_applied", src=str(pdf_path), dst=str(result))
            return result
        return pdf_path
    except Exception as exc:  # noqa: BLE001 — never break ingestion
        _log.warning("maybe_ocr_error", src=str(pdf_path), error=str(exc))
        return pdf_path
