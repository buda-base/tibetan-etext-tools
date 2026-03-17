#!/usr/bin/env python3
"""
Convert PDF files to TEI XML format.
note : it handles non-selectable text
This script implements a multi-phase pipeline for extracting text from PDFs
(including Tibetan Unicode PDFs) and producing well-structured TEI XML output.

Pipeline:
  1. Extract positioned glyphs using pdfminer.six (preserves font size and bbox)
  2. Decode glyphs → Unicode (ToUnicode CMap → font cmap via fontTools → shape fallback)
  3. Reconstruct layout: blocks → lines → clusters
  4. Assemble Unicode strings per line
  5. Normalize Unicode (via normalization.py)
  6. Classify font sizes (large / regular / small) by character volume
  7. Apply font markup and convert to TEI XML

Requirements:
    pip install pdfminer.six fonttools

Usage:
    python pdf_to_tei_xml.py <input_pdf_or_folder> <output_folder> [options]

Examples:
    # Convert a single PDF
    python pdf_to_tei_xml.py mybook.pdf ./output

    # Convert all PDFs in a folder
    python pdf_to_tei_xml.py ./pdf_folder ./output

    # With crop box to remove headers/footers (x0,y0,x1,y1 in PDF points)
    python pdf_to_tei_xml.py mybook.pdf ./output --crop 50,60,550,740

"""

import sys
import os
import re
import hashlib
import argparse
import shutil
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional

# ── Optional heavy imports (fail gracefully) ──────────────────────────────────
try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTPage, LTTextBox, LTTextLine, LTImage, LTFigure
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams
    HAS_PDFMINER = True
except ImportError:
    HAS_PDFMINER = False
    print("Warning: pdfminer.six not found. Install with: pip install pdfminer.six")

try:
    from fontTools.ttLib import TTFont
    HAS_FONTTOOLS = True
except ImportError:
    HAS_FONTTOOLS = False

# normalization.py must live in the same directory (or be importable)
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from normalization import normalize_unicode
except ImportError:
    def normalize_unicode(s, **kw):
        """Fallback no-op when normalization.py is unavailable."""
        import unicodedata
        return unicodedata.normalize("NFC", s)

try:
    from tibetan_text_fixes import fix_tibetan_mark_order
except ImportError:
    def fix_tibetan_mark_order(text: str) -> str:
        """Fallback no-op when tibetan_text_fixes.py is unavailable."""
        return text

# ── Constants ─────────────────────────────────────────────────────────────────
PAGE_BREAK_STR  = "ZZZZ"
EMPTY_PAGE_STR  = "YYYY"   # sentinel for pages with no selectable text
BLANK_PAGE_STR  = "WWWW"   # sentinel for pages with no text and no visible objects
UNREADABLE_LINE_STR = "XXXX_UNREADABLE_LINE_XXXX"  # line with likely unextractable text
FONT_SIZE_FORMAT = "<fs:{}>"

# Confidence levels for glyph→Unicode mapping
CONF_HIGH   = "high"    # ToUnicode CMap
CONF_MEDIUM = "medium"  # embedded font cmap via fontTools
CONF_LOW    = "low"     # shape-based fallback


# =============================================================================
# Phase 1 – Raw Glyph Extraction  (pdfminer.six)
# =============================================================================

class GlyphInfo:
    """Lightweight container for a single positioned glyph."""
    __slots__ = ("pdf_code", "fontname", "fontsize", "bbox",
                 "unicode_char", "confidence")

    def __init__(self, pdf_code, fontname, fontsize, bbox,
                 unicode_char="", confidence=CONF_HIGH):
        self.pdf_code     = pdf_code
        self.fontname     = fontname
        self.fontsize     = fontsize
        self.bbox         = bbox          # (x0, y0, x1, y1)
        self.unicode_char = unicode_char
        self.confidence   = confidence


def _extract_glyphs_pdfminer(pdf_path: Path,
                              crop: Optional[tuple] = None
                              ) -> list[list[GlyphInfo]]:
    """
    Extract raw glyphs page-by-page using pdfminer.six.

    Returns a list of pages; each page is a flat list of GlyphInfo.
    Reading order is NOT assumed – layout is reconstructed in Phase 3.
    """
    pages_glyphs: list[list[GlyphInfo]] = []
    laparams = LAParams(all_texts=True, detect_vertical=False)
    rsrcmgr  = PDFResourceManager()
    device   = PDFPageAggregator(rsrcmgr, laparams=laparams)
    interp   = PDFPageInterpreter(rsrcmgr, device)

    with open(pdf_path, "rb") as fh:
        for page_obj in PDFPage.get_pages(fh):
            interp.process_page(page_obj)
            layout = device.get_result()
            glyphs: list[GlyphInfo] = []
            crop_points = None

            if crop:
                cx0, cy0, cx1, cy1 = crop
                normalized_crop = all(0.0 <= v <= 1.0 for v in (cx0, cy0, cx1, cy1))
                if normalized_crop:
                    # Support percentage-style crop values relative to page size.
                    mb = page_obj.mediabox
                    px0 = float(mb[0])
                    py0 = float(mb[1])
                    px1 = float(mb[2])
                    py1 = float(mb[3])
                    pw = px1 - px0
                    ph = py1 - py0
                    crop_points = (
                        px0 + (cx0 * pw),
                        py0 + (cy0 * ph),
                        px0 + (cx1 * pw),
                        py0 + (cy1 * ph),
                    )
                else:
                    crop_points = crop

            def _walk(element):
                if isinstance(element, LTChar):
                    bbox = element.bbox  # (x0,y0,x1,y1) in PDF user space
                    text = element.get_text()
                    if not text:
                        return
                    # Apply crop box filter
                    if crop_points:
                        cx0, cy0, cx1, cy1 = crop_points
                        if not (cx0 <= element.bbox[0] and
                                element.bbox[2] <= cx1 and
                                cy0 <= element.bbox[1] and
                                element.bbox[3] <= cy1):
                            return
                    # Some PDFs map a single positioned glyph to multi-char text;
                    # split safely instead of crashing on ord().
                    chars = text if len(text) > 1 else (text[0],)
                    for ch in chars:
                        g = GlyphInfo(
                            pdf_code     = ord(ch),
                            fontname     = element.fontname,
                            fontsize     = element.size,
                            bbox         = bbox,
                            unicode_char = ch if len(text) > 1 else "",
                            confidence   = CONF_HIGH,
                        )
                        glyphs.append(g)
                elif hasattr(element, "__iter__"):
                    for child in element:
                        _walk(child)

            _walk(layout)
            pages_glyphs.append(glyphs)

    device.close()
    return pages_glyphs


def extract_glyphs(pdf_path: Path,
                   crop: Optional[tuple] = None
                   ) -> list[list[GlyphInfo]]:
    """Extract raw glyphs page-by-page using pdfminer.six."""
    if not HAS_PDFMINER:
        raise RuntimeError(
            "pdfminer.six is required. Install with: pip install pdfminer.six")
    return _extract_glyphs_pdfminer(pdf_path, crop=crop)


def _extract_page_content_stats(pdf_path: Path,
                                crop: Optional[tuple] = None
                                ) -> list[dict]:
    """
    Collect per-page object stats to distinguish truly blank pages from
    non-selectable/image pages.
    """
    if not HAS_PDFMINER:
        raise RuntimeError(
            "pdfminer.six is required. Install with: pip install pdfminer.six")

    stats: list[dict] = []
    laparams = LAParams(all_texts=True, detect_vertical=False)

    for lt_page in extract_pages(str(pdf_path), laparams=laparams):
        px0, py0, px1, py1 = lt_page.bbox
        crop_points = None
        if crop:
            cx0, cy0, cx1, cy1 = crop
            normalized_crop = all(0.0 <= v <= 1.0 for v in (cx0, cy0, cx1, cy1))
            if normalized_crop:
                pw = px1 - px0
                ph = py1 - py0
                crop_points = (
                    px0 + (cx0 * pw),
                    py0 + (cy0 * ph),
                    px0 + (cx1 * pw),
                    py0 + (cy1 * ph),
                )
            else:
                crop_points = crop

        page_stats = {"text_chars": 0, "images": 0, "figures": 0}

        def _in_crop(bbox) -> bool:
            if not crop_points:
                return True
            cx0, cy0, cx1, cy1 = crop_points
            x0, y0, x1, y1 = bbox
            return (cx0 <= x0 and x1 <= cx1 and cy0 <= y0 and y1 <= cy1)

        def _walk(element):
            if isinstance(element, LTChar):
                if _in_crop(element.bbox):
                    text = element.get_text() or ""
                    page_stats["text_chars"] += sum(1 for ch in text if not ch.isspace())
            elif isinstance(element, LTImage):
                if _in_crop(element.bbox):
                    page_stats["images"] += 1
            elif isinstance(element, LTFigure):
                if _in_crop(element.bbox):
                    page_stats["figures"] += 1

            if hasattr(element, "__iter__"):
                for child in element:
                    _walk(child)

        _walk(lt_page)
        stats.append(page_stats)

    return stats


# =============================================================================
# Phase 2 – Glyph → Unicode Decoding
# =============================================================================

# Cache font cmap lookups to avoid repeated I/O
_FONT_CMAP_CACHE: dict[str, dict] = {}


def _load_embedded_cmap(fontname: str, pdf_path: Path) -> dict:
    """
    Attempt to extract and parse an embedded font's cmap using fontTools.
    Returns a dict: {glyph_id_or_name: unicode_char}.
    """
    if not HAS_FONTTOOLS:
        return {}
    key = f"{pdf_path}::{fontname}"
    if key in _FONT_CMAP_CACHE:
        return _FONT_CMAP_CACHE[key]

    cmap: dict = {}
    try:
        # pdfminer exposes font objects; here we try a heuristic path
        import pdfminer.pdfdocument as pdfdoc
        import pdfminer.pdfparser as pdfparser
        import io, tempfile

        with open(pdf_path, "rb") as fh:
            parser = pdfparser.PDFParser(fh)
            doc    = pdfdoc.PDFDocument(parser)
            # Walk XRef to find font streams with matching BaseFont name
            for xref in doc.xrefs:
                for objid in xref.get_objids():
                    try:
                        obj = doc.getobj(objid)
                        if not isinstance(obj, dict):
                            continue
                        if obj.get("Type") == "/Font":  # noqa – intentional typo guard
                            pass
                        if (obj.get("Subtype") in (b"TrueType", "TrueType",
                                                    b"CIDFontType2", "CIDFontType2")
                                and obj.get("BaseFont", "").lstrip("/") == fontname):
                            fd = obj.get("FontDescriptor", {})
                            ff = (fd.get("FontFile2") or fd.get("FontFile3"))
                            if ff:
                                data = ff.get_data()
                                with tempfile.NamedTemporaryFile(
                                        suffix=".ttf", delete=False) as tmp:
                                    tmp.write(data)
                                    tmp_path = tmp.name
                                tt = TTFont(tmp_path)
                                for table in tt["cmap"].tables:
                                    for gid, ucp in table.cmap.items():
                                        cmap[gid] = chr(ucp)
                                os.unlink(tmp_path)
                                break
                    except Exception:
                        continue
    except Exception:
        pass

    _FONT_CMAP_CACHE[key] = cmap
    return cmap


def decode_glyphs(pages_glyphs: list[list[GlyphInfo]],
                  pdf_path: Path
                  ) -> list[list[GlyphInfo]]:
    """
    Phase 2: Assign unicode_char + confidence to every GlyphInfo.

    Priority:
      1. pdfminer raw code point is the correct Unicode scalar when the PDF
         has a valid ToUnicode CMap – accept directly for Tibetan/Latin/CJK.
      2. Try embedded font cmap via fontTools (medium confidence).
      3. Shape-based fallback (placeholder – extend as needed).
    """
    for page in pages_glyphs:
        for g in page:
            cp = g.pdf_code
            ch = chr(cp) if 0 < cp < 0x110000 else ""

            # Heuristic: if the code point is a printable Tibetan / Latin /
            # Arabic-numeral character it's very likely already Unicode.
            if ch and (
                (0x0F00 <= cp <= 0x0FFF) or   # Tibetan block
                (0x0020 <= cp <= 0x007E) or   # Basic Latin printable
                (0x4E00 <= cp <= 0x9FFF) or   # CJK Unified Ideographs
                (0x0900 <= cp <= 0x097F)       # Devanagari
            ):
                g.unicode_char = ch
                g.confidence   = CONF_HIGH
                continue

            # Try embedded font cmap (medium confidence)
            if HAS_FONTTOOLS and HAS_PDFMINER:
                cmap = _load_embedded_cmap(g.fontname, pdf_path)
                if cp in cmap:
                    g.unicode_char = cmap[cp]
                    g.confidence   = CONF_MEDIUM
                    continue

            # Shape-based fallback placeholder
            # Future: compare glyph outline against glyph_db
            g.confidence = CONF_LOW
            g.unicode_char = ch or "?"

    return pages_glyphs


# =============================================================================
# Phase 3 – Layout Reconstruction
# =============================================================================

def _bbox_center(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _group_into_lines(glyphs: list[GlyphInfo],
                      line_tolerance_factor: float = 0.6
                      ) -> list[list[GlyphInfo]]:
    """
    Group glyphs into lines using vertical overlap / proximity.

    line_tolerance_factor * avg_fontsize  defines the y-band radius.
    Returns a list of lines, each line sorted left-to-right (ascending x).
    """
    if not glyphs:
        return []

    # Sort by descending y-center (top of page first in PDF coords where y=0 is bottom)
    glyphs_sorted = sorted(glyphs, key=lambda g: -_bbox_center(g.bbox)[1])

    lines: list[list[GlyphInfo]] = []
    current_line: list[GlyphInfo] = []
    current_y    = None

    for g in glyphs_sorted:
        cy = _bbox_center(g.bbox)[1]
        tol = g.fontsize * line_tolerance_factor

        if current_y is None or abs(cy - current_y) <= tol:
            current_line.append(g)
            # Running average of the line's y-center
            current_y = sum(_bbox_center(gg.bbox)[1]
                            for gg in current_line) / len(current_line)
        else:
            # New line
            current_line.sort(key=lambda gg: gg.bbox[0])
            lines.append(current_line)
            current_line = [g]
            current_y    = cy

    if current_line:
        current_line.sort(key=lambda gg: gg.bbox[0])
        lines.append(current_line)

    return lines


def _remove_duplicate_glyphs(glyphs: list[GlyphInfo],
                              pos_tolerance: float = 1.0
                              ) -> list[GlyphInfo]:
    """Remove glyphs at nearly identical positions (PDF duplicate rendering)."""
    seen: list[tuple] = []
    result: list[GlyphInfo] = []
    for g in glyphs:
        cx, cy = _bbox_center(g.bbox)
        is_dup = any(
            abs(cx - sx) < pos_tolerance and
            abs(cy - sy) < pos_tolerance and
            g.unicode_char == sc
            for sx, sy, sc in seen
        )
        if not is_dup:
            seen.append((cx, cy, g.unicode_char))
            result.append(g)
    return result


def reconstruct_layout(page_glyphs: list[GlyphInfo]
                       ) -> list[list[GlyphInfo]]:
    """
    Phase 3: Turn a flat list of page glyphs into ordered lines.
    """
    clean = _remove_duplicate_glyphs(page_glyphs)
    lines = _group_into_lines(clean)
    return lines


# =============================================================================
# Phase 4-6 – Line → Text String Assembly + Font-size Tagging
# =============================================================================

def _line_to_tagged_text(line: list[GlyphInfo]) -> str:
    """
    Convert a single reconstructed line to a font-size-tagged string.

    Format:  <fs:12>text content here
    Multiple font sizes within a line produce multiple tags.
    """
    if not line:
        return ""

    segments: list[tuple[int, str]] = []  # (rounded_fs, char)
    for g in line:
        if not g.unicode_char or g.unicode_char in ("\x00",):
            continue
        fs = max(1, round(g.fontsize))
        segments.append((fs, g.unicode_char))

    if not segments:
        return ""

    # Merge consecutive same-fontsize chars
    result  = []
    cur_fs  = segments[0][0]
    cur_buf = segments[0][1]

    for fs, ch in segments[1:]:
        if fs == cur_fs:
            cur_buf += ch
        else:
            result.append(f"<fs:{cur_fs}>{cur_buf}")
            cur_fs  = fs
            cur_buf = ch

    result.append(f"<fs:{cur_fs}>{cur_buf}")
    return "".join(result)


def _strip_fs_tags(text: str) -> str:
    """Drop internal font-size markers, leaving only extracted characters."""
    return re.sub(r"<fs:\d+>", "", text)


def _is_unreadable_line(text_with_fs: str) -> bool:
    """
    Heuristic: detect lines that are mostly spaces with too few visible chars.
    Such lines are often produced where PDF glyph mapping is broken.
    """
    plain = _strip_fs_tags(text_with_fs)
    if not plain:
        return False
    total = len(plain)
    space_count = sum(1 for ch in plain if ch.isspace())
    non_space = total - space_count
    if non_space == 0:
        return True
    # Keep thresholds conservative to avoid masking valid sparse text lines.
    if total >= 6 and (space_count / total) >= 0.80 and non_space <= 4:
        return True
    if total >= 4 and non_space <= 1:
        return True
    return False


def _is_processing_error_page(lines: list[str]) -> bool:
    """
    Decide whether a non-empty page is effectively unextractable.

    This catches pages where layout detection produced many line breaks but most
    lines are unreadable placeholders and only tiny text fragments survived.
    """
    if not lines:
        return True

    unreadable_count = sum(1 for l in lines if l == UNREADABLE_LINE_STR)
    readable_lines = [l for l in lines if l != UNREADABLE_LINE_STR]

    if not readable_lines:
        return True

    meaningful_chars = 0
    for line in readable_lines:
        plain = _strip_fs_tags(line)
        meaningful_chars += sum(
            1 for ch in plain
            if (
                ("\u0F00" <= ch <= "\u0FFF") or   # Tibetan
                ("A" <= ch <= "Z") or ("a" <= ch <= "z") or
                ("0" <= ch <= "9")
            )
        )

    total_lines = len(lines)
    unreadable_ratio = unreadable_count / total_lines if total_lines else 0.0

    # Conservative threshold for severe extraction failure:
    # many unreadable lines + very little meaningful text.
    if unreadable_count >= 4 and unreadable_ratio >= 0.50 and meaningful_chars <= 30:
        return True

    # Common partial-failure shape seen in some Tibetan PDFs:
    # short pages dominated by unreadable placeholders with only tiny fragments.
    if (unreadable_count >= 3 and total_lines <= 8 and
            len(readable_lines) <= 4 and meaningful_chars <= 30):
        return True

    # Aggressive fallback for highly fragmented pages where extraction yields
    # many placeholders and sparse broken snippets (requested special case).
    if (unreadable_count >= 3 and unreadable_ratio >= 0.30 and total_lines <= 12 and
            len(readable_lines) <= 7 and meaningful_chars <= 120):
        return True
    return False


def pages_to_tagged_text(pages_glyphs: list[list[GlyphInfo]],
                         page_stats: Optional[list[dict]] = None) -> str:
    """
    Convert all pages to a single font-size-tagged text string.

    Pages are separated by PAGE_BREAK_STR; lines by newlines.
    Pages that yield no selectable text (image-only / non-selectable Tibetan)
    are represented by EMPTY_PAGE_STR so the TEI converter can emit the
    appropriate <gap reason="processing-error"> element.
    """
    page_texts: list[str] = []

    for page_idx, page in enumerate(pages_glyphs):
        lines = reconstruct_layout(page)
        line_texts: list[str] = []
        for line in lines:
            tagged = _line_to_tagged_text(line)
            if not tagged:
                continue
            plain = _strip_fs_tags(tagged)
            if not plain.strip():
                # Preserve suspicious blank-looking extracted lines as explicit gaps.
                if not line_texts or line_texts[-1] != UNREADABLE_LINE_STR:
                    line_texts.append(UNREADABLE_LINE_STR)
                continue
            if _is_unreadable_line(tagged):
                if not line_texts or line_texts[-1] != UNREADABLE_LINE_STR:
                    line_texts.append(UNREADABLE_LINE_STR)
                continue
            line_texts.append(tagged)
        if line_texts:
            if _is_processing_error_page(line_texts):
                page_texts.append(EMPTY_PAGE_STR)
                continue
            page_texts.append("\n".join(line_texts))
        else:
            # Distinguish truly blank pages from unextractable/image pages.
            stats = page_stats[page_idx] if (page_stats and page_idx < len(page_stats)) else None
            if stats and stats["text_chars"] == 0 and stats["images"] == 0 and stats["figures"] == 0:
                page_texts.append(BLANK_PAGE_STR)
            else:
                page_texts.append(EMPTY_PAGE_STR)

    return f"\n{PAGE_BREAK_STR}\n".join(page_texts)


# =============================================================================
# Post-extraction Cleanup  (ported & generalised from pdf_to_xml.py)
# =============================================================================

def remove_headers_footers(text: str) -> str:
    """
    Dynamically detect and strip repeated headers, footers, and page numbers.
    Works on any PDF; no hard-coded strings required.
    """
    pages = text.split(f"\n{PAGE_BREAK_STR}\n")
    first_lines: list[str] = []
    last_lines:  list[str] = []

    for page in pages:
        lines = [l for l in page.split("\n") if l.strip()]
        if lines:
            first_lines.append(re.sub(r"<fs:\d+>", "", lines[0]).strip())
            last_lines.append( re.sub(r"<fs:\d+>", "", lines[-1]).strip())

    threshold  = max(3, len(pages) * 0.2)
    rep_heads  = {l for l, c in Counter(first_lines).items()
                  if c >= threshold and len(l) > 2}
    rep_foots  = {l for l, c in Counter(last_lines).items()
                  if c >= threshold and len(l) > 2}

    def _is_hf(line: str, rep: set) -> bool:
        clean = re.sub(r"<fs:\d+>", "", line).strip()
        if re.match(r"^[\d\s\u0F20-\u0F29]+$", clean):
            return True
        if clean in rep:
            return True
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}", clean):
            return True
        return False

    cleaned_pages: list[str] = []
    for page in pages:
        lines = page.split("\n")
        # Strip blank edges
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            cleaned_pages.append("")
            continue
        if lines and _is_hf(lines[0],  rep_heads): lines.pop(0)
        if lines and _is_hf(lines[-1], rep_foots): lines.pop()
        cleaned_pages.append("\n".join(lines))

    return f"\n{PAGE_BREAK_STR}\n".join(cleaned_pages)


def remove_indesign_artifacts(text: str) -> str:
    """Strip lines containing Adobe InDesign artefacts."""
    return "\n".join(l for l in text.split("\n")
                     if ".indd" not in l.lower())


# =============================================================================
# Font-size Simplification  (from pdf_to_xml.py, generalised)
# =============================================================================

def simplify_font_sizes(text: str) -> str:
    """
    Merge adjacent <fs:N> spans that carry no Tibetan separator (་ / །) to
    eliminate spurious font-size changes inside a single word/syllable.
    """
    pattern = r"<fs:(\d+)>"
    parts   = re.split(pattern, text)

    segments: list[tuple] = []
    cur_fs = None
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part:
                segments.append((cur_fs, part))
        else:
            cur_fs = part

    if not segments:
        return text

    merged: list[tuple] = []
    for fs, content in segments:
        has_sep = "་" in content or "།" in content
        if not has_sep and merged:
            prev_fs, prev_c = merged[-1]
            merged[-1] = (prev_fs, prev_c + content)
        else:
            merged.append((fs, content))

    # Collapse consecutive same-fs spans
    final: list[tuple] = []
    for fs, content in merged:
        if final and final[-1][0] == fs:
            final[-1] = (fs, final[-1][1] + content)
        else:
            final.append((fs, content))

    return "".join(
        (f"<fs:{fs}>{c}" if fs is not None else c)
        for fs, c in final
    )


# =============================================================================
# Font-size Classification
# =============================================================================

def classify_font_sizes(text: str) -> dict:
    """
    Classify font sizes purely by total character volume.
    The most-used size is 'regular'; larger → 'large'; smaller → 'small'.
    """
    pattern = r"<fs:(\d+)>([^<]*)"
    matches = re.findall(pattern, text)
    if not matches:
        return {}

    size_counts: Counter = Counter()
    for fs, content in matches:
        n = len([c for c in content if
                 (0x0F00 <= ord(c) <= 0x0FFF) or
                 (0x0041 <= ord(c) <= 0x007A) or
                 (0x4E00 <= ord(c) <= 0x9FFF)])
        if n > 0:
            size_counts[int(fs)] += n

    if not size_counts:
        return {}

    dominant = max(size_counts, key=lambda k: size_counts[k])
    return {
        fs: ("regular" if fs == dominant
             else "large"   if fs > dominant
             else "small")
        for fs in size_counts
    }


def apply_font_markup(text: str, classifications: dict) -> str:
    """Replace <fs:N> with <large>/<small> wrappers; strip unknown sizes."""

    def _tag(m):
        fs   = int(m.group(1))
        cls  = classifications.get(fs, "regular")
        return {"large": "<LARGE_START>",
                "small": "<SMALL_START>"}.get(cls, "<REGULAR_START>")

    text  = re.sub(r"<fs:(\d+)>", _tag, text)
    parts = re.split(r"(<(?:LARGE|SMALL|REGULAR)_START>)", text)

    result  = []
    state   = "regular"
    CLOSE   = {"large": "</large>", "small": "</small>"}
    OPEN    = {"large": "<large>",  "small": "<small>"}
    TAG_MAP = {
        "<LARGE_START>":   "large",
        "<SMALL_START>":   "small",
        "<REGULAR_START>": "regular",
    }

    for part in parts:
        if part in TAG_MAP:
            new = TAG_MAP[part]
            if state in CLOSE and state != new:
                result.append(CLOSE[state])
            if new in OPEN and new != state:
                result.append(OPEN[new])
            state = new
        else:
            result.append(part)

    if state in CLOSE:
        result.append(CLOSE[state])

    text = "".join(result)
    # Tidy up whitespace around inline tags
    text = re.sub(r"(<(?:large|small)>)(\s)",  r"\2\1", text)
    text = re.sub(r"(\s)(</(?:large|small)>)", r"\2\1", text)
    text = re.sub(r"<large></large>",   "", text)
    text = re.sub(r"<small></small>",   "", text)
    return text


# =============================================================================
# TEI XML Generation
# =============================================================================

def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def convert_markup_to_tei(text: str) -> str:
    """
    Convert internal markup to TEI elements.

    Mapping:
      <large>        → <hi rend="head">
      <small>        → <hi rend="small">
      newlines       → <lb/>
      PAGE_BREAK_STR → <pb/>
      BLANK_PAGE_STR      → no gap element (page break only)
      EMPTY_PAGE_STR      → <pb/><gap reason="processing-error" extent="1 page">…</gap>
                            (emitted for pages where no selectable text was found)
      UNREADABLE_LINE_STR → <gap reason="unextractable-text" extent="1 line"/>
                            (line looked present in layout but text extraction failed)
    """
    # Protect our markup tags, then XML-escape everything else
    SENTINEL = {
        "<large>":  "\x00LARGE\x00",
        "</large>": "\x00/LARGE\x00",
        "<small>":  "\x00SMALL\x00",
        "</small>": "\x00/SMALL\x00",
    }
    for tag, ph in SENTINEL.items():
        text = text.replace(tag, ph)

    text = _escape_xml(text)

    for tag, ph in SENTINEL.items():
        text = text.replace(ph, tag)          # restore markup

    # Handle empty (non-selectable / image-only) pages.
    # pages_to_tagged_text() marks them with EMPTY_PAGE_STR.
    # Replace each such sentinel with a TEI processing-error gap so it
    # survives the rest of the conversion as a literal XML fragment.
    GAP_ELEMENT = (
        '<gap reason="processing-error" extent="1 page">'
        "<desc>Text extraction from PDF failed.</desc></gap>"
    )
    UNREADABLE_LINE_GAP = '<gap reason="unextractable-text" extent="1 line"/>'
    text = re.sub(
        r"(?:^|\n)" + re.escape(BLANK_PAGE_STR) + r"(?:\n|$)",
        "\n<<<BLANK_PAGE>>>\n",
        text,
    )
    text = re.sub(
        r"(?:^|\n)" + re.escape(EMPTY_PAGE_STR) + r"(?:\n|$)",
        "\n<<<EMPTY_PAGE>>>\n",
        text,
    )
    text = re.sub(
        r"(?:^|\n)" + re.escape(UNREADABLE_LINE_STR) + r"(?:\n|$)",
        "\n<<<UNREADABLE_LINE>>>\n",
        text,
    )

    # Leading page-break cleanup
    text = re.sub(r"^\n?" + re.escape(PAGE_BREAK_STR) + r"\n?", "", text)

    text = re.sub(re.escape(PAGE_BREAK_STR), "<<<PB>>>", text)
    text = "<pb/>\n" + text

    # Lines → <lb/>
    lines  = text.split("\n")
    result = []
    for i, line in enumerate(lines):
        if i > 0:
            result.append("\n<lb/>")
        result.append(line.rstrip())
    text = "".join(result)

    # Page breaks
    text = re.sub(r"<<<PB>>>", "<pb/>", text)
    text = re.sub(r"\n<lb/>\s*(?=<pb)",  "\n",  text)
    text = re.sub(r"<lb/>\s*\n\s*(?=<pb)", "",  text)
    text = re.sub(r"\n<lb/>\s*$",         "",   text)

    # Empty-page gaps: <<<EMPTY_PAGE>>> sits between two <pb/> elements.
    # The line-break pass will have turned surrounding newlines into <lb/> –
    # strip those and emit the correct TEI markup on its own file line.
    text = re.sub(r"<lb/>\s*<<<BLANK_PAGE>>>\s*", "\n", text)
    text = re.sub(
        r"<lb/>\s*<<<EMPTY_PAGE>>>\s*",
        "\n" + GAP_ELEMENT + "\n",
        text,
    )
    # Catch any residual sentinel not preceded by <lb/>
    text = text.replace("<<<BLANK_PAGE>>>", "\n")
    text = text.replace("<<<EMPTY_PAGE>>>", "\n" + GAP_ELEMENT + "\n")
    text = text.replace("<<<UNREADABLE_LINE>>>", UNREADABLE_LINE_GAP)
    # Clean up double newlines introduced around gap elements
    text = re.sub(r"\n{2,}", "\n", text)

    # Translate size markup to TEI hi elements
    text = text.replace("<large>",  '<hi rend="head">')
    text = text.replace("</large>", "</hi>")
    text = text.replace("<small>",  '<hi rend="small">')
    text = text.replace("</small>", "</hi>")

    # General cleanup
    text = re.sub(r"(<lb/>[\s\n]*)+</hi>",  r"</hi>",     text)
    text = re.sub(r"<lb/>[\s\n]*<pb",        r"<pb",       text)
    text = re.sub(r"\n(</hi>)",              r"\1\n",      text)
    text = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r'\n<lb/>\1', text)
    text = re.sub(r"<lb/> +",               r"<lb/>",     text)
    text = re.sub(r"\n{2,}",                r"\n",        text)
    text = re.sub(r"  +",                   r" ",         text)

    # Remove standalone page numbers before <pb/>
    pn_pat = (r'\n(?:<lb/>)?\s*(?:<hi[^>]*>)?\s*'
              r'(?:[0-9]+|[\u0F20-\u0F29]+|[ivxlcdmIVXLCDM]+)'
              r'\s*(?:</hi>)?\s*\n(?=<pb)')
    text = re.sub(pn_pat, "\n", text)

    # Deduplicate consecutive <pb/>
    text = re.sub(r"(<pb/>[\s\n]*)+", r"<pb/>\n", text)

    return text


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def _generate_tei_header(pdf_path: Path,
                         ie_id: str = "",
                         ve_id: str  = "",
                         ut_id: str  = "",
                         title: str  = "XXX") -> str:
    sha      = _sha256(pdf_path)
    src_path = f"{ve_id}/{pdf_path.name}" if ve_id else pdf_path.name
    ie_value = ie_id.strip()
    if not ie_value:
        raise ValueError("IE ID is required and could not be inferred from input path.")

    return f"""<teiHeader>
<fileDesc>
<titleStmt>
<title>{_escape_xml(title)}</title>
</titleStmt>
<publicationStmt>
<p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
</publicationStmt>
<sourceDesc>
<bibl>
<idno type="src_path">{src_path}</idno>
<idno type="src_sha256">{sha}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{ie_value}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{ie_value}">record in the BDRC database</ref>.</p>
</encodingDesc>
</teiHeader>"""


def generate_tei_document(body_content: str, header: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">\n'
        f"{header}\n"
        "<text>\n"
        '<body xml:lang="bo">\n'
        '<p xml:space="preserve">\n'
        f"{body_content}</p>\n"
        "</body>\n"
        "</text>\n"
        "</TEI>\n"
    )


# =============================================================================
# Main Conversion Function
# =============================================================================

def convert_pdf(pdf_path: Path,
                output_dir: Path,
                ie_id: str          = "",
                ve_id: str          = "",
                file_idx: int       = 1,
                crop: Optional[tuple] = None) -> Optional[Path]:
    """
    Convert a single PDF to a TEI XML file.

    Output structure:
        output_dir/archive/<ve_id>/UT<ve_suffix>_<file_idx:04d>.xml
        output_dir/sources/<ve_id>/<original_pdf_name>

    Returns the path of the produced XML file, or None on failure.
    """
    print(f"  Processing: {pdf_path.name}")

    # ── Phase 1: Extract ──────────────────────────────────────────────────────
    try:
        pages_glyphs = extract_glyphs(pdf_path, crop=crop)
    except Exception as exc:
        print(f"    ERROR during extraction: {exc}")        
        return None

    if not any(pages_glyphs):
        print(f"    No glyphs extracted – skipping.")
        return None

    page_stats = _extract_page_content_stats(pdf_path, crop=crop)
    blank_pages = sum(1 for s in page_stats
                      if s["text_chars"] == 0 and s["images"] == 0 and s["figures"] == 0)
    nonselectable_pages = sum(1 for s in page_stats
                              if s["text_chars"] == 0 and (s["images"] > 0 or s["figures"] > 0))
    if blank_pages:
        print(f"    Info: {blank_pages} truly blank page(s) detected.")
    if nonselectable_pages:
        print(f"    Warning: {nonselectable_pages} non-selectable/image page(s) "
              f"– will be annotated as processing-error gap(s).")

    # ── Phase 2: Decode glyphs ────────────────────────────────────────────────
    pages_glyphs = decode_glyphs(pages_glyphs, pdf_path)

    # ── Phase 3-4: Layout + tagged text ──────────────────────────────────────
    raw_text = pages_to_tagged_text(pages_glyphs, page_stats=page_stats)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    raw_text = remove_indesign_artifacts(raw_text)
    raw_text = remove_headers_footers(raw_text)

    # ── Phase 5: Font size simplification + Unicode normalisation ─────────────
    simplified = simplify_font_sizes(raw_text)
    normalized = normalize_unicode(simplified)
    normalized = fix_tibetan_mark_order(normalized)

    # ── Phase 6: Font markup ──────────────────────────────────────────────────
    classifications = classify_font_sizes(normalized)
    if classifications:
        print(f"    Font classifications: {classifications}")
    marked = apply_font_markup(normalized, classifications)

    # ── Phase 7: TEI assembly ─────────────────────────────────────────────────
    # Derive ve_suffix and ut_id from ve_id (e.g. "VE1ER566" → suffix "1ER566")
    ve_suffix = ve_id[2:] if ve_id.startswith("VE") else ve_id
    ut_id     = f"UT{ve_suffix}_{file_idx:04d}" if ve_id else pdf_path.stem

    tei_body = convert_markup_to_tei(marked)
    header   = _generate_tei_header(pdf_path, ie_id=ie_id, ve_id=ve_id, ut_id=ut_id)
    tei_doc  = generate_tei_document(tei_body, header)

    # ── Write XML to archive/<ve_id>/ ─────────────────────────────────────────
    archive_ve_dir = output_dir / "archive" / (ve_id if ve_id else "unknown")
    archive_ve_dir.mkdir(parents=True, exist_ok=True)
    out_xml = archive_ve_dir / f"{ut_id}.xml"
    out_xml.write_text(tei_doc, encoding="utf-8")
    print(f"    Wrote XML:  {out_xml}")

    # ── Copy source PDF to sources/<ve_id>/ ───────────────────────────────────
    sources_ve_dir = output_dir / "sources" / (ve_id if ve_id else "unknown")
    sources_ve_dir.mkdir(parents=True, exist_ok=True)
    dest_pdf = sources_ve_dir / pdf_path.name
    shutil.copy2(pdf_path, dest_pdf)
    print(f"    Copied PDF: {dest_pdf}")

    return out_xml


def _collect_pdfs_with_ids(input_path: Path,
                           ve_override: str = "",
                           ie_override: str = "") -> list[tuple[Path, str, str]]:
    """
    Collect PDFs and infer (ie_id, ve_id) from path when possible.

    Expected BDRC path pattern:
        IE.../sources/VE.../*.pdf
    """
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"{input_path} is not a PDF file.")
        return [(input_path, ie_override, ve_override)]

    if not input_path.is_dir():
        raise ValueError(f"{input_path} is not a PDF file or a directory.")

    pdf_files = sorted(input_path.glob("**/*.pdf"))
    if not pdf_files:
        raise ValueError(f"No PDF files found in {input_path}")

    entries: list[tuple[Path, str, str]] = []
    for pdf in pdf_files:
        ie_id = ie_override
        ve_id = ve_override

        parts = pdf.parts
        for i, part in enumerate(parts):
            if part == "sources" and i >= 1:
                inferred_ie = parts[i - 1]
                inferred_ve = parts[i + 1] if i + 1 < len(parts) else ""
                if not ie_id:
                    ie_id = inferred_ie if inferred_ie.startswith("IE") else ""
                if not ve_id:
                    ve_id = inferred_ve if inferred_ve.startswith("VE") else ""
                break

        entries.append((pdf, ie_id, ve_id))

    return entries


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF(s) to TEI XML (Tibetan-aware, BDRC output structure)")
    parser.add_argument("input",
        help=(
            "Path to a single PDF file, or a folder containing PDFs. "
            "Supports BDRC layout IE.../sources/VE.../*.pdf and auto-detects IDs."
        ))
    parser.add_argument("output",
        help="Output folder; XML goes to <output>/archive/<ve_id>/, PDFs to <output>/sources/<ve_id>/")
    parser.add_argument("--crop", default=None,
        help=(
            "Crop rectangle x0,y0,x1,y1; accepts PDF points or normalized "
            "fractions in [0..1] per page"
        ))
    parser.add_argument("--ve-id", default="",
        help=(
            "VE ID for the volume (e.g. VE1ER566). Used to build the output "
            "directory structure and the TEI header BDRC identifiers. "
            "When converting a folder of PDFs, each file is numbered "
            "sequentially (0001, 0002, …) within this VE."
        ))
    parser.add_argument("--ie-id", default="",
        help=(
            "IE ID for the etext instance (e.g. IE3KG218). "
            "If omitted, the script tries to infer it from paths like "
            "IE.../sources/VE.../*.pdf."
        ))
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output)
    ve_id       = args.ve_id
    ie_id       = args.ie_id

    crop: Optional[tuple] = None
    if args.crop:
        try:
            crop = tuple(float(v) for v in args.crop.split(","))
            assert len(crop) == 4
        except Exception:
            print("ERROR: --crop must be four comma-separated numbers: x0,y0,x1,y1")
            sys.exit(1)

    try:
        pdf_entries = _collect_pdfs_with_ids(
            input_path,
            ve_override=ve_id,
            ie_override=ie_id,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    missing_ie = [str(pdf) for pdf, entry_ie_id, _ in pdf_entries if not entry_ie_id]
    if missing_ie:
        print("ERROR: IE ID is required for all inputs.")
        print("Provide --ie-id or use BDRC paths like IE.../sources/VE.../*.pdf.")
        print(f"First file missing IE ID: {missing_ie[0]}")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"PDF → TEI XML Converter  (BDRC output structure)")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"IE ID:  {ie_id or '(auto from path)'}")
    print(f"VE ID:  {ve_id or '(none – using PDF stem)'}")
    print(f"Files:  {len(pdf_entries)}")
    if crop:
        print(f"Crop:   {crop}")
    print(f"{'='*60}\n")

    ok = failed = 0
    seq_by_ve: defaultdict[str, int] = defaultdict(int)
    for pdf, entry_ie_id, entry_ve_id in pdf_entries:
        key_ve = entry_ve_id or "__default__"
        seq_by_ve[key_ve] += 1
        result = convert_pdf(
            pdf,
            output_dir         = output_path,
            ie_id              = entry_ie_id,
            ve_id              = entry_ve_id,
            file_idx           = seq_by_ve[key_ve],
            crop               = crop,
        )
        if result:
            ok += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"Done.  Converted: {ok}   Failed: {failed}")
    print(f"Output folder: {output_path}")
    print(f"  archive/  → TEI XML files")
    print(f"  sources/  → original PDFs")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()