"""
pdf2line.extract — Hybrid PDF text extraction.

This is the only stage carried over (in spirit) from the previous TEI/XML
pipeline: a **hybrid** extractor that prefers PyMuPDF and can fall back to
pytiblegenc for legacy-encoded fonts.

For this package the extractor returns text **grouped by page** — a list where
each element is the raw multi-line text of one PDF page. The page-assembly
stage (``pdf2line.assemble``) then turns each page into a single output line.

Backends
--------
- **pymupdf** (default): ``page.get_text("text")`` per page. Fast, correct for
  Unicode Tibetan PDFs such as the MonlamUni / Jonang Dharma sources.
- **pytiblegenc** (optional): used only when explicitly requested and available;
  intended for legacy-encoded PDFs that PyMuPDF cannot decode to Unicode.
- **hybrid** (default policy): try pymupdf; if a page yields little/no Tibetan
  but the PDF embeds a known legacy font, retry that PDF via pytiblegenc.

Only pymupdf is required. pytiblegenc is imported lazily and is optional.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("pdf2line.extract")

_TIBETAN_RE = re.compile(r"[\u0f00-\u0fff]")

try:
    import fitz  # PyMuPDF
    _HAVE_PYMUPDF = True
except Exception:  # pragma: no cover
    _HAVE_PYMUPDF = False

# pytiblegenc is optional and imported lazily inside the function that needs it.


def _require_pymupdf() -> None:
    if not _HAVE_PYMUPDF:
        raise RuntimeError(
            "PyMuPDF (pymupdf) is required. Install with: pip install pymupdf"
        )


def _tibetan_ratio(text: str) -> float:
    """Fraction of non-space characters that are Tibetan script."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    tib = sum(1 for c in chars if "\u0f00" <= c <= "\u0fff")
    return tib / len(chars)


def extract_pages_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
) -> List[str]:
    """
    Extract text per page with PyMuPDF.

    Returns a list of strings, one per PDF page, each containing that page's
    text with its original visual line breaks (``\n``) preserved. Optional
    header/footer cropping removes a fraction of page height before extraction.
    """
    _require_pymupdf()
    doc = fitz.open(str(pdf_path))
    pages: List[str] = []
    try:
        for page in doc:
            clip = None
            if crop_top > 0.0 or crop_bottom > 0.0:
                r = page.rect
                clip = fitz.Rect(
                    r.x0,
                    r.y0 + r.height * crop_top,
                    r.x1,
                    r.y1 - r.height * crop_bottom,
                )
            pages.append(page.get_text("text", clip=clip))
    finally:
        doc.close()
    return pages


def extract_pages_pytiblegenc(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    page_break_str: str = "\x0c",
) -> List[str]:
    """
    Extract text per page with pytiblegenc (legacy-font decoding).

    Lazily imports pytiblegenc; raises if unavailable. Splits the returned text
    on the page-break marker to recover per-page grouping.
    """
    try:
        from pytiblegenc import pdf_to_txt  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "pytiblegenc is required for the pytiblegenc backend. Install with: "
            "pip install git+https://github.com/buda-base/py-tiblegenc.git"
        ) from exc

    # Optional crop: pytiblegenc reads a file path, so crop into a temp PDF.
    tmp: Optional[Path] = None
    try:
        target = pdf_path
        if crop_top > 0.0 or crop_bottom > 0.0:
            tmp = _make_cropped_pdf(pdf_path, crop_top, crop_bottom)
            target = tmp
        text = pdf_to_txt(
            str(target),
            page_break_str=f"\n{page_break_str}\n",
            normalize=False,
        )
        # Recover pages by splitting on the marker.
        parts = re.split(rf"\s*{re.escape(page_break_str)}\s*", text)
        return parts
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _make_cropped_pdf(pdf_path: Path, crop_top: float, crop_bottom: float) -> Path:
    """Write a temp PDF with each page's cropbox reduced by the given fractions."""
    _require_pymupdf()
    import tempfile

    doc = fitz.open(str(pdf_path))
    try:
        for page in doc:
            r = page.rect
            page.set_cropbox(
                fitz.Rect(
                    r.x0,
                    r.y0 + r.height * crop_top,
                    r.x1,
                    r.y1 - r.height * crop_bottom,
                )
            )
        fd, name = tempfile.mkstemp(suffix=".pdf")
        import os

        os.close(fd)
        out = Path(name)
        doc.save(str(out))
        return out
    finally:
        doc.close()


# Known legacy font name fragments that signal pytiblegenc may decode better.
_LEGACY_FONT_HINTS = ("tcrc", "youtso", "sambhota", "esukhia")


def _pdf_has_legacy_font(pdf_path: Path) -> bool:
    _require_pymupdf()
    doc = fitz.open(str(pdf_path))
    try:
        for page in doc:
            for f in page.get_fonts():
                base = (f[3] or "").lower()
                if any(h in base for h in _LEGACY_FONT_HINTS):
                    return True
    finally:
        doc.close()
    return False


def extract_pages(
    pdf_path: Path,
    *,
    backend: str = "hybrid",
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    hybrid_min_tibetan_ratio: float = 0.20,
) -> List[str]:
    """
    Extract per-page text using the chosen backend.

    backend
        - ``"pymupdf"``: PyMuPDF only.
        - ``"pytiblegenc"``: pytiblegenc only.
        - ``"hybrid"`` (default): PyMuPDF first; if the document's overall
          Tibetan ratio is below ``hybrid_min_tibetan_ratio`` AND a legacy font
          is present, retry the whole PDF with pytiblegenc.
    """
    if backend == "pymupdf":
        return extract_pages_pymupdf(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom)
    if backend == "pytiblegenc":
        return extract_pages_pytiblegenc(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom)

    # hybrid
    pages = extract_pages_pymupdf(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom)
    joined = "\n".join(pages)
    ratio = _tibetan_ratio(joined)
    if ratio < hybrid_min_tibetan_ratio and _pdf_has_legacy_font(pdf_path):
        logger.info(
            "  hybrid: low Tibetan ratio (%.2f) + legacy font -> retry pytiblegenc: %s",
            ratio, pdf_path.name,
        )
        try:
            return extract_pages_pytiblegenc(
                pdf_path, crop_top=crop_top, crop_bottom=crop_bottom
            )
        except RuntimeError as exc:
            logger.warning(
                "  hybrid: pytiblegenc unavailable (%s); keeping PyMuPDF output.", exc
            )
    return pages


def extract_pdf_text(pdf_path: Path, **kwargs) -> str:
    """Convenience: extract and return all pages joined by form-feed (\\x0c)."""
    return "\x0c".join(extract_pages(pdf_path, **kwargs))
