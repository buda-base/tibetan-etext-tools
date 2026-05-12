"""
PDF text extraction for IE1KG25273: PyMuPDF ``rawdict`` or ``pytiblegenc.pdf_to_txt``.

Line breaks are layout-level (one ``\\n`` per extractor line); ``PAGE_BREAK_STR`` marks pages.
"""

from __future__ import annotations

import logging
import os
import tempfile
import traceback
from pathlib import Path
from typing import Optional

try:
    import pymupdf as fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    try:
        import fitz
        PYMUPDF_AVAILABLE = True
    except ImportError:
        PYMUPDF_AVAILABLE = False
        fitz = None  # type: ignore

try:
    from pytiblegenc import pdf_to_txt
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False
    pdf_to_txt = None  # type: ignore

logger = logging.getLogger(__name__)

PAGE_BREAK_STR = "ZZZZ"
_FONT_SIZE_FORMAT = "<fs:{}>"


def create_cropped_pdf(
    pdf_path: Path,
    top_frac: float,
    bottom_frac: float,
    left_frac: float = 0.0,
    right_frac: float = 0.0,
) -> Optional[Path]:
    """
    Temp PDF with header/footer bands physically redacted (text removed, white fill).

    Uses ``add_redact_annot`` + ``apply_redactions`` on ``page.rect`` fractions.
    """
    if top_frac == 0.0 and bottom_frac == 0.0:
        return None

    if not PYMUPDF_AVAILABLE:
        logger.warning(
            "Header/footer redaction requested but PyMuPDF is not installed. "
            "pip install pymupdf — continuing without redaction."
        )
        return None

    try:
        doc = fitz.open(str(pdf_path))

        for page in doc:
            r = page.rect
            h = r.height
            w = r.width

            if top_frac > 0.0:
                page.add_redact_annot(
                    fitz.Rect(r.x0, r.y0, r.x1, r.y0 + h * top_frac)
                )

            if bottom_frac > 0.0:
                page.add_redact_annot(
                    fitz.Rect(r.x0, r.y0 + h * (1.0 - bottom_frac), r.x1, r.y1)
                )
            if left_frac > 0.0:
                page.add_redact_annot(
                    fitz.Rect(r.x0, r.y0, r.x0 + w * left_frac, r.y1)
                )

            if right_frac > 0.0:
                page.add_redact_annot(
                    fitz.Rect(r.x1 - w * right_frac, r.y0, r.x1, r.y1)
                )

            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=0,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, dir=tempfile.gettempdir()
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        doc.save(str(tmp_path), garbage=4, deflate=True)
        doc.close()

        logger.info(
            f"    Redacted temp PDF: {tmp_path.name} "
            f"(top={top_frac*100:.1f}%, bottom={bottom_frac*100:.1f}%)"
        )
        return tmp_path

    except Exception as e:
        logger.warning(
            f"    Failed to redact header/footer on {pdf_path.name}: {e} — using original PDF."
        )
        return None


def _is_wingdings_font(font_name: str) -> bool:
    if not font_name:
        return False
    base = font_name.split("+")[-1]
    compact = base.lower().replace(" ", "")
    return "wingdings" in compact


def extract_pdf_pytiblegenc(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    crop_left: float = 0.0,
    crop_right: float = 0.0,
) -> str:
    """
    Extract via ``pytiblegenc.pdf_to_txt`` (same options as IE3KG664 / Desktop SRC_CODE).

    Optional ``crop_top`` / ``crop_bottom`` (fractions of page height) use ``create_cropped_pdf``.
    """
    logger.info(f"    Extracting (pytiblegenc pdf_to_txt): {pdf_path.name}")

    if not PYTIBLEGENC_AVAILABLE:
        logger.error(
            "pytiblegenc is required for --extractor pytiblegenc. "
            "pip install git+https://github.com/buda-base/py-tiblegenc.git"
        )
        return ""

    tmp_pdf: Optional[Path] = None

    try:
        if crop_top > 0.0 or crop_bottom > 0.0:
        tmp_pdf = create_cropped_pdf(
            pdf_path,
            crop_top,
            crop_bottom,
            CROP_LEFT_FRACTION,
            CROP_RIGHT_FRACTION,
        )

        target_pdf = tmp_pdf if tmp_pdf else pdf_path

        text = pdf_to_txt(
            str(target_pdf),
            page_break_str=f"\n{PAGE_BREAK_STR}\n",
            track_font_size=True,
            font_size_format=_FONT_SIZE_FORMAT,
            normalize=False,
            simplify_font_sizes_option=False,
        )
        return text

    except Exception as e:
        logger.error(f"    ERROR extracting {pdf_path.name}: {e}")
        traceback.print_exc()
        return ""
    finally:
        if tmp_pdf is not None and tmp_pdf.exists():
            try:
                os.unlink(tmp_pdf)
            except OSError:
                pass


def _extract_line_text(line: dict) -> list:
    """
    Extract (font_size, text) fragments from a single MuPDF ``line`` dict,
    skipping Wingdings fonts.  Returns a list of strings (font-size tags + text).
    """
    fragments: list[str] = []
    for span in line.get("spans", []):
        if _is_wingdings_font(span.get("font") or ""):
            continue
        fs = round(span.get("size", 12))
        fragments.append(_FONT_SIZE_FORMAT.format(fs))
        char_objs = span.get("chars") or []
        if char_objs:
            for char_obj in char_objs:
                fragments.append(char_obj.get("c", ""))
        else:
            fragments.append(span.get("text") or "")
    return fragments


# Tolerance in points for treating two MuPDF lines as the same visual row.
# Tibetan glyphs with vowel marks can cause small Y shifts across spans.
_Y_MERGE_TOLERANCE = 3.0


def extract_pdf_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    crop_left: float = 0.0,
    crop_right: float = 0.0,
) -> str:
    """
    Extract text using PyMuPDF ``rawdict``: one ``\\n`` per **visual** line.

    MuPDF often splits a single visual line into multiple ``line`` objects
    (e.g. at a Tibetan shad ``།``).  We merge lines whose vertical midpoints
    are within ``_Y_MERGE_TOLERANCE`` points of each other, then sort left-
    to-right so the reading order is preserved.
    """
    logger.info(f"    Extracting (PyMuPDF rawdict): {pdf_path.name}")

    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF is required for --extractor pymupdf. pip install pymupdf")
        return ""

    tmp_pdf: Optional[Path] = None

    try:
        if crop_top > 0.0 or crop_bottom > 0.0:
        tmp_pdf = create_cropped_pdf(
            pdf_path,
            crop_top,
            crop_bottom,
            CROP_LEFT_SIDE_FRACTION,
            CROP_RIGHT_SIDE_FRACTION,
        )

        target_pdf = tmp_pdf if tmp_pdf else pdf_path
        doc = fitz.open(str(target_pdf))
        parts: list[str] = []

        for page in doc:
            page_dict = page.get_text("rawdict")

            # Collect every MuPDF line across all text blocks on this page,
            # together with its vertical midpoint and horizontal start.
            raw_lines: list[tuple[float, float, list[str]]] = []  # (y_mid, x0, fragments)

            for block in page_dict.get("blocks", []):
                if block.get("type", 1) != 0:
                    continue
                for line in block.get("lines", []):
                    bbox = line.get("bbox", [0, 0, 0, 0])
                    y_mid = (bbox[1] + bbox[3]) / 2.0
                    x0 = bbox[0]
                    fragments = _extract_line_text(line)
                    if fragments:
                        raw_lines.append((y_mid, x0, fragments))

            # Sort by vertical position first, then left-to-right.
            raw_lines.sort(key=lambda t: (t[0], t[1]))

            # Merge lines that share (approximately) the same Y midpoint.
            merged_rows: list[list[tuple[float, float, list[str]]]] = []  # each row = list of (y_mid, x0, frags)
            for y_mid, x0, frags in raw_lines:
                if merged_rows:
                    # Check if this line belongs to the current visual row.
                    last_y = merged_rows[-1][0][0]  # y_mid of first entry in row
                    # Use the average y_mid of the current row for comparison.
                    avg_y = sum(e[0] for e in merged_rows[-1]) / len(merged_rows[-1])
                    if abs(y_mid - avg_y) <= _Y_MERGE_TOLERANCE:
                        merged_rows[-1].append((y_mid, x0, frags))
                        continue
                # New visual row.
                merged_rows.append([(y_mid, x0, frags)])

            # Emit one \n per merged visual row.
            for row in merged_rows:
                # Sort spans within the row left-to-right.
                row.sort(key=lambda t: t[1])
                for _y, _x, frags in row:
                    parts.extend(frags)
                parts.append("\n")

            parts.append(f"\n{PAGE_BREAK_STR}\n")

        doc.close()
        return "".join(parts)

    except Exception as e:
        logger.error(f"    ERROR extracting {pdf_path.name}: {e}")
        traceback.print_exc()
        return ""
    finally:
        if tmp_pdf is not None and tmp_pdf.exists():
            try:
                os.unlink(tmp_pdf)
            except OSError:
                pass


def extract_pdf_to_text(
    pdf_path: Path,
    extractor: str,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    crop_left: float = 0.0,
    crop_right: float = 0.0,
) -> str:
    """Dispatch to PyMuPDF or pytiblegenc."""
    if extractor == "pytiblegenc":
        return extract_pdf_pytiblegenc(
            pdf_path, crop_top=crop_top, crop_bottom=crop_bottom
        )
    return extract_pdf_pymupdf(
        pdf_path, crop_top=crop_top, crop_bottom=crop_bottom
    )