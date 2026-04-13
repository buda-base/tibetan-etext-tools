"""
PDF text extraction for Monlam-font PDFs: PyMuPDF ``rawdict`` or ``pytiblegenc.pdf_to_txt``.

Line breaks are layout-level (one ``\\n`` per extractor line); ``PAGE_BREAK_STR`` marks pages.

Fixes applied (all in the PyMuPDF path):
  1. Phantom space detection rule corrected  (space_x < prev_x + threshold, not < next_x)
  2. WinAnsi vowel glyph mis-mappings fixed  (ŀ→ོ, Ĳ→ེ, Ĩ→ི)
  3. Phantom space check threaded across span boundaries within a line
  4. Epsilon tolerance for near-zero-advance phantom spaces from WinAnsi vowel spans
  5. Duplicate text-layer deduplication for InDesign-generated PDFs (PyMuPDF path)
  6. Duplicate line deduplication for pytiblegenc path — InDesign PDFs produced via
     two different workflows both embed duplicate text layers, but with different
     interleaving patterns that require a sliding-window approach:

     a) PScript5/Acrobat Distiller (e.g. TI1047): every line is duplicated 2× at
        identical y-coordinates → pdfminer emits consecutive pairs (A A B B …).

     b) Adobe PDF Library / InDesign CS4 drop-shadow (e.g. TI1259): every line is
        duplicated 4× at slightly different y-coordinates → pdfminer interleaves them
        in y-order, producing an A A A B A B B C B C C D pattern. Consecutive dedup
        fails here because duplicates are separated by other lines.

     Both cases are handled by a sliding-window dedup: a line is suppressed if its
     content appeared anywhere in the preceding _DEDUP_WINDOW_SIZE lines.

  7. Legacy font name alias injection — PDFs from PageMaker / older InDesign embed
     font names without spaces (e.g. "TCRCYoutso") while pytiblegenc's conversion
     tables key on spaced names ("TCRC Youtso"). Without the alias the font is
     unrecognised and raw legacy encoding bytes pass straight through to the XML.
     The alias map is built dynamically from pytiblegenc's own loaded tables so it
     stays in sync if the package is updated.
     Affected font families: TCRC Youtso, TCRC Youtsoweb, TCRC Bod-Yig,
     Tibetisch dBu-can, Tibetisch dBu-can Overstrike (and any future spaced names).
"""

from __future__ import annotations

import logging
import os
import re
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
    from pytiblegenc import (
        get_glyph_db_path,
        build_font_hash_index_from_csv,
        identify_pdf_fonts_from_db,
        build_glyph_lookup_tables,
    )
    from pytiblegenc.pdfminer_text_converter import DuffedTextConverter
    from pytiblegenc.char_converter import get_base as _tibl_get_base, get_utfc_base as _tibl_get_utfc_base
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.pdfpage import PDFPage
    from io import StringIO
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False
    pdf_to_txt = None  # type: ignore

logger = logging.getLogger(__name__)

PAGE_BREAK_STR = "ZZZZ"
_FONT_SIZE_FORMAT = "<fs:{}>"

# ---------------------------------------------------------------------------
# Fix 7 — Legacy font name alias map
#
# Some authoring tools (PageMaker 7, older InDesign versions) embed Tibetan
# font names with spaces stripped: "TCRCYoutso" instead of "TCRC Youtso".
# pytiblegenc's convert_string() does an exact dict lookup on the font name,
# so "TCRCYoutso" is never found → the font lands in unhandled_fonts and raw
# legacy encoding bytes pass through unchanged.
#
# Fix: build a map of {stripped_name: canonical_table_name} from pytiblegenc's
# own loaded conversion tables, then inject it into font_normalization before
# each pytiblegenc extraction so the converter sees the right key.
#
# The map is built lazily at first use (avoids import-time cost) and cached.
# ---------------------------------------------------------------------------
_FONT_NAME_ALIASES: dict[str, str] | None = None


def _get_font_name_aliases() -> dict[str, str]:
    """
    Return {pdf_embedded_name: pytiblegenc_table_name} for all font names
    whose table key contains spaces (built from pytiblegenc's live tables).

    Result is cached in _FONT_NAME_ALIASES after the first call.
    """
    global _FONT_NAME_ALIASES
    if _FONT_NAME_ALIASES is not None:
        return _FONT_NAME_ALIASES
    if not PYTIBLEGENC_AVAILABLE:
        _FONT_NAME_ALIASES = {}
        return _FONT_NAME_ALIASES
    try:
        all_known: set[str] = set(_tibl_get_base().keys()) | set(_tibl_get_utfc_base().keys())
        _FONT_NAME_ALIASES = {
            name.replace(" ", ""): name
            for name in all_known
            if " " in name
        }
        logger.debug("Built font name alias map (%d entries): %s", len(_FONT_NAME_ALIASES), _FONT_NAME_ALIASES)
    except Exception as exc:
        logger.warning("Could not build font name alias map: %s", exc)
        _FONT_NAME_ALIASES = {}
    return _FONT_NAME_ALIASES


def create_cropped_pdf(
    pdf_path: Path, top_frac: float, bottom_frac: float
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

            if top_frac > 0.0:
                page.add_redact_annot(
                    fitz.Rect(r.x0, r.y0, r.x1, r.y0 + h * top_frac)
                )

            if bottom_frac > 0.0:
                page.add_redact_annot(
                    fitz.Rect(r.x0, r.y0 + h * (1.0 - bottom_frac), r.x1, r.y1)
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
) -> str:
    """
    Extract via pytiblegenc using the low-level API (DuffedTextConverter directly).

    Using the low-level API instead of ``pdf_to_txt`` lets us inject
    ``font_normalization`` overrides before conversion starts — which is required
    for Fix 7 (legacy font name alias injection).

    Optional ``crop_top`` / ``crop_bottom`` (fractions of page height) use
    ``create_cropped_pdf``.
    """
    logger.info(f"    Extracting (pytiblegenc low-level): {pdf_path.name}")

    if not PYTIBLEGENC_AVAILABLE:
        logger.error(
            "pytiblegenc is required for --extractor pytiblegenc. "
            "pip install git+https://github.com/buda-base/py-tiblegenc.git"
        )
        return ""

    tmp_pdf: Optional[Path] = None

    try:
        if crop_top > 0.0 or crop_bottom > 0.0:
            tmp_pdf = create_cropped_pdf(pdf_path, crop_top, crop_bottom)

        target_pdf = tmp_pdf if tmp_pdf else pdf_path

        # --- build font_normalization (glyph-hash based) ---
        font_normalization: dict = {}
        glyph_lookup = None
        try:
            glyph_db_path = get_glyph_db_path()
            glyph_index = build_font_hash_index_from_csv(str(glyph_db_path))
            with open(str(target_pdf), "rb") as _f:
                _parser = PDFParser(_f)
                _doc_tmp = PDFDocument(_parser)
                font_normalization = identify_pdf_fonts_from_db(_doc_tmp, glyph_index) or {}
            glyph_lookup = build_glyph_lookup_tables(str(glyph_db_path))
        except Exception as exc:
            logger.warning("Could not load font normalization or glyph lookup: %s", exc)

        # Fix 7: inject name-based aliases for fonts whose PDF-embedded name
        # differs from the pytiblegenc table name only by spaces being removed
        # (e.g. "TCRCYoutso" → "TCRC Youtso", "TCRCBod-Yig" → "TCRC Bod-Yig").
        # Only add an alias when the glyph-hash lookup did not already resolve it.
        for alias, canonical in _get_font_name_aliases().items():
            if alias not in font_normalization:
                font_normalization[alias] = {canonical}

        if font_normalization:
            logger.debug("font_normalization: %s", font_normalization)

        # --- run extraction ---
        stats: dict = {
            "unhandled_fonts": {},
            "handled_fonts": {},
            "unknown_characters": {},
            "error_characters": 0,
            "diffs_with_utfc": {},
            "nb_non_horizontal_removed": 0,
        }
        output_string = StringIO()

        with open(str(target_pdf), "rb") as in_file:
            parser = PDFParser(in_file)
            doc = PDFDocument(parser)
            rsrcmgr = PDFResourceManager()
            device = DuffedTextConverter(
                rsrcmgr,
                output_string,
                stats,
                region=None,
                pbs=f"\n{PAGE_BREAK_STR}\n",
                remove_non_hz=True,
                font_normalization=font_normalization,
                error_chr_fun=None,
                track_font_size=True,
                font_size_format=_FONT_SIZE_FORMAT,
                glyph_lookup=glyph_lookup,
            )
            interpreter = PDFPageInterpreter(rsrcmgr, device)
            for page in PDFPage.create_pages(doc):
                interpreter.process_page(page)

        text = output_string.getvalue()

        if stats["unhandled_fonts"]:
            logger.warning("Unhandled fonts (no conversion table): %s", stats["unhandled_fonts"])
        if stats["handled_fonts"]:
            logger.debug("Handled fonts: %s", stats["handled_fonts"])

        # Fix 6: sliding-window dedup for InDesign duplicate text layers
        text = _deduplicate_pytiblegenc_output(text, PAGE_BREAK_STR)

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


# ---------------------------------------------------------------------------
# Fix 1 & 4 — Phantom space detection
#
# Legacy Monlam/Dedris fonts encode combining marks (vowels, subscripts) as
# separate glyphs whose x-origin is shifted LEFT of the base character's
# advance position.  PyMuPDF materialises the resulting gap as a U+0020 space.
# Two sub-cases:
#
#   a) Negative advance   (subscripts): space_x < prev_x
#   b) Near-zero advance  (WinAnsi vowel spans corrected by Fix 2): the
#      corrected vowel and the space that follows share virtually the same
#      x (~0.2–0.3 pt difference — sub-pixel noise).
#
# Both are caught by: space_x < prev_x + THRESHOLD
# Real inter-word spaces always advance ≥ 4–5 pt, so they are never affected.
# ---------------------------------------------------------------------------
_PHANTOM_SPACE_ADVANCE_THRESHOLD = 1.5  # points


def _is_phantom_space(char_obj: dict, prev_char_obj: dict | None) -> bool:
    """
    Return True when *char_obj* is a phantom glyph-advance space.

    A space is phantom iff it does not advance rightward by at least
    ``_PHANTOM_SPACE_ADVANCE_THRESHOLD`` points from the preceding glyph.
    See module-level comment above for the full rationale.
    """
    if char_obj.get("c") != " ":
        return False
    if prev_char_obj is None:
        return False
    space_x = char_obj.get("origin", (0, 0))[0]
    prev_x = prev_char_obj.get("origin", (0, 0))[0]
    return space_x < prev_x + _PHANTOM_SPACE_ADVANCE_THRESHOLD


# ---------------------------------------------------------------------------
# Fix 2 — WinAnsi vowel glyph mis-mappings
#
# The WinAnsi-encoded instance of MonlamUniOuChan2 ships a broken ToUnicode
# table that maps Tibetan vowel glyph slots to Latin Extended codepoints.
# Verified by rasterising affected pages and comparing against extracted chars.
#
#   U+0140  ŀ  (l with middle dot)  →  U+0F7C  ོ  (Tibetan vowel sign O)
#   U+0132  Ĳ  (IJ digraph)         →  U+0F7A  ེ  (Tibetan vowel sign E)
#   U+0128  Ĩ  (I with tilde)       →  U+0F72  ི  (Tibetan vowel sign I)
# ---------------------------------------------------------------------------
_MONLAM_GLYPH_CORRECTIONS: dict[str, str] = {
    "\u0140": "\u0F7C",  # ŀ → ོ
    "\u0132": "\u0F7A",  # Ĳ → ེ
    "\u0128": "\u0F72",  # Ĩ → ི
}


def _correct_monlam_glyph(c: str) -> str:
    """Return the correct Tibetan character for a known Monlam WinAnsi mis-mapping."""
    return _MONLAM_GLYPH_CORRECTIONS.get(c, c)


def _extract_line_text(line: dict) -> list[str]:
    """
    Extract text fragments from a single MuPDF ``line`` dict.

    Returns a list of strings (font-size tags interleaved with text characters).
    Wingdings fonts are skipped entirely.

    Two Monlam/Dedris font artefacts are corrected:

    Fix 1+4 — **Phantom spaces**: glyph-advance gaps materialised as U+0020 are
    dropped when ``space_x < prev_x + _PHANTOM_SPACE_ADVANCE_THRESHOLD``.
    ``span_prev_char_obj`` is threaded *across span boundaries* within the same
    visual line (Fix 3) so that cross-span phantoms are also caught.

    Fix 2 — **WinAnsi vowel mis-mappings**: ŀ→ོ, Ĳ→ེ, Ĩ→ི via
    ``_correct_monlam_glyph``.
    """
    fragments: list[str] = []
    # Thread prev char across span boundaries so cross-span phantom spaces
    # (Fix 3) are detected correctly.
    span_prev_char_obj: dict | None = None

    for span in line.get("spans", []):
        if _is_wingdings_font(span.get("font") or ""):
            continue
        fs = round(span.get("size", 12))
        fragments.append(_FONT_SIZE_FORMAT.format(fs))
        char_objs = span.get("chars") or []
        if char_objs:
            for char_obj in char_objs:
                # Fix 1+3+4: drop phantom glyph-advance spaces
                if _is_phantom_space(char_obj, span_prev_char_obj):
                    # Do NOT update span_prev_char_obj — phantom is invisible
                    continue
                # Fix 2: correct WinAnsi vowel mis-mappings
                c = _correct_monlam_glyph(char_obj.get("c", ""))
                fragments.append(c)
                span_prev_char_obj = char_obj
        else:
            fragments.append(span.get("text") or "")
            span_prev_char_obj = None  # no char-level position info available

    return fragments


# ---------------------------------------------------------------------------
# Fix 5 — Duplicate text-layer deduplication
#
# Some InDesign / Acrobat-generated PDFs place every visual line twice in the
# content stream at identical coordinates (same y_mid, same x0, same text).
# Without deduplication both copies land in the same merged visual row and
# their fragments are emitted twice, producing verbatim repeated text.
#
# Strategy: after collecting raw_lines, remove any entry whose (y_bucket, x0,
# text) key has already been seen.  y_bucket is y_mid rounded to the nearest
# _Y_MERGE_TOLERANCE step so sub-pixel y differences between copies don't
# defeat the check.  text_key strips font-size tags before comparison.
# ---------------------------------------------------------------------------
_FS_TAG_RE = re.compile(r"<fs:\d+>")


def _deduplicate_raw_lines(
    raw_lines: list[tuple[float, float, list[str]]],
    y_tolerance: float,
) -> list[tuple[float, float, list[str]]]:
    """
    Remove duplicate raw lines produced by PDFs with overlapping text layers.

    Keeps the first occurrence of each (y_bucket, x0_rounded, text_key) triple.
    See module-level Fix 5 comment for full rationale.
    """
    seen: set[tuple[float, float, str]] = set()
    deduped: list[tuple[float, float, list[str]]] = []

    for y_mid, x0, frags in raw_lines:
        y_bucket = round(y_mid / y_tolerance) * y_tolerance
        x_bucket = round(x0, 1)
        text_key = _FS_TAG_RE.sub("", "".join(frags))

        key = (y_bucket, x_bucket, text_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((y_mid, x0, frags))

    return deduped


# Tolerance in points for treating two MuPDF lines as the same visual row.
# Tibetan glyphs with vowel marks can cause small Y shifts across spans.
_Y_MERGE_TOLERANCE = 3.0


# ---------------------------------------------------------------------------
# Fix 6 — pytiblegenc duplicate-line deduplication
#
# InDesign PDFs printed through PScript5.dll / Acrobat Distiller embed every
# text line twice in the content stream at exactly the same coordinates. The
# PyMuPDF rawdict path catches this via _deduplicate_raw_lines (Fix 5), but
# pytiblegenc.pdf_to_txt renders both copies and emits them as consecutive
# identical lines separated by a single newline. The page-break marker
# (PAGE_BREAK_STR) is the only guaranteed non-text separator.
#
# Strategy: split the raw output into per-page chunks, then within each chunk
# remove any line that is identical to the immediately preceding non-empty
# line. This is conservative — it only removes a line when it is *adjacent*
# and *identical*, so legitimately repeated lines separated by other content
# (e.g. a refrain that genuinely appears twice in a verse) are kept.
#
# Font-size tags (<fs:N>) are stripped before comparison so that a line whose
# only difference from its predecessor is a tag variant is still detected as
# a duplicate.
# ---------------------------------------------------------------------------
_FS_TAG_RE_TIBL = re.compile(r"<fs:\d+>")

# How many preceding lines to look back when checking for duplicates.
# Must be large enough to span the interleaving gap in the 4× drop-shadow pattern
# (gap between first and last copy of a line ≈ 3×(unique_lines_per_group) ≈ 3–15 lines)
# but small enough not to suppress legitimately repeated text in verse/prose.
# 16 covers the worst observed case (4 lines × 4 copies = 16 entries) with margin.
_DEDUP_WINDOW_SIZE = 16


def _deduplicate_pytiblegenc_output(text: str, page_break_str: str) -> str:
    """
    Remove duplicate lines from pytiblegenc ``pdf_to_txt`` output using a sliding window.

    Each page is processed independently (page-break markers are never removed).
    Within a page, a line is suppressed when its content — after stripping font-size
    tags — is non-empty and has already appeared in the preceding
    ``_DEDUP_WINDOW_SIZE`` non-empty lines.

    This handles two distinct InDesign duplication patterns:

    * **2× consecutive** (PScript5/Acrobat Distiller): pdfminer emits identical
      pairs ``A A B B …`` — caught trivially by window ≥ 1.

    * **4× interleaved** (Adobe PDF Library drop-shadow): pdfminer sorts all four
      copies by y-coordinate, yielding ``A A A B A B B C B C C D …`` — the third
      copy of A is separated from the first by up to ``window-1`` other lines.
      A window of 16 safely covers all observed cases.

    The window resets between pages so it never suppresses text that legitimately
    recurs across a page boundary (running headers handled separately by
    ``strip_page_header_artifacts``).
    """
    pages = text.split(f"\n{page_break_str}\n")
    deduped_pages = []

    for page_text in pages:
        lines = page_text.split("\n")
        result_lines: list[str] = []
        # Sliding window: a deque of the last _DEDUP_WINDOW_SIZE non-empty keys.
        recent: list[str] = []

        for line in lines:
            key = _FS_TAG_RE_TIBL.sub("", line).strip()
            if key and key in recent:
                # This line appeared in the recent window — drop as duplicate.
                continue
            result_lines.append(line)
            if key:
                recent.append(key)
                if len(recent) > _DEDUP_WINDOW_SIZE:
                    recent.pop(0)

        deduped_pages.append("\n".join(result_lines))

    return f"\n{page_break_str}\n".join(deduped_pages)


def extract_pdf_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
) -> str:
    """
    Extract text using PyMuPDF ``rawdict``: one ``\\n`` per **visual** line.

    MuPDF often splits a single visual line into multiple ``line`` objects
    (e.g. at a Tibetan shad ``།``).  We merge lines whose vertical midpoints
    are within ``_Y_MERGE_TOLERANCE`` points of each other, then sort left-
    to-right so the reading order is preserved.

    All five Monlam/InDesign artefact fixes are applied here — see the
    module-level docstring for a summary.
    """
    logger.info(f"    Extracting (PyMuPDF rawdict): {pdf_path.name}")

    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF is required for --extractor pymupdf. pip install pymupdf")
        return ""

    tmp_pdf: Optional[Path] = None

    try:
        if crop_top > 0.0 or crop_bottom > 0.0:
            tmp_pdf = create_cropped_pdf(pdf_path, crop_top, crop_bottom)

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

            # Fix 5: remove duplicate lines from overlapping PDF text layers.
            if raw_lines:
                raw_lines = _deduplicate_raw_lines(raw_lines, _Y_MERGE_TOLERANCE)

            # Sort by vertical position first, then left-to-right.
            raw_lines.sort(key=lambda t: (t[0], t[1]))

            # Merge lines that share (approximately) the same Y midpoint.
            merged_rows: list[list[tuple[float, float, list[str]]]] = []
            for y_mid, x0, frags in raw_lines:
                if merged_rows:
                    avg_y = sum(e[0] for e in merged_rows[-1]) / len(merged_rows[-1])
                    if abs(y_mid - avg_y) <= _Y_MERGE_TOLERANCE:
                        merged_rows[-1].append((y_mid, x0, frags))
                        continue
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
) -> str:
    """Dispatch to PyMuPDF or pytiblegenc."""
    if extractor == "pytiblegenc":
        return extract_pdf_pytiblegenc(
            pdf_path, crop_top=crop_top, crop_bottom=crop_bottom
        )
    return extract_pdf_pymupdf(
        pdf_path, crop_top=crop_top, crop_bottom=crop_bottom
    )