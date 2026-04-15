"""
PyMuPDF-based PDF text extraction: layout + ``<fs:N>`` + pytiblegenc ``convert_string`` per span.

Used when ``config.PDF_EXTRACT_BACKEND`` is ``"pymupdf"``. Region semantics match
``pytiblegenc.pdf_to_txt(..., region=...)`` (see :func:`_pymupdf_clip_rect`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from tibetan_text_fixes import collapse_duplicate_tibetan_span_marks

log = logging.getLogger(__name__)


def _pymupdf_clip_rect(page, region) -> object | None:
    """
    Clip rectangle for PyMuPDF, aligned with pytiblegenc ``PDF_EXTRACT_REGION``:
    ``[x0, y0, width, height]`` with values in (0, 1) treated as fractions of
    page width/height (same rules as ``scale_region_box`` in
    ``DuffedTextConverter``).

    pdfminer y is measured **upward from the bottom** of the page; PyMuPDF y is
    **downward from the top**. We build the same absolute box as pytiblegenc,
    then convert y for ``fitz.Rect`` / ``get_text(..., clip=...)``.
    """
    if region is None or len(region) != 4:
        return None
    import fitz

    pr = page.rect
    lw, lh = pr.width, pr.height
    r = [region[0], region[1], region[0] + region[2], region[1] + region[3]]
    out: list[float] = []
    for i, c in enumerate(r):
        # Match ``scale_region_box`` (``c > 0 and c < 1``).
        if c > 0 and c < 1:
            if i % 2 == 0:
                out.append(int(c * lw) + pr.x0)
            else:
                # LTPage origin is bottom-left; y0 is 0 on mediabox — not pr.y0 (top).
                out.append(int(c * lh))
        else:
            out.append(float(c))
    x0, y0_pdf, x1, y1_pdf = out[0], out[1], out[2], out[3]
    y0_mupdf = pr.y0 + lh - y1_pdf
    y1_mupdf = pr.y0 + lh - y0_pdf
    clip = fitz.Rect(x0, y0_mupdf, x1, y1_mupdf)
    clip = clip & pr
    if clip.is_empty:
        return None
    return clip


def extract_pdf_to_text_pymupdf(
    pdf_path: Path,
    *,
    region,
    page_break_str: str,
    font_size_format: str,
) -> str:
    """
    PyMuPDF path: layout + ``<fs:N>`` + ``convert_string`` per span.

    PyMuPDF’s text layer often matches what you see when a PDF’s ToUnicode / cmap is
    wrong or ambiguous; pdfminer + pytiblegenc can disagree because it walks glyphs and
    font tables differently. Trade-off: layout/order can still differ between backends.
    """
    import fitz  # PyMuPDF
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser
    from pytiblegenc.char_converter import convert_string
    from pytiblegenc.font_utils import (
        build_font_hash_index_from_csv,
        build_glyph_lookup_tables,
        get_glyph_db_path,
        identify_pdf_fonts_from_db,
    )

    stats = {
        "unhandled_fonts": {},
        "handled_fonts": {},
        "unknown_characters": {},
        "error_characters": 0,
        "diffs_with_utfc": {},
        "nb_non_horizontal_removed": 0,
    }

    def _wrap_font_for_convert(fontname: str, font_norm: Optional[dict]) -> str:
        """Mirror ``DuffedTextConverter.convert_item`` font name handling (PyMuPDF-only)."""
        fn = fontname or ""
        if font_norm:
            if fn in font_norm and font_norm[fn]:
                fn = next(iter(font_norm[fn]))
            else:
                plus_pos = fn.find("+")
                if plus_pos >= 0:
                    basefont = fn[plus_pos + 1 :]
                    if basefont in font_norm and font_norm[basefont]:
                        fn = next(iter(font_norm[basefont]))
        return fn[fn.find("+") + 1 :]

    font_normalization = None
    glyph_lookup = None
    try:
        glyph_db_path = get_glyph_db_path()
        gpath = str(glyph_db_path)
        glyph_index = build_font_hash_index_from_csv(gpath)
        with open(pdf_path, "rb") as in_file:
            parser = PDFParser(in_file)
            doc = PDFDocument(parser)
            font_normalization = identify_pdf_fonts_from_db(doc, glyph_index)
        glyph_lookup = build_glyph_lookup_tables(gpath)
    except Exception as e:
        log.debug("pymupdf: font normalization / glyph lookup skipped: %s", e)

    def _page_dict_to_fs_text(page_dict: dict) -> str:
        lines_out: list[str] = []
        for block in page_dict.get("blocks", ()):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", ()):
                runs: list[tuple[Optional[int], str]] = []
                for span in line.get("spans", ()):
                    t_raw = span.get("text") or ""
                    if not t_raw:
                        continue
                    font_raw = span.get("font") or ""
                    fn = _wrap_font_for_convert(font_raw, font_normalization)
                    ctext = convert_string(t_raw, fn, stats, None, glyph_lookup)
                    t = t_raw if ctext is None else ctext
                    raw = span.get("size")
                    fs = max(0, int(round(float(raw)))) if raw is not None else None
                    if runs and runs[-1][0] == fs:
                        prev_fs, prev_t = runs[-1]
                        runs[-1] = (prev_fs, prev_t + t)
                    else:
                        runs.append((fs, t))
                parts: list[str] = []
                for fs, t in runs:
                    if fs is not None:
                        parts.append(font_size_format.format(fs) + t)
                    else:
                        parts.append(t)
                if parts:
                    lines_out.append("".join(parts))
        return "\n".join(lines_out)

    sep = page_break_str
    doc = fitz.open(pdf_path)
    try:
        chunks: list[str] = []
        for i in range(len(doc)):
            page = doc[i]
            chunks.append(sep)
            clip = _pymupdf_clip_rect(page, region)
            kw: dict = {}
            if clip is not None:
                kw["clip"] = clip
            try:
                page_dict = page.get_text("dict", sort=True, **kw)
            except TypeError:
                page_dict = page.get_text("dict", **kw)
            chunks.append(_page_dict_to_fs_text(page_dict))
        return collapse_duplicate_tibetan_span_marks("".join(chunks))
    finally:
        doc.close()
