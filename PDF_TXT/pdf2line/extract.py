"""
pdf2line.extract - Hybrid PDF text extraction.

Backends
--------
- pymupdf (default): page.get_text("text") per page. Fast, correct for
  Unicode Tibetan PDFs.
- pytiblegenc (optional): for legacy-encoded PDFs that PyMuPDF cannot decode.
- hybrid (default policy): try pymupdf; if a page yields little/no Tibetan
  but the PDF embeds a known legacy font, retry that PDF via pytiblegenc.

Two-up / multi-column support
------------------------------
Pass two_up=True to split each PDF page into left and right halves before
extraction. Each half is returned as a separate entry so assemble.py can
detect embedded page-number lines and split them correctly.

Pass auto_two_up=True to enable automatic detection: any PDF page whose
width exceeds 1.5x its height is treated as a two-up scan.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("pdf2line.extract")

_TIBETAN_RE = re.compile(r"[ༀ-࿿]")

# Aspect-ratio threshold: width / height > this => likely two-up scan.
_TWO_UP_RATIO = 1.5

try:
    import fitz  # PyMuPDF
    _HAVE_PYMUPDF = True
except Exception:  # pragma: no cover
    _HAVE_PYMUPDF = False


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
    tib = sum(1 for c in chars if "ༀ" <= c <= "࿿")
    return tib / len(chars)


def _is_two_up_page(page) -> bool:
    """Return True if the page aspect ratio suggests a two-up (landscape) scan."""
    r = page.rect
    return r.width > _TWO_UP_RATIO * r.height


def _extract_page_text(page, clip=None) -> str:
    """Extract text from a single PyMuPDF page, optionally within a clip rect."""
    return page.get_text("text", clip=clip)


def extract_pages_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    two_up: bool = False,
    auto_two_up: bool = False,
) -> List[str]:
    """
    Extract text per page with PyMuPDF.

    Returns a list of strings, one per PDF page (or one per half-page when
    two_up / auto_two_up is active), each containing that page's text with its
    original visual line breaks preserved.

    Parameters
    ----------
    two_up : Force split every page into left and right halves.
    auto_two_up : Automatically split pages whose width > 1.5x height.
    crop_top, crop_bottom : Fractions of page height to remove from top/bottom.
    """
    _require_pymupdf()
    doc = fitz.open(str(pdf_path))
    pages: List[str] = []
    try:
        for page in doc:
            r = page.rect
            split = two_up or (auto_two_up and _is_two_up_page(page))
            y0 = r.y0 + r.height * crop_top
            y1 = r.y1 - r.height * crop_bottom
            if split:
                mid_x = (r.x0 + r.x1) / 2
                left_clip  = fitz.Rect(r.x0,  y0, mid_x, y1)
                right_clip = fitz.Rect(mid_x, y0, r.x1,  y1)
                pages.append(_extract_page_text(page, clip=left_clip))
                pages.append(_extract_page_text(page, clip=right_clip))
            else:
                clip = fitz.Rect(r.x0, y0, r.x1, y1) if (crop_top or crop_bottom) else None
                pages.append(_extract_page_text(page, clip=clip))
    finally:
        doc.close()
    return pages


def extract_pages_pytiblegenc(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    two_up: bool = False,
    auto_two_up: bool = False,
    page_break_str: str = "\x0c",
) -> List[str]:
    """
    Extract text per page with pytiblegenc (legacy-font decoding).

    Lazily imports pytiblegenc; raises if unavailable. For two-up scans,
    requires an intermediate cropped-PDF step per half (slower than PyMuPDF).
    """
    try:
        from pytiblegenc import pdf_to_txt  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "pytiblegenc is required for the pytiblegenc backend. Install with: "
            "pip install git+https://github.com/buda-base/py-tiblegenc.git"
        ) from exc

    def _run(target: Path) -> List[str]:
        text = pdf_to_txt(
            str(target),
            page_break_str="\n" + page_break_str + "\n",
            normalize=False,
        )
        return re.split(r"\s*" + re.escape(page_break_str) + r"\s*", text)

    if two_up or auto_two_up:
        _require_pymupdf()
        doc = fitz.open(str(pdf_path))
        page_rects = [(i, page.rect) for i, page in enumerate(doc)]
        doc.close()

        all_pages: List[str] = []
        for page_idx, rect in page_rects:
            do_split = two_up or (auto_two_up and rect.width > _TWO_UP_RATIO * rect.height)
            halves = (
                [(rect.x0, (rect.x0 + rect.x1) / 2),
                 ((rect.x0 + rect.x1) / 2, rect.x1)]
                if do_split
                else [(rect.x0, rect.x1)]
            )
            for x0, x1 in halves:
                tmp = _make_cropped_pdf(
                    pdf_path,
                    crop_top=crop_top, crop_bottom=crop_bottom,
                    clip_x0=x0, clip_x1=x1,
                    page_indices=[page_idx],
                )
                try:
                    all_pages.extend(_run(tmp))
                finally:
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
        return all_pages

    # Simple path: no two-up splitting needed.
    if crop_top > 0.0 or crop_bottom > 0.0:
        tmp = _make_cropped_pdf(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom)
        try:
            return _run(tmp)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    return _run(pdf_path)


def _make_cropped_pdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    clip_x0: Optional[float] = None,
    clip_x1: Optional[float] = None,
    page_indices: Optional[List[int]] = None,
) -> Path:
    """
    Write a temporary PDF with each page's cropbox adjusted.

    Supports vertical crop fractions and optional horizontal clip. If
    page_indices is given, only those pages are included in the output.
    Returns the temp file path; caller is responsible for deletion.
    """
    _require_pymupdf()
    doc = fitz.open(str(pdf_path))
    try:
        indices = page_indices if page_indices is not None else list(range(len(doc)))
        out_doc = fitz.open()
        for i in indices:
            page = doc[i]
            r = page.rect
            x0 = clip_x0 if clip_x0 is not None else r.x0
            x1 = clip_x1 if clip_x1 is not None else r.x1
            y0 = r.y0 + r.height * crop_top
            y1 = r.y1 - r.height * crop_bottom
            out_doc.insert_pdf(doc, from_page=i, to_page=i)
            new_page = out_doc[-1]
            new_page.set_cropbox(fitz.Rect(x0, y0, x1, y1))

        fd, name = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        out_path = Path(name)
        out_doc.save(str(out_path))
        out_doc.close()
        return out_path
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
    two_up: bool = False,
    auto_two_up: bool = False,
    hybrid_min_tibetan_ratio: float = 0.20,
) -> List[str]:
    """
    Extract per-page text using the chosen backend.

    backend
        "pymupdf": PyMuPDF only.
        "pytiblegenc": pytiblegenc only.
        "hybrid" (default): PyMuPDF first; if the document's overall Tibetan
        ratio is below hybrid_min_tibetan_ratio AND a legacy font is present,
        retry the whole PDF with pytiblegenc.

    two_up
        Force split every PDF page into left/right halves. Use when one scan
        page contains two facing pecha pages.

    auto_two_up
        Detect two-up pages automatically by aspect ratio (width > 1.5x height).

    hybrid_min_tibetan_ratio
        Tibetan-character fraction below which the hybrid backend retries with
        pytiblegenc (only when a legacy font is detected). Default: 0.20.
    """
    common = dict(
        crop_top=crop_top,
        crop_bottom=crop_bottom,
        two_up=two_up,
        auto_two_up=auto_two_up,
    )

    if backend == "pymupdf":
        return extract_pages_pymupdf(pdf_path, **common)
    if backend == "pytiblegenc":
        return extract_pages_pytiblegenc(pdf_path, **common)

    # hybrid
    pages = extract_pages_pymupdf(pdf_path, **common)
    joined = "\n".join(pages)
    ratio = _tibetan_ratio(joined)
    if ratio < hybrid_min_tibetan_ratio and _pdf_has_legacy_font(pdf_path):
        logger.info(
            "  hybrid: low Tibetan ratio (%.2f) + legacy font -> retry pytiblegenc: %s",
            ratio, pdf_path.name,
        )
        try:
            return extract_pages_pytiblegenc(pdf_path, **common)
        except RuntimeError as exc:
            logger.warning(
                "  hybrid: pytiblegenc unavailable (%s); keeping PyMuPDF output.", exc
            )
    return pages


def extract_pdf_text(pdf_path: Path, **kwargs) -> str:
    """Convenience: extract and return all pages joined by form-feed."""
    return "\x0c".join(extract_pages(pdf_path, **kwargs))
