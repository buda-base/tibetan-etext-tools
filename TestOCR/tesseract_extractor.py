"""
Tesseract OCR-based PDF text extraction: render each page to a bitmap (optional clip)
and run Tesseract. Region semantics match :func:`pymupdf_extractor._pymupdf_clip_rect`
and ``config.PDF_EXTRACT_REGION`` (same as PyMuPDF text extraction).

Requires the ``tesseract`` executable on ``PATH`` (or set
``pytesseract.pytesseract.tesseract_cmd``) and trained data for the chosen language
(e.g. ``bod`` for Tibetan).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

from pymupdf_extractor import _pymupdf_clip_rect

log = logging.getLogger(__name__)


def _pad_image_bottom_for_ocr(img: Image.Image, *, frac: float = 0.03, min_px: int = 40) -> Image.Image:
    """
    Add white space below the page bitmap. Tesseract often drops or garbles the last
    line when text sits on the bottom edge of the image; padding avoids that.
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    pad = max(int(round(h * frac)), min_px)
    out = Image.new("RGB", (w, h + pad), (255, 255, 255))
    out.paste(rgb, (0, 0))
    return out


def extract_pdf_to_text_tesseract(
    pdf_path: Path,
    *,
    region,
    page_break_str: str,
    dpi: float = 300.0,
    lang: str = "bod",
    tesseract_config: str = "",
) -> str:
    """
    Rasterize each PDF page (optionally clipped) and OCR with Tesseract.

    :param pdf_path: Input PDF.
    :param region: Same as ``extract_pdf_to_text_pymupdf`` / ``PDF_EXTRACT_REGION``:
        ``[x0, y0, width, height]`` with values in ``(0, 1)`` as fractions of page size.
        ``None`` or invalid → full page.
    :param page_break_str: Inserted before each page’s text (same convention as pymupdf path).
    :param dpi: Rasterization resolution (72 PDF points → pixels via ``fitz.Matrix``).
    :param lang: Tesseract language(s), e.g. ``bod`` or ``bod+eng``.
    :param tesseract_config: Extra Tesseract CLI options (e.g. ``"--psm 6"``).
    """
    import fitz  # PyMuPDF

    try:
        import pytesseract
    except ImportError as e:
        raise ImportError(
            "tesseract_extractor requires the 'pytesseract' package "
            "(pip install pytesseract). Pillow is also required."
        ) from e

    zoom = max(1e-6, float(dpi)) / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    sep = page_break_str
    chunks: list[str] = []
    doc = fitz.open(pdf_path)
    n_pages = len(doc)
    log.info(
        f"Tesseract OCR: starting {pdf_path.name} ({n_pages} page{'s' if n_pages != 1 else ''}, {dpi:.0f} dpi)"
    )
    try:
        for i in range(n_pages):
            page = doc[i]
            chunks.append(sep)
            clip = _pymupdf_clip_rect(page, region)
            kw: dict = {"matrix": matrix, "alpha": False}
            if clip is not None:
                kw["clip"] = clip
            pix = page.get_pixmap(**kw)
            png_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(png_bytes))
            img = _pad_image_bottom_for_ocr(img)
            ocr_kw: dict = {}
            if lang and lang.strip():
                ocr_kw["lang"] = lang.strip()
            tc = tesseract_config.strip()
            if tc:
                ocr_kw["config"] = tc
            try:
                text = pytesseract.image_to_string(img, **ocr_kw)
            except pytesseract.TesseractNotFoundError as e:
                raise RuntimeError(
                    "Tesseract executable not found. Install Tesseract OCR and ensure "
                    "it is on PATH, or set pytesseract.pytesseract.tesseract_cmd to the "
                    "full path of the binary."
                ) from e
            chunks.append(text.rstrip("\n") + "\n")
            cur = i + 1
            if cur % 50 == 0 or cur == n_pages:
                log.info(
                    f"Tesseract OCR: {cur}/{n_pages} pages done — {pdf_path.name}"
                )
    finally:
        doc.close()

    return "".join(chunks)
