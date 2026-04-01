"""
Extended PDF → text extraction on top of pytiblegenc / pdfminer.

- Optional pdfminer LAParams.boxes_flow for multi-column flow heuristics.
- Optional two-column mode: extract left/right (or right/left) vertical bands per page
  with a single page-break marker per physical page (fixes landscape 2-up ordering).
- Optional extraction region [x, y, w, h] (relative 0–1 or absolute), same as pytiblegenc.
"""

from __future__ import annotations

import logging
import re
from io import StringIO
from typing import Callable, List, Optional

from pdfminer.layout import LTContainer, LTImage, LTItem, LTPage, LTText, LTTextBox
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser

from pytiblegenc.font_size_utils import simplify_font_sizes
from pytiblegenc.font_utils import (
    build_font_hash_index_from_csv,
    get_glyph_db_path,
    identify_pdf_fonts_from_db,
)
from pytiblegenc.normalization import normalize_unicode
from pytiblegenc.pdfminer_text_converter import (
    CustomLAParams,
    DuffedTextConverter,
    USUAL_LA_PARAMS,
)


def _make_laparams(boxes_flow: Optional[float]):
    if boxes_flow is None:
        return USUAL_LA_PARAMS
    return CustomLAParams(
        char_margin=1000,
        word_margin=1000,
        char_margin_left=2,
        line_overlap=0.0,
        line_margin=1.8,
        boxes_flow=boxes_flow,
        detect_vertical=False,
        all_texts=False,
    )


class SuppressiblePageBreakDuffedConverter(DuffedTextConverter):
    """Same as DuffedTextConverter, but column passes can omit the page-break prefix."""

    def __init__(self, *args, emit_page_break: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.emit_page_break = emit_page_break

    def receive_layout(self, ltpage: LTPage) -> None:
        def render(item: LTItem, linenumref) -> None:
            if isinstance(item, LTContainer):
                for child in item:
                    render(child, linenumref)
            elif isinstance(item, LTText):
                if linenumref["linenum"] <= self.maxlines:
                    self.convert_item(item, ltpage)
            if isinstance(item, LTTextBox):
                self.write_text("\n")
                linenumref["linenum"] += 1
            elif isinstance(item, LTImage):
                if self.imagewriter is not None:
                    self.imagewriter.export_image(item)

        if self.emit_page_break:
            self.write_text(self.pbs.format(ltpage.pageid))
        if self.track_font_size:
            self.current_font_size = None
        render(ltpage, {"linenum": 1})


def _empty_stats() -> dict:
    return {
        "unhandled_fonts": {},
        "handled_fonts": {},
        "unknown_characters": {},
        "error_characters": 0,
        "diffs_with_utfc": {},
        "nb_non_horizontal_removed": 0,
    }


def _font_normalization_for_doc(doc: PDFDocument):
    try:
        glyph_db_path = get_glyph_db_path()
        glyph_index = build_font_hash_index_from_csv(str(glyph_db_path))
        return identify_pdf_fonts_from_db(doc, glyph_index)
    except Exception as e:
        logging.warning("Could not load font normalization: %s", e)
        return None


def _postprocess_raw(
    res: str,
    *,
    normalize: bool,
    simplify_font_sizes_option: bool,
    track_font_size: bool,
) -> str:
    res = re.sub(r"\n\n+", "\n", res)
    if simplify_font_sizes_option and track_font_size:
        res = simplify_font_sizes(res)
    if normalize:
        res = normalize_unicode(res)
    return res


def _intersect_xywh(a: List[float], b: List[float]) -> List[float]:
    """Intersect two axis-aligned rectangles as [x, y, width, height] (pdfminer y0 at bottom)."""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = ix1 - ix0
    ih = iy1 - iy0
    if iw <= 0 or ih <= 0:
        return a
    return [ix0, iy0, iw, ih]


def _merge_region_with_vertical_crop(
    region: Optional[List[float]],
    crop_top: float,
    crop_bottom: float,
    log: Optional[logging.Logger] = None,
) -> Optional[List[float]]:
    """
    Build pytiblegenc ``region`` as [x, y, width, height] with y the bottom edge of the box.

    Vertical crop removes ``crop_top`` / ``crop_bottom`` fractions of page height from the
    top and bottom. When ``region`` is also set (relative 0–1), the result is the
    intersection. Absolute regions (any coordinate outside [0, 1]) are returned unchanged
    if no crop is requested; with crop, crop is skipped and a warning is logged.
    """
    _eps = 1e-6
    crop_top = max(0.0, float(crop_top))
    crop_bottom = max(0.0, float(crop_bottom))
    if crop_top + crop_bottom >= 1.0:
        raise ValueError("crop_top + crop_bottom must be less than 1")
    h_body = 1.0 - crop_top - crop_bottom - _eps

    if region is None:
        if crop_top == 0 and crop_bottom == 0:
            return None
        return [0.0, crop_bottom, 1.0 - _eps, h_body]

    if len(region) != 4:
        raise ValueError("region must be [x, y, width, height]")

    rx, ry, rw, rh = region
    rel = all(0.0 <= c <= 1.0 for c in region)
    if not rel:
        if crop_top > 0 or crop_bottom > 0:
            if log:
                log.warning(
                    "PDF_EXTRACT_REGION looks absolute; skipping vertical crop. "
                    "Use relative 0–1 coordinates to combine with crop."
                )
            return region
        return region

    y0 = max(ry, crop_bottom)
    y1 = min(ry + rh, 1.0 - crop_top - _eps)
    x0 = max(0.0, rx)
    x1 = min(rx + rw, 1.0 - _eps)
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        raise ValueError("PDF_EXTRACT_REGION does not overlap vertical crop bands")
    return [x0, y0, w, h]


def extract_pdf_to_text_full(
    pdf_path: str,
    *,
    page_break_str: str,
    track_font_size: bool = False,
    font_size_format: str = "<fs:{}>",
    normalize: bool = False,
    simplify_font_sizes_option: bool = False,
    remove_non_hz: bool = True,
    error_chr_fun: Optional[Callable] = None,
    region: Optional[List[float]] = None,
    two_column: bool = False,
    column_order: str = "lr",
    column_split: float = 0.5,
    boxes_flow: Optional[float] = None,
    log: Optional[logging.Logger] = None,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
) -> str:
    """
    Extract text like pytiblegenc.pdf_to_txt with optional layout overrides.

    ``region`` is [x, y, w, h] in relative (0–1) or absolute units (pytiblegenc rules).
    ``crop_top`` / ``crop_bottom`` shrink the extraction area by that fraction of page
    height (no PDF rewrite; applied via the same region filter as pytiblegenc).
    When ``two_column`` is True, each page is extracted as two vertical bands
    (split at ``column_split`` on the 0–1 x-axis before page scaling), ordered
    by ``column_order`` ("lr" or "rl").
    """
    merged = _merge_region_with_vertical_crop(region, crop_top, crop_bottom, log=log)

    use_stock_pdf_to_txt = not two_column and boxes_flow is None
    if use_stock_pdf_to_txt:
        from pytiblegenc import pdf_to_txt as stock_pdf_to_txt

        return stock_pdf_to_txt(
            pdf_path,
            region=merged,
            page_break_str=page_break_str,
            remove_non_hz=remove_non_hz,
            track_font_size=track_font_size,
            font_size_format=font_size_format,
            error_chr_fun=error_chr_fun,
            normalize=normalize,
            simplify_font_sizes_option=simplify_font_sizes_option,
        )

    laparams = _make_laparams(boxes_flow)
    stats = _empty_stats()
    output_string = StringIO()

    column_order = column_order if column_order in ("lr", "rl") else "lr"
    split = min(max(column_split, 0.05), 0.95)
    # pytiblegenc only scales relative coords c with 0 < c < 1; y+h==1.0 stays as 1 pt — use slightly < 1.
    _eps = 1e-6
    _yf = 1.0 - _eps
    left_band: List[float] = [0.0, 0.0, split, _yf]
    # Avoid x1==1.0 (not scaled in pytiblegenc); shrink width slightly.
    right_band: List[float] = [split, 0.0, max(1.0 - split - _eps, _eps), _yf]
    if merged is not None:
        left_band = _intersect_xywh(left_band, merged)
        right_band = _intersect_xywh(right_band, merged)
    bands: List[List[float]] = (
        [left_band, right_band] if column_order == "lr" else [right_band, left_band]
    )

    with open(pdf_path, "rb") as in_file:
        parser = PDFParser(in_file)
        doc = PDFDocument(parser)
        font_normalization = _font_normalization_for_doc(doc)
        rsrcmgr = PDFResourceManager()

        converter = SuppressiblePageBreakDuffedConverter(
            rsrcmgr,
            output_string,
            stats,
            region=None if two_column else merged,
            laparams=laparams,
            pbs=page_break_str,
            remove_non_hz=remove_non_hz,
            font_normalization=font_normalization,
            error_chr_fun=error_chr_fun,
            track_font_size=track_font_size,
            font_size_format=font_size_format,
            emit_page_break=True,
        )
        interpreter = PDFPageInterpreter(rsrcmgr, converter)

        for _page in PDFPage.create_pages(doc):
            if two_column:
                for col_i, band in enumerate(bands):
                    converter.emit_page_break = col_i == 0
                    x, y, w, h = band
                    converter.region = [x, y, x + w, y + h]
                    if col_i > 0:
                        converter.write_text("\n")
                    interpreter.process_page(_page)
            else:
                converter.emit_page_break = True
                interpreter.process_page(_page)

    res = output_string.getvalue()
    return _postprocess_raw(
        res,
        normalize=normalize,
        simplify_font_sizes_option=simplify_font_sizes_option,
        track_font_size=track_font_size,
    )
