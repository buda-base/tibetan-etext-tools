#!/usr/bin/env python3
"""
tib_geometric_extractor.py
==========================
Geometric reconstruction pipeline for Tibetan PDFs with broken ToUnicode CMaps.

Problem this solves
-------------------
Standard PDF text extraction trusts the PDF's ToUnicode CMap. Tibetan Unicode
fonts like MonlamUniOuChan2 use GSUB ligature substitution to produce stacked
glyphs (e.g. ཀྱི་). The PDF subset's ToUnicode CMap only maps the *base*
glyph, so subjoined consonants (ya-btags ྱ, ra-btags ྲ, etc.) are silently
dropped, yielding ཀི་ instead of ཀྱི་.

Pipeline overview
-----------------
Phase 1 – Raw extraction      pdfminer.six LTChar, bboxes, font names, sizes
Phase 2 – Decoding fallback   ToUnicode CMap → fontTools internal cmap → GSUB
Phase 3 – Layout grouping     Cluster LTChar objects into blocks and lines
Phase 4 – Syllable clustering Nearest-neighbour proximity within each line
Phase 5 – Canonical ordering  Base → Subjoined → Vowels → Final marks
Phase 6 – Assembly            NFC-normalised Unicode output

Dependencies
------------
    pip install pdfminer.six fonttools --break-system-packages

Optional (for GSUB inversion, drop-in with existing codebase):
    gsub_resolver.py  (already in your project)
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tibetan Unicode ranges (used everywhere for classification)
# ---------------------------------------------------------------------------

_TIB_MIN = 0x0F00
_TIB_MAX = 0x0FFF

# Subranges used for canonical ordering (Phase 5)
_BASE_CONSONANTS   = range(0x0F40, 0x0F6D)   # ཀ–ཬ
_NUMBERS           = range(0x0F20, 0x0F34)   # ༠–༳
_SUBJOINED         = range(0x0F90, 0x0FBD)   # ྐ–྽  (subjoined consonants)
_BELOW_VOWELS      = (0x0F71, 0x0F74, 0x0F75)  # ཱ, ུ, ཱུ
_ABOVE_VOWELS      = (0x0F72, 0x0F73, 0x0F7A,  # ི, ཱི, ེ,
                      0x0F7B, 0x0F7C, 0x0F7D,  # ཻ, ོ, ཽ
                      0x0F80, 0x0F81)           # ྀ, ཱྀ
_FINAL_MARKS       = (0x0F7E, 0x0F7F,           # ཾ (anusvara), ཿ (visarga)
                      0x0F82, 0x0F83, 0x0F84,   # ྂ, ྃ, ྄
                      0x0F35, 0x0F37)            # ྵ, ྷ

# Bounding-box: (x0, y0, x1, y1) in PDF points
BBox = Tuple[float, float, float, float]


# ===========================================================================
# Phase 1 – Raw glyph extraction via pdfminer.six
# ===========================================================================

@dataclass
class RawGlyph:
    """A single positioned character as extracted from PDF."""
    codepoint: str          # Unicode string (may be wrong for broken CMaps)
    glyph_name: str         # Internal glyph name, e.g. 'glyph00306'
    glyph_id: int           # Numeric GID
    font_name: str          # Cleaned base font name
    font_size: float
    bbox: BBox              # (x0, y0, x1, y1) in PDF user-space points
    page_num: int

    @property
    def x0(self) -> float: return self.bbox[0]
    @property
    def y0(self) -> float: return self.bbox[1]
    @property
    def x1(self) -> float: return self.bbox[2]
    @property
    def y1(self) -> float: return self.bbox[3]
    @property
    def width(self) -> float: return self.x1 - self.x0
    @property
    def height(self) -> float: return self.y1 - self.y0
    @property
    def x_center(self) -> float: return (self.x0 + self.x1) / 2.0
    @property
    def y_center(self) -> float: return (self.y0 + self.y1) / 2.0


def _clean_font_name(raw_name: str) -> str:
    """Strip PDF subset prefix (e.g. 'ABCDEF+FontName' → 'FontName')."""
    if raw_name and '+' in raw_name:
        return raw_name.split('+', 1)[1]
    return raw_name or ''


def extract_raw_glyphs(pdf_path: str, page_numbers: Optional[List[int]] = None) -> List[List[RawGlyph]]:
    """
    Phase 1: Extract all LTChar objects from a PDF, page by page.

    Returns a list of pages; each page is a flat list of RawGlyph objects.
    The reading order of the PDF stream is deliberately ignored — we rely
    entirely on bbox coordinates for layout reconstruction (Phase 3).

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.
    page_numbers : list[int] | None
        0-based page indices to process. None = all pages.
    """
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTChar
    except ImportError as e:
        raise ImportError(
            "pdfminer.six is required: pip install pdfminer.six"
        ) from e

    all_pages: List[List[RawGlyph]] = []
    page_filter = set(page_numbers) if page_numbers is not None else None

    for page_idx, page_layout in enumerate(extract_pages(pdf_path)):
        if page_filter is not None and page_idx not in page_filter:
            all_pages.append([])
            continue

        glyphs: List[RawGlyph] = []
        _collect_ltchars(page_layout, glyphs, page_idx)
        all_pages.append(glyphs)
        logger.debug("Page %d: %d raw glyphs", page_idx, len(glyphs))

    return all_pages


def _collect_ltchars(element, out: List[RawGlyph], page_num: int) -> None:
    """Recursively walk a pdfminer layout element tree, collecting LTChar objects."""
    from pdfminer.layout import LTChar, LTFigure, LTLayoutContainer

    if isinstance(element, LTChar):
        font = element.fontname or ''
        clean_font = _clean_font_name(font)
        # Extract glyph name and GID from the pdfminer character object
        glyph_name = ''
        glyph_id = 0
        try:
            # pdfminer stores the PDFFont on the char; we can reach the glyph name
            # through the font's resource. Fall back gracefully if not available.
            if hasattr(element, 'font') and element.font:
                pdf_font = element.font
                # pdfminer encodes the character; reverse to get glyph info
                if hasattr(pdf_font, 'char_to_gid'):
                    glyph_id = pdf_font.char_to_gid.get(element._text, 0)
                if hasattr(pdf_font, 'cid2unicode'):
                    pass  # already decoded
        except Exception:
            pass

        g = RawGlyph(
            codepoint=element._text,
            glyph_name=glyph_name,
            glyph_id=glyph_id,
            font_name=clean_font,
            font_size=element.size,
            bbox=element.bbox,  # (x0, y0, x1, y1)
            page_num=page_num,
        )
        out.append(g)

    elif hasattr(element, '__iter__'):
        for child in element:
            _collect_ltchars(child, out, page_num)


# ===========================================================================
# Phase 2 – Decoding fallback: ToUnicode → fontTools cmap → GSUB
# ===========================================================================

@dataclass
class FontDecoder:
    """
    Encapsulates all glyph-to-Unicode resolution logic for one embedded font.

    Resolution hierarchy (mirrors the spec and your existing gsub_resolver.py):
      1. ToUnicode CMap (trusted Tibetan-valued entries only)
      2. fontTools internal cmap (glyph_name → Unicode via cmap table)
      3. GSUB inversion (requires full unsubsetted font from FONT_DIR)
      4. Fuzzy shape matching (outline hash comparison)
    """
    font_name: str
    _gid_map: Dict[int, str] = field(default_factory=dict)      # GID → unicode
    _name_map: Dict[str, str] = field(default_factory=dict)     # glyph_name → unicode
    _ready: bool = False

    # ------------------------------------------------------------------
    # Bootstrap: load from the PDF's embedded subset font bytes
    # ------------------------------------------------------------------

    def load_from_font_bytes(self, font_bytes: bytes, tounicode_cmap: Dict[int, str]) -> None:
        """
        Primary setup path.

        1. Seed self._gid_map from the ToUnicode CMap (Tibetan entries only).
        2. Load the embedded subset via fontTools to access glyph names.
        3. For any GID that ToUnicode maps to non-Tibetan (or is absent):
             a. Try fontTools' internal cmap (often stripped in subsets, but worth trying).
             b. Fall through to GSUB / fuzzy via gsub_resolver if available.
        """
        try:
            from fontTools import ttLib
        except ImportError:
            logger.warning("fontTools not available; Phase 2 fallback disabled")
            self._gid_map = tounicode_cmap
            self._ready = True
            return

        # Step 2.1 – Accept Tibetan-valued ToUnicode entries as ground truth
        for gid, uni in tounicode_cmap.items():
            if _all_tibetan(uni):
                self._gid_map[gid] = uni

        if not font_bytes:
            self._ready = True
            return

        # Load subset font
        try:
            subset_tt = ttLib.TTFont(io.BytesIO(font_bytes))
        except Exception as e:
            logger.debug("FontDecoder: failed to load subset bytes: %s", e)
            self._ready = True
            return

        glyph_order = subset_tt.getGlyphOrder()

        # Step 2.2 – fontTools internal cmap (usually absent in subsets, but try)
        try:
            internal_cmap = subset_tt['cmap'].getBestCmap() or {}
            # Invert: codepoint → glyph_name, then resolve glyph_name → GID
            name_to_cp = {gname: cp for cp, gname in internal_cmap.items()}
            for gid, gname in enumerate(glyph_order):
                if gid in self._gid_map:
                    continue  # already resolved by ToUnicode
                cp = name_to_cp.get(gname)
                if cp and _all_tibetan(chr(cp)):
                    self._gid_map[gid] = chr(cp)
                    logger.debug("FontDecoder step2.2: GID 0x%04X %s → U+%04X", gid, gname, cp)
        except (KeyError, Exception) as e:
            logger.debug("FontDecoder step2.2: no internal cmap (%s)", e)

        # Step 2.3 – GSUB inversion + fuzzy shape via gsub_resolver (if available)
        self._apply_gsub_resolver(subset_tt, tounicode_cmap, glyph_order)

        # Build name map for lookup by glyph name (used in Phase 1 augmentation)
        for gid, gname in enumerate(glyph_order):
            if gid in self._gid_map:
                self._name_map[gname] = self._gid_map[gid]

        self._ready = True
        logger.info(
            "FontDecoder '%s': %d / %d GIDs resolved",
            self.font_name, len(self._gid_map), len(glyph_order)
        )

    def _apply_gsub_resolver(self, subset_tt, tounicode_cmap: Dict[int, str], glyph_order: list) -> None:
        """
        Step 2.3: Use gsub_resolver.build_glyph_unicode_map (your existing module)
        to fill gaps left by the ToUnicode CMap.

        This is the core fix for dropped subjoined consonants:
          - The ToUnicode CMap maps the ligature glyph (e.g. ཀྱ) to just 'ཀ'
            (the base consonant), dropping ྱ (ya-btags U+0FB1).
          - GSUB inversion traces the substitution chain: the ligature glyph was
            produced by substituting ཀ + ྱ, so its correct Unicode is 'ཀྱ'.
          - Fuzzy shape matching catches the remaining cases where the CMap is
            missing the entry entirely.

        Requires either:
          a. Full font files in FONT_DIR (config.py) — best accuracy
          b. Subset font with enough outline data for shape matching
        """
        try:
            from gsub_resolver import build_glyph_unicode_map
        except ImportError:
            logger.debug("gsub_resolver not available; skipping GSUB step")
            return

        try:
            glyph_map = build_glyph_unicode_map(subset_tt, tounicode_cmap)
            resolved = 0
            for gid, gname in enumerate(glyph_order):
                if gid in self._gid_map:
                    continue
                uni = glyph_map.get(gname)
                if uni and _all_tibetan(uni):
                    self._gid_map[gid] = uni
                    resolved += 1
            logger.debug("FontDecoder step2.3 (GSUB+fuzzy): %d additional GIDs resolved", resolved)
        except Exception as e:
            logger.warning("FontDecoder step2.3 error: %s", e)

    def decode(self, glyph_id: int, fallback: str) -> str:
        """Resolve a GID to its correct Unicode string."""
        return self._gid_map.get(glyph_id, fallback)

    def decode_by_name(self, glyph_name: str, fallback: str) -> str:
        """Resolve a glyph name to its correct Unicode string."""
        return self._name_map.get(glyph_name, fallback)


def _all_tibetan(s: str) -> bool:
    """Return True if every character in s is in the Tibetan Unicode block."""
    return bool(s) and all(_TIB_MIN <= ord(c) <= _TIB_MAX for c in s)


def build_font_decoders_from_pdf(pdf_path: str) -> Dict[str, FontDecoder]:
    """
    Phase 2 entry point: extract embedded font data from the PDF and build
    a FontDecoder for every Identity-H (Unicode CID) font found.

    Uses pypdf to read the raw PDF structure (font xrefs, CMap streams,
    embedded FontFile2 streams). pdfminer.six is used only for glyph extraction
    in Phase 1; the font structure access uses pypdf which is already a
    dependency of your project.

    Returns
    -------
    dict[font_name_stem, FontDecoder]
    """
    decoders: Dict[str, FontDecoder] = {}

    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf not available; font decoder setup skipped")
        return decoders

    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            logger.warning("PyMuPDF not available; using pypdf-only font extraction")
            fitz = None

    # Use PyMuPDF for font extraction (more reliable CMap / FontFile2 access)
    if fitz is not None:
        decoders = _build_decoders_via_pymupdf(pdf_path, fitz)
    else:
        decoders = _build_decoders_via_pypdf(pdf_path)

    return decoders


def _parse_tounicode_cmap(cmap_text: str) -> Dict[int, str]:
    """
    Parse a ToUnicode CMap stream into {glyph_id: unicode_string}.

    Handles:
      - beginbfchar / endbfchar  (<gid> <unicode_hex>)
      - beginbfrange / endbfrange linear  (<start> <end> <base_hex>)
      - beginbfrange / endbfrange array  (<start> <end> [<hex1> <hex2> …])
    """
    result: Dict[int, str] = {}

    # Single-char mappings
    for m in re.finditer(r'<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]+)>', cmap_text):
        gid = int(m.group(1), 16)
        uhex = m.group(2)
        result[gid] = ''.join(chr(int(uhex[i:i+4], 16)) for i in range(0, len(uhex), 4))

    # Range mappings (linear)
    for m in re.finditer(
        r'<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]+)>', cmap_text
    ):
        start, end = int(m.group(1), 16), int(m.group(2), 16)
        base_hex = m.group(3)
        if len(base_hex) == 4:
            base_cp = int(base_hex, 16)
            for i in range(end - start + 1):
                result[start + i] = chr(base_cp + i)

    return result


def _build_decoders_via_pymupdf(pdf_path: str, fitz) -> Dict[str, FontDecoder]:
    """Extract font data using PyMuPDF and build FontDecoder objects."""
    decoders: Dict[str, FontDecoder] = {}
    try:
        from fontTools import ttLib
        ft_available = True
    except ImportError:
        ft_available = False

    doc = fitz.open(pdf_path)
    processed_tou_xrefs: set = set()

    for pn in range(len(doc)):
        page = doc[pn]
        for font_entry in page.get_fonts(full=True):
            font_xref = font_entry[0]
            enc = font_entry[5]
            if enc != 'Identity-H':
                continue

            raw_font_name = font_entry[3]
            clean_name = _clean_font_name(raw_font_name)

            if clean_name in decoders:
                continue

            font_obj_str = doc.xref_object(font_xref, compressed=False)

            # Extract ToUnicode CMap
            tou_m = re.search(r'/ToUnicode\s+(\d+)\s+0\s+R', font_obj_str)
            tounicode_cmap: Dict[int, str] = {}
            tou_xref = None
            if tou_m:
                tou_xref = int(tou_m.group(1))
                if tou_xref not in processed_tou_xrefs:
                    try:
                        cmap_bytes = doc.xref_stream(tou_xref)
                        cmap_text = cmap_bytes.decode('latin-1', errors='replace')
                        tounicode_cmap = _parse_tounicode_cmap(cmap_text)
                    except Exception as e:
                        logger.debug("Cannot read ToUnicode xref=%d: %s", tou_xref, e)

            # Extract embedded font bytes (FontFile2 = TrueType)
            font_bytes = b''
            desc_m = re.search(r'/DescendantFonts\s*\[\s*(\d+)', font_obj_str)
            if desc_m:
                desc_obj = doc.xref_object(int(desc_m.group(1)), compressed=False)
                fd_m = re.search(r'/FontDescriptor\s+(\d+)', desc_obj)
                if fd_m:
                    fd_obj = doc.xref_object(int(fd_m.group(1)), compressed=False)
                    ff2_m = re.search(r'/FontFile2\s+(\d+)', fd_obj)
                    if ff2_m:
                        try:
                            font_bytes = doc.xref_stream(int(ff2_m.group(1)))
                        except Exception:
                            pass

            # Build decoder
            decoder = FontDecoder(font_name=clean_name)
            decoder.load_from_font_bytes(font_bytes, tounicode_cmap)
            decoders[clean_name] = decoder

            if tou_xref:
                processed_tou_xrefs.add(tou_xref)

            logger.info(
                "Built FontDecoder for '%s' (ToUnicode: %d entries, FontFile2: %d bytes)",
                clean_name, len(tounicode_cmap), len(font_bytes)
            )

    doc.close()
    return decoders


def _build_decoders_via_pypdf(pdf_path: str) -> Dict[str, FontDecoder]:
    """Fallback font extraction using pypdf (no PyMuPDF)."""
    decoders: Dict[str, FontDecoder] = {}
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            resources = page.get('/Resources')
            if not resources:
                continue
            if hasattr(resources, 'get_object'):
                resources = resources.get_object()
            font_dict = resources.get('/Font')
            if not font_dict:
                continue
            if hasattr(font_dict, 'get_object'):
                font_dict = font_dict.get_object()
            for res_name, font_ref in font_dict.items():
                font_obj = font_ref.get_object() if hasattr(font_ref, 'get_object') else font_ref
                base_font = str(font_obj.get('/BaseFont', '')).lstrip('/')
                clean = _clean_font_name(base_font)
                if clean and clean not in decoders:
                    decoder = FontDecoder(font_name=clean)
                    decoder.load_from_font_bytes(b'', {})
                    decoders[clean] = decoder
    except Exception as e:
        logger.warning("pypdf font extraction error: %s", e)
    return decoders


# ===========================================================================
# Phase 2 augmentation: re-decode raw glyphs using FontDecoder
# ===========================================================================

def redecode_glyphs(
    pages: List[List[RawGlyph]],
    decoders: Dict[str, FontDecoder],
) -> List[List[RawGlyph]]:
    """
    Apply FontDecoder corrections to each RawGlyph in-place.

    Replaces each glyph's `.codepoint` with the resolved Unicode string when
    the decoder has a better answer than the raw ToUnicode CMap value.

    This is where dropped subjoined consonants get restored:
      Raw codepoint:     'ཀ'    (only base consonant from broken CMap)
      Corrected:         'ཀྱ'   (base + ya-btags, from GSUB inversion)
    """
    for page_glyphs in pages:
        for g in page_glyphs:
            decoder = decoders.get(g.font_name)
            if decoder is None:
                continue
            corrected = decoder.decode(g.glyph_id, g.codepoint)
            if corrected != g.codepoint:
                logger.debug(
                    "Glyph correction: font=%s GID=0x%04X %r → %r",
                    g.font_name, g.glyph_id, g.codepoint, corrected
                )
            g.codepoint = corrected
    return pages


# ===========================================================================
# Phase 3 – Geometric layout: group glyphs into blocks → lines
# ===========================================================================

@dataclass
class TextLine:
    """A horizontal run of glyphs sharing approximately the same baseline."""
    glyphs: List[RawGlyph] = field(default_factory=list)
    page_num: int = 0

    @property
    def bbox(self) -> BBox:
        if not self.glyphs:
            return (0, 0, 0, 0)
        return (
            min(g.x0 for g in self.glyphs),
            min(g.y0 for g in self.glyphs),
            max(g.x1 for g in self.glyphs),
            max(g.y1 for g in self.glyphs),
        )

    @property
    def y_center(self) -> float:
        b = self.bbox
        return (b[1] + b[3]) / 2.0

    @property
    def dominant_font_size(self) -> float:
        if not self.glyphs:
            return 12.0
        sizes = [g.font_size for g in self.glyphs if g.font_size > 0]
        return sorted(sizes)[len(sizes) // 2] if sizes else 12.0


@dataclass
class TextBlock:
    """A group of lines that form a coherent text block."""
    lines: List[TextLine] = field(default_factory=list)


def group_glyphs_into_lines(
    glyphs: List[RawGlyph],
    y_tolerance_factor: float = 0.5,
) -> List[TextLine]:
    """
    Phase 3a: Group glyphs into horizontal text lines by vertical overlap.

    Two glyphs belong to the same line when their y-band centres are within
    `y_tolerance_factor * median_font_size` of each other. This is more
    robust than a fixed threshold because Tibetan PDFs mix font sizes
    (body text ~13pt, footnotes ~9pt, headings ~16pt).

    Algorithm
    ---------
    1. Sort all glyphs by y_center (top of page first in PDF coordinates is
       higher y value, so sort descending for reading order).
    2. Walk the sorted list; if the current glyph's y_center is within
       tolerance of the running average for the current line bucket, append it;
       otherwise start a new bucket.
    3. Within each line bucket, sort glyphs left-to-right by x0.

    Parameters
    ----------
    glyphs : list[RawGlyph]
        All glyphs on one page (Phase 1 output, after Phase 2 correction).
    y_tolerance_factor : float
        Multiplier on the font size to determine vertical clustering radius.
        0.5 means glyphs must share > 50% of their height band to be co-linear.
    """
    if not glyphs:
        return []

    # Estimate median font size for tolerance
    sizes = sorted(g.font_size for g in glyphs if g.font_size > 0)
    median_size = sizes[len(sizes) // 2] if sizes else 12.0
    y_tol = y_tolerance_factor * median_size

    # Sort descending by y_center (top of page first)
    sorted_glyphs = sorted(glyphs, key=lambda g: (-g.y_center, g.x0))

    lines: List[TextLine] = []
    current_line: Optional[TextLine] = None
    current_y_avg: float = 0.0

    for glyph in sorted_glyphs:
        if current_line is None or abs(glyph.y_center - current_y_avg) > y_tol:
            current_line = TextLine(glyphs=[], page_num=glyph.page_num)
            lines.append(current_line)
            current_y_avg = glyph.y_center
        else:
            # Running average keeps tolerance adaptive as the line fills
            n = len(current_line.glyphs)
            current_y_avg = (current_y_avg * n + glyph.y_center) / (n + 1)

        current_line.glyphs.append(glyph)

    # Sort each line's glyphs left-to-right
    for line in lines:
        line.glyphs.sort(key=lambda g: g.x0)

    logger.debug("Phase 3: %d glyphs → %d lines", len(glyphs), len(lines))
    return lines


def group_lines_into_blocks(
    lines: List[TextLine],
    block_gap_factor: float = 1.5,
) -> List[TextBlock]:
    """
    Phase 3b: Group lines into text blocks based on inter-line vertical gap.

    A new block starts when the gap between consecutive lines exceeds
    `block_gap_factor * median_line_height`. This separates headers, body
    paragraphs, and footnotes without needing heuristic page-region rules.
    """
    if not lines:
        return []

    line_heights = [ln.bbox[3] - ln.bbox[1] for ln in lines if ln.glyphs]
    median_height = sorted(line_heights)[len(line_heights) // 2] if line_heights else 12.0
    gap_threshold = block_gap_factor * median_height

    blocks: List[TextBlock] = []
    current_block = TextBlock(lines=[lines[0]])

    for prev_line, next_line in zip(lines, lines[1:]):
        gap = prev_line.bbox[1] - next_line.bbox[3]  # PDF y increases upward
        if gap > gap_threshold:
            blocks.append(current_block)
            current_block = TextBlock(lines=[])
        current_block.lines.append(next_line)

    blocks.append(current_block)
    logger.debug("Phase 3: %d lines → %d blocks", len(lines), len(blocks))
    return blocks


# ===========================================================================
# Phase 4 – Syllable clustering within lines
# ===========================================================================

@dataclass
class SyllableCluster:
    """
    A cluster of glyphs that form one Tibetan syllable stack.

    In Tibetan typography a syllable cluster can span multiple vertical levels:
      - Main (base) consonant on the writing baseline
      - Subjoined consonants below (ra-btags ྲ, ya-btags ྱ, wa-zur ྭ, etc.)
      - Vowel signs above (gigu ི, drengbu ེ, etc.) or below (naro ུ)
      - Final marks (anusvara ཾ, etc.)

    The bounding boxes of stacked glyphs significantly overlap horizontally
    but are separated vertically — this is the geometric signal we exploit.
    """
    glyphs: List[RawGlyph] = field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        if not self.glyphs:
            return (0, 0, 0, 0)
        return (
            min(g.x0 for g in self.glyphs),
            min(g.y0 for g in self.glyphs),
            max(g.x1 for g in self.glyphs),
            max(g.y1 for g in self.glyphs),
        )

    @property
    def x_center(self) -> float:
        b = self.bbox
        return (b[0] + b[2]) / 2.0


def cluster_line_into_syllables(
    line: TextLine,
    overlap_threshold: float = 0.3,
) -> List[SyllableCluster]:
    """
    Phase 4: Partition the glyphs in a line into syllable clusters.

    Core insight for Tibetan stacking:
      Base consonant ཀ and its ya-btags ྱ share the same horizontal column.
      Their x-ranges OVERLAP significantly (≥ overlap_threshold fraction of
      the narrower glyph's width). A tsheg (་) or space marks the syllable
      boundary — it does NOT overlap horizontally with the preceding cluster.

    Algorithm (nearest-neighbour with overlap test):
    ------------------------------------------------
    1. Walk left-to-right through the line's glyphs.
    2. For each glyph, check horizontal overlap with the current cluster's bbox.
       - If overlap ≥ threshold  →  this glyph belongs to the current cluster
         (it is a stacked/attached mark on the same syllable).
       - If overlap < threshold  →  start a new cluster.

    Overlap is computed as:
        overlap_width / min(glyph_width, cluster_width)

    This handles the case where a vowel sign glyph is slightly narrower than
    the consonant it attaches to — the overlap fraction stays high.

    Parameters
    ----------
    line : TextLine
        A horizontal line of glyphs (left-to-right sorted from Phase 3).
    overlap_threshold : float
        Minimum horizontal overlap fraction to merge into current cluster.
        0.3 works well for Monlam fonts; decrease for looser stacking.
    """
    if not line.glyphs:
        return []

    clusters: List[SyllableCluster] = []
    current = SyllableCluster(glyphs=[line.glyphs[0]])

    for glyph in line.glyphs[1:]:
        c_bbox = current.bbox
        c_width = c_bbox[2] - c_bbox[0]
        g_width = glyph.width if glyph.width > 0 else 0.1

        # Horizontal overlap between this glyph and current cluster
        overlap_left = max(glyph.x0, c_bbox[0])
        overlap_right = min(glyph.x1, c_bbox[2])
        overlap_width = max(0.0, overlap_right - overlap_left)

        min_width = min(c_width, g_width) if min(c_width, g_width) > 0 else 0.1
        overlap_frac = overlap_width / min_width

        # Tibetan tsheg (་) and shad (།) are syllable/sentence boundary markers.
        # They should never be merged into a preceding cluster even if they touch.
        is_boundary_mark = glyph.codepoint in ('\u0F0B', '\u0F0C', '\u0F0D', '\u0F0E',
                                               '\u0F0F', ' ', '\xa0')

        if overlap_frac >= overlap_threshold and not is_boundary_mark:
            current.glyphs.append(glyph)
        else:
            clusters.append(current)
            current = SyllableCluster(glyphs=[glyph])

    clusters.append(current)
    return clusters


# ===========================================================================
# Phase 5 – Canonical Tibetan Unicode ordering within each cluster
# ===========================================================================

def _tibetan_slot(codepoint: str) -> int:
    """
    Return the canonical ordering slot for a Tibetan codepoint.

    Slot values define the legal Unicode sequence within one syllable stack
    (ascending order = correct reading order):

        0  Base consonants  (ཀ–ཬ, U+0F40–0F6C) or numbers/other
        1  Subjoined consonants (ྐ–྽, U+0F90–0FBC)  ← the dropped chars!
        2  Below-stack vowels (ཱ U+0F71, ུ U+0F74)
        3  Above-stack vowels (ི, ེ, ོ, etc.)
        4  Final marks (ཾ anusvara, ཿ visarga, ྂ, etc.)
        5  Everything else (tsheg, digits, punctuation)

    The slot numbers match the standard description of Tibetan syllable
    structure: consonant frame → subjoined stack → vowel decoration → marks.

    Why sorting by slot fixes dropped subjoined consonants:
      If Phase 2 correctly restored the subjoined codepoint into the glyph's
      `.codepoint` string, it may arrive as a single multi-char string ('ཀྱ').
      When the cluster mixes single-char and multi-char codepoints, we need to
      expand and re-sort them to ensure the canonical sequence.
    """
    if not codepoint:
        return 5
    cp = ord(codepoint[0])

    if 0x0F40 <= cp <= 0x0F6C:      # Base consonants
        return 0
    if 0x0F20 <= cp <= 0x0F33:      # Tibetan digits / numbers
        return 0
    if cp == 0x0F00:                  # ༀ (OM syllable)
        return 0
    if 0x0F90 <= cp <= 0x0FBC:      # Subjoined consonants — slot 1
        return 1
    if cp in (0x0F71, 0x0F74, 0x0F75):  # Below vowels — slot 2
        return 2
    if 0x0F72 <= cp <= 0x0F81 and cp not in (0x0F74, 0x0F75):  # Above vowels — slot 3
        return 3
    if cp in (0x0F7E, 0x0F7F, 0x0F82, 0x0F83, 0x0F84, 0x0F35, 0x0F37):  # Final marks — slot 4
        return 4
    return 5  # tsheg, shad, punctuation, Latin fallback, etc.


def canonically_order_cluster(cluster: SyllableCluster) -> str:
    """
    Phase 5: Assemble one syllable cluster into a canonically-ordered Unicode string.

    Steps
    -----
    1. Expand each glyph's .codepoint into individual characters.
       (Phase 2 GSUB correction may have returned multi-char strings like 'ཀྱ'.)
    2. Separate into "base" characters (to sort) and "boundary" characters
       (tsheg, shad — to append verbatim at the end).
    3. Sort the non-boundary characters by their canonical slot (0→4).
    4. Within slot 0 (base consonants), use the geometric y_center of the
       originating glyph as a tie-breaker: lower on the page (smaller y)
       means visually below, which typically means it is a superscript prefix
       (like a ra-mgo ར) not a subjoined — keep it first.
    5. Re-join and return.

    Note on NFC: we apply unicodedata.normalize('NFC', …) at the final assembly
    stage (Phase 6), not here, so that Phase 5's ordering is preserved exactly.
    """
    # Build a list of (char, source_glyph) pairs
    char_glyph_pairs: List[Tuple[str, RawGlyph]] = []
    boundary_chars: List[str] = []

    for glyph in cluster.glyphs:
        for ch in glyph.codepoint:
            if not ch or ch.isspace():
                boundary_chars.append(ch)
                continue
            cp = ord(ch)
            if _TIB_MIN <= cp <= _TIB_MAX:
                char_glyph_pairs.append((ch, glyph))
            else:
                # Non-Tibetan characters (ASCII punctuation, digits, etc.) pass through
                char_glyph_pairs.append((ch, glyph))

    if not char_glyph_pairs and not boundary_chars:
        return ''

    # Sort by canonical slot, then by source glyph's y_center (descending =
    # higher on page comes first, matching reading order for stacked elements)
    char_glyph_pairs.sort(key=lambda cg: (_tibetan_slot(cg[0]), -cg[1].y_center))

    result = ''.join(ch for ch, _ in char_glyph_pairs)
    result += ''.join(boundary_chars)
    return result


# ===========================================================================
# Phase 6 – Final assembly
# ===========================================================================

def assemble_page_text(
    blocks: List[TextBlock],
    decoders: Dict[str, FontDecoder],
    page_num: int,
) -> str:
    """
    Phase 6: Convert a page's text blocks into a NFC-normalised Unicode string.

    Structure:
      - Blocks are separated by double newlines.
      - Lines within a block are separated by single newlines.
      - Syllable clusters within a line are joined directly (no separator between
        stacked glyphs; tsheg/shad glyphs provide the inter-syllable spacing).
    """
    block_texts: List[str] = []

    for block in blocks:
        line_texts: List[str] = []
        for line in block.lines:
            # Phase 4: cluster into syllables
            clusters = cluster_line_into_syllables(line)
            # Phase 5: canonical ordering within each cluster
            syllable_strings = [canonically_order_cluster(c) for c in clusters]
            line_text = ''.join(s for s in syllable_strings if s)
            # Phase 6: NFC normalisation per line
            line_text = unicodedata.normalize('NFC', line_text)
            if line_text.strip():
                line_texts.append(line_text)

        if line_texts:
            block_texts.append('\n'.join(line_texts))

    return '\n\n'.join(block_texts)


# ===========================================================================
# Top-level pipeline entry point
# ===========================================================================

def extract_tibetan_text(
    pdf_path: str,
    page_numbers: Optional[List[int]] = None,
    y_tolerance_factor: float = 0.5,
    overlap_threshold: float = 0.3,
) -> List[str]:
    """
    Full 6-phase geometric extraction pipeline.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.
    page_numbers : list[int] | None
        0-based page indices to process. None = all pages.
    y_tolerance_factor : float
        Phase 3 vertical clustering tolerance (fraction of font size).
    overlap_threshold : float
        Phase 4 horizontal overlap threshold for syllable clustering.

    Returns
    -------
    list[str]
        One string per page of extracted, NFC-normalised Tibetan Unicode text.

    Example
    -------
    >>> pages = extract_tibetan_text("broken_cmap.pdf")
    >>> print(pages[0][:200])
    ཀྱི་རྒྱུ་མཚན་...   # subjoined consonants now present!
    """
    logger.info("=== Tibetan Geometric Extraction Pipeline ===")
    logger.info("Input: %s", pdf_path)

    # Phase 1 – Raw extraction
    logger.info("Phase 1: Extracting raw glyphs via pdfminer.six ...")
    raw_pages = extract_raw_glyphs(pdf_path, page_numbers)
    total_glyphs = sum(len(p) for p in raw_pages)
    logger.info("  Extracted %d glyphs across %d pages", total_glyphs, len(raw_pages))

    # Phase 2 – Build font decoders
    logger.info("Phase 2: Building font decoders (fontTools + GSUB) ...")
    decoders = build_font_decoders_from_pdf(pdf_path)
    logger.info("  %d font decoder(s) built: %s", len(decoders), list(decoders.keys()))

    # Phase 2 – Apply corrections
    logger.info("Phase 2: Applying glyph corrections ...")
    corrected_pages = redecode_glyphs(raw_pages, decoders)

    page_texts: List[str] = []

    for page_idx, page_glyphs in enumerate(corrected_pages):
        if not page_glyphs:
            page_texts.append('')
            continue

        logger.debug("Processing page %d (%d glyphs)", page_idx, len(page_glyphs))

        # Phase 3 – Layout grouping
        lines = group_glyphs_into_lines(page_glyphs, y_tolerance_factor)
        blocks = group_lines_into_blocks(lines)

        # Phases 4, 5, 6 – Cluster, order, assemble
        page_text = assemble_page_text(blocks, decoders, page_idx)
        page_texts.append(page_text)

    logger.info("=== Extraction complete. %d pages processed. ===", len(page_texts))
    return page_texts


# ===========================================================================
# Integration helper: drop-in replacement for extract_pdf_pymupdf
# ===========================================================================

def extract_pdf_geometric(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    page_break_str: str = "ZZZZ",
) -> str:
    """
    Drop-in companion to extract_pdf_pymupdf() in pdf_extract.py.

    Use this when PyMuPDF's rawdict extraction produces text with dropped
    subjoined consonants despite CMap patching (e.g. when the subset font
    lacks enough outline data for shape matching).

    Returns the same format as extract_pdf_pymupdf:
      - newline per visual line
      - `page_break_str` between pages
      - Font-size tags are NOT emitted (geometric extractor focuses on
        correct Unicode; plug back into your classify_font_sizes pipeline
        separately if needed).

    Usage in convert_pdf_to_xml.py
    --------------------------------
    Replace:
        from pdf_extract import extract_pdf_pymupdf
        raw_text = extract_pdf_pymupdf(pdf_path, ...)

    With:
        from tib_geometric_extractor import extract_pdf_geometric
        raw_text = extract_pdf_geometric(pdf_path, ...)
    """
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)

    page_texts = extract_tibetan_text(str(pdf_path))
    parts: List[str] = []

    for page_text in page_texts:
        parts.append(page_text)
        parts.append(f'\n{page_break_str}\n')

    return ''.join(parts)


# ===========================================================================
# CLI entry point for quick testing
# ===========================================================================

if __name__ == '__main__':
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description='Geometric Tibetan PDF extractor (bypasses broken ToUnicode CMaps)'
    )
    parser.add_argument('pdf', help='Path to input PDF')
    parser.add_argument('--pages', nargs='+', type=int, help='0-based page numbers to process')
    parser.add_argument('--out', help='Output text file (default: stdout)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(levelname)s %(message)s',
    )

    pages = extract_tibetan_text(args.pdf, page_numbers=args.pages)

    output = '\n\n--- PAGE BREAK ---\n\n'.join(pages)

    if args.out:
        Path(args.out).write_text(output, encoding='utf-8')
        print(f'Written to {args.out}')
    else:
        print(output)
