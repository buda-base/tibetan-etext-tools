"""
PDF text extraction for Monlam-font PDFs: PyMuPDF ``rawdict`` or ``pytiblegenc.pdf_to_txt``.

Line breaks are layout-level (one ``\n`` per extractor line); ``PAGE_BREAK_STR`` marks pages.

Fixes applied (all in the PyMuPDF path):
  1. Phantom space detection rule corrected  (space_x < prev_x + threshold, not < next_x)
  2. WinAnsi vowel glyph mis-mappings — resolved via gsub_resolver (GSUB inversion +
     fuzzy shape matching).  The ToUnicode CMap is patched in-memory before extraction
     so PyMuPDF decodes characters correctly without any per-character post-processing.
     Set FONT_DIR in config.py to enable GSUB inversion from the full .ttf file.
  3. Phantom space check threaded across span boundaries within a line
  4. Epsilon tolerance for near-zero-advance phantom spaces from WinAnsi vowel spans
  5. Duplicate text-layer deduplication for InDesign-generated PDFs (NFC + ZW strip
     + whitespace / U+3000 normalisation for keys; looser X bucketing for CJK).
     (b) _dedup_within_row removes shadow copies that survive (a) within a merged row.
  6. TibetanMachine / Dedris legacy Type1 font decoding — applied per-span at extraction
     time.  Fonts are detected by their Encoding /Differences glyph names (ASCII standard
     names, not Tibetan Unicode names) and decoded via the TibetanMachineWeb table from
     dedris_resolver.py.  Safe for mixed-language pages (English + Tibetan colophons).
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import traceback
import unicodedata
from pathlib import Path
from typing import Dict, Optional, Tuple

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

try:
    from fontTools import ttLib as _ttLib
    FONTTOOLS_AVAILABLE = True
except ImportError:
    FONTTOOLS_AVAILABLE = False
    _ttLib = None  # type: ignore

try:
    from gsub_resolver import build_glyph_unicode_map
    GSUB_RESOLVER_AVAILABLE = True
except ImportError:
    GSUB_RESOLVER_AVAILABLE = False

try:
    from dedris_resolver import is_dedris_font, decode_tibetan_machine, should_decode_span
    DEDRIS_RESOLVER_AVAILABLE = True
except ImportError:
    DEDRIS_RESOLVER_AVAILABLE = False

logger = logging.getLogger(__name__)

PAGE_BREAK_STR = "ZZZZ"
_FONT_SIZE_FORMAT = "<fs:{}>"

# Footnote sentinels (format per convert_pdf_to_xml.convert_footnote_sentinels_to_tei).
# pdf_extract may emit these when footnote detection is enabled.
_FN_SENTINEL_START = "ZZFN_START:"
_FN_SENTINEL_END = "ZZFN_END"


# ---------------------------------------------------------------------------
# Fix 2 — GSUB-based CMap patching
#
# For Unicode Tibetan fonts (MonlamUniOuChan2 etc.) the PDF's ToUnicode CMap
# maps some GSUB-substituted glyph alternates to wrong Latin Extended codepoints
# instead of the correct Tibetan vowels.  The fix uses gsub_resolver to identify
# the correct mappings and patches them directly into the CMap stream in memory
# before PyMuPDF processes the page — so PyMuPDF decodes characters correctly
# without any per-character post-processing.
#
# Resolution hierarchy (applied once per unique embedded font per PDF):
#   A) GSUB inversion via gsub_resolver + full .ttf from FONT_DIR        [best]
#   B) Fuzzy shape matching via gsub_resolver using the PDF's CMap        [good]
#
# To enable (A): set FONT_DIR in config.py to the directory containing the full
# (unsubsetted) font files, e.g. MonlamUniOuChan2.ttf, MonlamUniOuChan5.ttf.
# Without it, (B) is used automatically from the PDF's embedded subset.
# ---------------------------------------------------------------------------

_TIBETAN_MIN = 0x0F00
_TIBETAN_MAX = 0x0FFF


def _is_tibetan(s: str) -> bool:
    return bool(s) and all(_TIBETAN_MIN <= ord(c) <= _TIBETAN_MAX for c in s)


def _get_font_paths() -> list[Path]:
    """
    Return a list of font file paths from config.

    ``FONT_DIR`` in config.py can be:
      - A directory Path: all .ttf/.otf files under it (recursively) are candidates.
      - A single .ttf/.otf file Path: used directly.
      - A list of file/directory Paths: each entry is handled as above.
      - None: returns an empty list (GSUB correction disabled).

    This tolerates the common mistake of pointing FONT_DIR at the .ttf file
    itself rather than its parent directory.
    """
    try:
        from config import FONT_DIR  # type: ignore
    except (ImportError, AttributeError):
        return []

    if FONT_DIR is None:
        return []

    # Normalise to list
    entries = FONT_DIR if isinstance(FONT_DIR, (list, tuple)) else [FONT_DIR]
    paths: list[Path] = []
    for entry in entries:
        p = Path(entry)
        if p.is_dir():
            paths.extend(
                f
                for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in (".ttf", ".otf")
            )
        elif p.is_file() and p.suffix.lower() in (".ttf", ".otf"):
            paths.append(p)
        else:
            logger.debug("_get_font_paths: skipping non-existent or unsupported path: %s", p)
    return paths


def _find_font_file(basefont_name: str) -> Optional[Path]:
    """
    Find the font file whose stem matches *basefont_name*.

    Strips the PDF subset prefix (e.g. "FPDEGJ+MonlamUniOuChan2" → "MonlamUniOuChan2")
    and matches case-insensitively with separators (underscores, hyphens, spaces)
    ignored on both sides, so ``monlam_uni_ouchan2.ttf`` matches ``MonlamUniOuChan2``.
    """
    stem = basefont_name.split("+")[-1] if "+" in basefont_name else basefont_name

    def _norm(s: str) -> str:
        return s.lower().replace("_", "").replace("-", "").replace(" ", "")

    target = _norm(stem)
    for font_path in _get_font_paths():
        if _norm(font_path.stem) == target:
            return font_path
    return None


def _parse_tounicode_cmap(cmap_text: str) -> dict[int, str]:
    """
    Parse a PDF ToUnicode CMap stream into {glyph_id: unicode_string}.

    Handles bfchar, bfrange (linear), and bfrange (array) forms.
    """
    result: dict[int, str] = {}

    for m in re.finditer(r"<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]+)>", cmap_text):
        gid = int(m.group(1), 16)
        uni_hex = m.group(2)
        result[gid] = "".join(
            chr(int(uni_hex[i: i + 4], 16)) for i in range(0, len(uni_hex), 4)
        )

    for m in re.finditer(
        r"<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]+)>", cmap_text
    ):
        start, end = int(m.group(1), 16), int(m.group(2), 16)
        base_hex = m.group(3)
        if len(base_hex) == 4:
            base_cp = int(base_hex, 16)
            for i in range(end - start + 1):
                result[start + i] = chr(base_cp + i)

    for m in re.finditer(
        r"<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]{2,4})>\s+\[<([^>]+)>", cmap_text
    ):
        start = int(m.group(1), 16)
        uni_hex = m.group(3)
        result[start] = "".join(
            chr(int(uni_hex[i: i + 4], 16)) for i in range(0, len(uni_hex), 4)
        )

    return result


def _compute_fuzzy_hash(tt, glyph_name: str, resolution: int = 6) -> Optional[str]:
    """
    Resolution-6 fuzzy outline hash for glyph matching across GID spaces.

    Because subset fonts renumber GIDs relative to the full font, we cannot
    match by GID.  Instead we hash the normalised glyph outline: same shape
    → same hash regardless of which font or GID the glyph came from.
    """
    from hashlib import sha256
    try:
        if "glyf" not in tt:
            return None
        glyf_tbl = tt["glyf"]
        g = glyf_tbl[glyph_name]
        coords, end_pts, flags = g.getCoordinates(glyf_tbl)
    except Exception:
        return None
    upem = tt["head"].unitsPerEm
    if not coords:
        return None
    norm = [(x / upem, y / upem) for x, y in coords]
    min_x = min(p[0] for p in norm)
    min_y = min(p[1] for p in norm)
    norm = [(x - min_x, y - min_y) for x, y in norm]
    cends = set(end_pts)
    parts: list[str] = []
    for i, (x, y) in enumerate(norm):
        rx = round(x * resolution) / resolution
        ry = round(y * resolution) / resolution
        parts.append(f"{rx:.4f},{ry:.4f},{flags[i] & 1}")
        if i in cends:
            parts.append("|")
    return sha256(";".join(parts).encode()).hexdigest()


def _build_cmap_corrections(
    font_bytes: bytes,
    basefont: str,
    cmap_gid_to_unicode: dict[int, str],
) -> dict[int, str]:
    """
    Return {gid: correct_unicode} for every GID in the PDF font whose CMap
    value is absent or wrong (non-Tibetan for a Tibetan font).

    Algorithm
    ---------
    PDF subset fonts renumber glyphs starting from 0, so subset GID N has no
    relation to full font GID N.  Matching by GID number across the two fonts
    produces wrong results.  Instead we match by *glyph outline shape*:

    1. Load the full font from FONT_DIR and build a GSUB-derived map:
           glyph_name → correct_unicode   (from GSUB inversion)
    2. Build a fuzzy-hash → correct_unicode table from the full font:
           sha256(normalised_outline) → unicode
    3. Iterate the SUBSET font's glyph_order (same GID numbering as the PDF CMap):
       For each GID whose CMap entry is absent or non-Tibetan:
         a. Compute the fuzzy hash of that glyph's outline in the SUBSET font
         b. Look up the hash in the full font's table
         c. If found → record as a correction for that GID

    Returns an empty dict if fontTools / gsub_resolver are unavailable or if
    no full font is found in FONT_DIR (subset-only mode yields no corrections
    because the subset font itself lacks cmap+GSUB tables).
    """
    if not FONTTOOLS_AVAILABLE or not GSUB_RESOLVER_AVAILABLE:
        return {}

    # ── Load full font (GSUB source) ────────────────────────────────────────
    full_font = None
    font_file = _find_font_file(basefont)
    if font_file:
        try:
            full_font = _ttLib.TTFont(str(font_file))
        except Exception as exc:
            logger.debug("_build_cmap_corrections: failed to load %s: %s", font_file, exc)

    if full_font is None:
        logger.debug(
            "_build_cmap_corrections: no full font for %s — skipping GSUB correction",
            basefont,
        )
        return {}

    # ── Build GSUB-derived map from the full font ────────────────────────────
    # Pass an empty cmap_gid_to_unicode so build_glyph_unicode_map uses only
    # the full font's own cmap + GSUB, not the (unrelated) PDF subset CMap.
    glyph_map = build_glyph_unicode_map(full_font, {})

    # ── Build full-font hash table: outline_hash → unicode ──────────────────
    full_hash_table: dict[str, str] = {}
    for glyph_name, unicode_str in glyph_map.items():
        if not _is_tibetan(unicode_str):
            continue
        fh = _compute_fuzzy_hash(full_font, glyph_name)
        if fh:
            full_hash_table[fh] = unicode_str

    logger.debug(
        "_build_cmap_corrections: full font hash table has %d Tibetan entries for %s",
        len(full_hash_table), basefont,
    )

    if not full_hash_table:
        return {}

    # ── Load subset font (PDF GID space) ────────────────────────────────────
    subset_font = None
    if font_bytes:
        try:
            subset_font = _ttLib.TTFont(io.BytesIO(font_bytes))
        except Exception as exc:
            logger.debug("_build_cmap_corrections: failed to load subset: %s", exc)

    if subset_font is None:
        return {}

    subset_order = subset_font.getGlyphOrder()

    # ── Match each subset GID by shape against the full font ────────────────
    corrections: dict[int, str] = {}
    for gid, glyph_name in enumerate(subset_order):
        current_uni = cmap_gid_to_unicode.get(gid)
        if current_uni is not None and _is_tibetan(current_uni):
            continue  # already correct in CMap

        fh = _compute_fuzzy_hash(subset_font, glyph_name)
        if not fh:
            continue

        resolved = full_hash_table.get(fh)
        if resolved and _is_tibetan(resolved):
            corrections[gid] = resolved
            logger.debug(
                "_build_cmap_corrections: GID 0x%04X (%s) %r → %r  [shape match]",
                gid, glyph_name, current_uni or "MISSING", resolved,
            )

    logger.info(
        "_build_cmap_corrections: %d corrections for %s",
        len(corrections), basefont,
    )
    return corrections


def _patch_cmap_stream(cmap_text: str, corrections: dict[int, str]) -> str:
    """
    Inject *corrections* as additional bfchar entries into a ToUnicode CMap stream.

    The entries are inserted just before ``endcmap`` so they override any
    existing (wrong) mapping for the same GID — PDF CMap resolution uses the
    last matching entry when duplicates exist.
    """
    if not corrections:
        return cmap_text

    entries = [f"<{gid:04x}> <{''.join(f'{ord(c):04x}' for c in uni)}>"
               for gid, uni in sorted(corrections.items())]
    patch = f"\n{len(entries)} beginbfchar\n" + "\n".join(entries) + "\nendbfchar\n"
    return cmap_text.replace("endcmap", patch + "endcmap")


def _patch_font_cmaps(doc) -> None:
    """
    Patch all ToUnicode CMap streams in *doc* in-memory before text extraction.

    Iterates every Identity-H (Unicode CID) font in the document, builds the
    correction map via gsub_resolver, and rewrites any CMap streams that contain
    wrong mappings.  Each unique font xref is processed only once.

    This must be called once per document, before any call to page.get_text().
    After patching, PyMuPDF decodes characters correctly from the amended CMap
    without any further per-character post-processing.
    """
    if not FONTTOOLS_AVAILABLE or not GSUB_RESOLVER_AVAILABLE:
        return

    patched_tou_xrefs: set[int] = set()

    for pn in range(len(doc)):
        page = doc[pn]
        for font_entry in page.get_fonts(full=True):
            font_xref = font_entry[0]
            enc = font_entry[5]

            if enc != "Identity-H":
                continue  # only Unicode CID fonts need patching

            basefont = font_entry[3]
            font_obj = doc.xref_object(font_xref, compressed=False)

            tou_m = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", font_obj)
            if not tou_m:
                continue
            tou_xref = int(tou_m.group(1))

            if tou_xref in patched_tou_xrefs:
                continue  # already patched this CMap

            # Get font bytes (subset embedded in PDF)
            font_bytes = b""
            desc_m = re.search(r"/DescendantFonts\s*\[\s*(\d+)", font_obj)
            if desc_m:
                desc_obj = doc.xref_object(int(desc_m.group(1)), compressed=False)
                fd_m = re.search(r"/FontDescriptor\s+(\d+)", desc_obj)
                if fd_m:
                    fd_obj = doc.xref_object(int(fd_m.group(1)), compressed=False)
                    ff2_m = re.search(r"/FontFile2\s+(\d+)", fd_obj)
                    if ff2_m:
                        try:
                            font_bytes = doc.xref_stream(int(ff2_m.group(1)))
                        except Exception:
                            pass

            # Parse existing CMap
            try:
                cmap_text = doc.xref_stream(tou_xref).decode("latin-1", "replace")
            except Exception as exc:
                logger.debug("_patch_font_cmaps: cannot read CMap xref=%d: %s", tou_xref, exc)
                continue

            cmap_gid_to_unicode = _parse_tounicode_cmap(cmap_text)

            # Build corrections
            corrections = _build_cmap_corrections(font_bytes, basefont, cmap_gid_to_unicode)

            if corrections:
                patched_text = _patch_cmap_stream(cmap_text, corrections)
                try:
                    doc.update_stream(tou_xref, patched_text.encode("latin-1"))
                    logger.info(
                        "_patch_font_cmaps: patched %d GIDs in CMap xref=%d (%s)",
                        len(corrections), tou_xref, basefont,
                    )
                except Exception as exc:
                    logger.warning(
                        "_patch_font_cmaps: failed to update CMap xref=%d: %s",
                        tou_xref, exc,
                    )

            patched_tou_xrefs.add(tou_xref)


# ---------------------------------------------------------------------------
# Fix 6 — Dedris / TibetanMachine legacy font decoding
# ---------------------------------------------------------------------------

def _build_dedris_font_set(doc) -> set[str]:
    """
    Scan every font in *doc* and return the set of **stripped basefont names**
    (subset prefix removed, e.g. ``"TT1EA4o00"``) that belong to the
    TibetanMachine / Dedris legacy font family.

    PyMuPDF's span ``'font'`` field already contains the stripped name, so this
    set can be used directly as a membership test in ``_extract_line_text``.

    For detection, we assemble the full font context from three PDF objects:
      - The font dict itself  (references to FontDescriptor + Encoding)
      - The FontDescriptor    (contains /FontBBox and /CharSet)
      - The Encoding object   (contains /WinAnsiEncoding or /Differences)
    This is necessary because neither /CharSet nor /WinAnsiEncoding appear in
    the top-level font dict; they live one level down in the sub-objects.
    """
    if not DEDRIS_RESOLVER_AVAILABLE:
        return set()

    dedris_names: set[str] = set()
    seen_xrefs: set[int] = set()

    for pn in range(len(doc)):
        page = doc[pn]
        for font_entry in page.get_fonts(full=True):
            font_xref = font_entry[0]
            if font_xref in seen_xrefs:
                continue
            seen_xrefs.add(font_xref)

            enc = font_entry[5]
            # Quick skip: Identity-H fonts are Monlam/Unicode, never Dedris
            if enc == "Identity-H":
                continue

            try:
                font_obj = doc.xref_object(font_xref, compressed=False)
            except Exception:
                continue

            # Assemble full context: font obj + FontDescriptor + Encoding object.
            # CharSet (for Latin-glyph filter) lives in FontDescriptor;
            # WinAnsiEncoding lives in the referenced Encoding object.
            context_parts = [font_obj]

            fd_m = re.search(r"/FontDescriptor\s+(\d+)\s+0\s+R", font_obj)
            if fd_m:
                try:
                    context_parts.append(doc.xref_object(int(fd_m.group(1)), compressed=False))
                except Exception:
                    pass

            enc_m = re.search(r"/Encoding\s+(\d+)\s+0\s+R", font_obj)
            if enc_m:
                try:
                    context_parts.append(doc.xref_object(int(enc_m.group(1)), compressed=False))
                except Exception:
                    pass

            full_context = "\n".join(context_parts)

            if is_dedris_font(full_context):
                raw_basefont = font_entry[3]  # e.g. "TWPWAV+TT1EA4o00"
                stripped = raw_basefont.split("+")[-1] if "+" in raw_basefont else raw_basefont
                logger.debug(
                    "_build_dedris_font_set: Dedris font xref=%d (%s → %s)",
                    font_xref, raw_basefont, stripped,
                )
                dedris_names.add(stripped)

    if dedris_names:
        logger.info(
            "_build_dedris_font_set: %d Dedris font name(s) detected: %s",
            len(dedris_names),
            ", ".join(sorted(dedris_names)),
        )
    return dedris_names


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

def create_cropped_pdf(
    pdf_path: Path,
    preserve_rect: Optional[Tuple[float, float, float, float]],
) -> Optional[Path]:
    """
    Return a temp PDF with everything *outside* ``preserve_rect`` physically
    redacted (text removed, white fill).

    ``preserve_rect`` is ``(x0, y0, x1, y1)`` as **fractions of page size**
    (0.0–1.0) — the region to **keep**.  Matches the coordinate format from
    https://buddhist.tools/pdf-cropper and from ``margin_detector.detect_margins()``.

    If ``preserve_rect`` is ``None``, ``detect_margins()`` is called first to
    derive the rect automatically from repeated text bands across pages.
    Pass an empty tuple ``()`` to disable redaction entirely (--preserve-rect none).

    Returns ``None`` (no temp file created) when:
    - preserve_rect is an empty tuple (redaction disabled), or
    - auto-detection finds no margins, or
    - PyMuPDF is unavailable.
    """
    if not PYMUPDF_AVAILABLE:
        logger.warning(
            "Margin redaction requested but PyMuPDF is not installed. "
            "pip install pymupdf — continuing without redaction."
        )
        return None

    # ── resolve the preserve rect ────────────────────────────────────────────
    # Empty tuple is the sentinel for "disable all redaction" (--preserve-rect none).
    if isinstance(preserve_rect, tuple) and len(preserve_rect) == 0:
        return None

    if preserve_rect is None:
        try:
            from margin_detector import detect_margins
            preserve_rect = detect_margins(pdf_path)
        except ImportError:
            logger.warning("create_cropped_pdf: margin_detector.py not found — skipping redaction.")
            return None

    if preserve_rect is None:
        logger.info("create_cropped_pdf: no margins detected — using full page.")
        return None

    fx0, fy0, fx1, fy1 = preserve_rect

    try:
        doc = fitz.open(str(pdf_path))

        for page in doc:
            r = page.rect
            w, h = r.width, r.height

            # Convert fractions to absolute pts for this page
            px0 = r.x0 + fx0 * w
            py0 = r.y0 + fy0 * h
            px1 = r.x0 + fx1 * w
            py1 = r.y0 + fy1 * h

            any_redaction = False
            # Only redact bands that are non-trivially wide/tall (> 0.5 pt)
            if py0 > r.y0 + 0.5:                          # top band
                page.add_redact_annot(fitz.Rect(r.x0, r.y0, r.x1, py0))
                any_redaction = True
            if py1 < r.y1 - 0.5:                          # bottom band
                page.add_redact_annot(fitz.Rect(r.x0, py1, r.x1, r.y1))
                any_redaction = True
            if px0 > r.x0 + 0.5:                          # left band
                page.add_redact_annot(fitz.Rect(r.x0, r.y0, px0, r.y1))
                any_redaction = True
            if px1 < r.x1 - 0.5:                          # right band
                page.add_redact_annot(fitz.Rect(px1, r.y0, r.x1, r.y1))
                any_redaction = True

            if any_redaction:
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
            "    Redacted temp PDF: %s  preserve_rect=(%.4f, %.4f, %.4f, %.4f)  [fractions]",
            tmp_path.name, fx0, fy0, fx1, fy1,
        )
        return tmp_path

    except Exception as e:
        logger.warning(
            "    Failed to redact margins on %s: %s — using original PDF.", pdf_path.name, e
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
    preserve_rect: Optional[Tuple[float, float, float, float]] = None,
) -> str:
    """
    Extract via ``pytiblegenc.pdf_to_txt`` (same options as IE3KG664 / Desktop SRC_CODE).
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
        tmp_pdf = create_cropped_pdf(pdf_path, preserve_rect)
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


# ---------------------------------------------------------------------------
# Fix 1, 3, 4 — Phantom space detection
# ---------------------------------------------------------------------------
_PHANTOM_SPACE_ADVANCE_THRESHOLD = 1.5  # points


def _is_phantom_space(char_obj: dict, prev_char_obj: dict | None) -> bool:
    """
    Return True when *char_obj* is a phantom glyph-advance space.

    A space is phantom iff it does not advance rightward by at least
    ``_PHANTOM_SPACE_ADVANCE_THRESHOLD`` points from the preceding glyph.
    """
    if char_obj.get("c") != " ":
        return False
    if prev_char_obj is None:
        return False
    space_x = char_obj.get("origin", (0, 0))[0]
    prev_x = prev_char_obj.get("origin", (0, 0))[0]
    return space_x < prev_x + _PHANTOM_SPACE_ADVANCE_THRESHOLD


def _extract_line_text(line: dict, dedris_fonts: set[str] | None = None) -> list[str]:
    """
    Extract text fragments from a single MuPDF ``line`` dict.

    Returns a list of strings (font-size tags interleaved with text characters).
    Wingdings fonts are skipped entirely.

    Fixes applied
    -------------
    Fix 1+3+4 — Phantom spaces: dropped when space_x < prev_x + threshold.
    ``span_prev_char_obj`` is threaded across span boundaries (Fix 3) so
    cross-span phantoms are also caught.

    Fix 2 is handled upstream by ``_patch_font_cmaps()``, which rewrites the
    document's ToUnicode CMap streams before extraction, so PyMuPDF already
    returns the correct Tibetan codepoints here.

    Fix 6 — Dedris decoding: if a span's font name is in *dedris_fonts*, the
    full span text is decoded via ``decode_tibetan_machine`` instead of being
    emitted char-by-char.  This handles the multi-font-subset pattern used by
    TibetanMachine PDFs where one Tibetan cluster is split across several tiny
    Type1 font subsets.
    """
    fragments: list[str] = []
    span_prev_char_obj: dict | None = None

    for span in line.get("spans", []):
        font_name = span.get("font") or ""
        if _is_wingdings_font(font_name):
            continue

        fs = round(span.get("size", 12))
        fragments.append(_FONT_SIZE_FORMAT.format(fs))

        # Fix 6: Dedris / TibetanMachine span-level decode.
        # Build span text from individual char objects (span["text"] is None
        # in PyMuPDF rawdict mode — only span["chars"][i]["c"] has the values).
        if dedris_fonts and font_name in dedris_fonts:
            char_objs = span.get("chars") or []
            span_text = "".join(c.get("c", "") for c in char_objs)
            if not span_text:
                span_text = span.get("text") or ""  # fallback for non-rawdict
            if span_text:
                decoded = decode_tibetan_machine(span_text)
                if should_decode_span(span_text, decoded):
                    fragments.append(decoded)
                else:
                    fragments.append(span_text)
            span_prev_char_obj = None
            continue

        char_objs = span.get("chars") or []
        if char_objs:
            for char_obj in char_objs:
                # Fix 1+3+4: drop phantom glyph-advance spaces
                if _is_phantom_space(char_obj, span_prev_char_obj):
                    continue
                fragments.append(char_obj.get("c", ""))
                span_prev_char_obj = char_obj
        else:
            fragments.append(span.get("text") or "")
            span_prev_char_obj = None

    return fragments


# ---------------------------------------------------------------------------
# Fix 5 — Duplicate text-layer deduplication
# ---------------------------------------------------------------------------
_FS_TAG_RE = re.compile(r"<fs:\d+>")
_DEDUP_X_BUCKET_PT = 3.0
_ZW_STRIP_FOR_DEDUP_KEY = dict.fromkeys(
    map(ord, "\u200B\u200C\u200D\u2060\uFEFF\u034F\u180E")
)


def _text_key_for_dedup(frags: list[str]) -> str:
    """
    Build a comparison string so two overlapping PDF text layers dedupe together.

    Duplicate CJK/Latin colophon lines often differ across layers in: NFC vs NFD,
    U+3000 ideographic space vs ASCII space, or zero-width characters from HTML
    paste.  Tibetan-only lines behave as before when the grapheme string matches.
    """
    raw = _FS_TAG_RE.sub("", "".join(frags))
    raw = raw.translate(_ZW_STRIP_FOR_DEDUP_KEY)
    raw = unicodedata.normalize("NFC", raw)
    raw = raw.replace("\u3000", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _deduplicate_raw_lines(
    raw_lines: list[tuple[float, float, list[str]]],
    y_tolerance: float,
) -> list[tuple[float, float, list[str]]]:
    """Remove duplicate raw lines from InDesign overlapping text layers."""
    seen: set[tuple[float, float, str]] = set()
    deduped: list[tuple[float, float, list[str]]] = []
    xb = _DEDUP_X_BUCKET_PT
    for y_mid, x0, frags in raw_lines:
        y_bucket = round(y_mid / y_tolerance) * y_tolerance
        x_bucket = round(x0 / xb) * xb
        text_key = _text_key_for_dedup(frags)
        key = (y_bucket, x_bucket, text_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((y_mid, x0, frags))
    return deduped


_BLOCK_LEFT_MARGIN_TOLERANCE  = 50.0   # pts: left margin gap is clean, tight tolerance
_BLOCK_RIGHT_MARGIN_TOLERANCE = 100.0   # pts: right margin overlaps body, wider tolerance
_BLOCK_BOTTOM_TOLERANCE       = 100.0   # pts: allow blocks that extend slightly past bottom
_BLOCK_NARROW_MAX_WIDTH       = 50.0   # pts: blocks narrower than this are margin candidates


def _should_keep_block(
    block: dict,
    page_w: float,
    page_h: float,
    preserve_rect: Tuple[float, float, float, float],
) -> bool:
    """
    Return False for margin blocks (folio, section label, page number, title column)
    that should be excluded from extraction.

    Uses block geometry relative to the preserve rect rather than physical redaction,
    which avoids clipping body characters that bleed into the margin column x-range.

    Rules (all must pass to keep the block):
    - Narrow blocks (< 40pt wide) whose right edge sits within 5pt of the body
      left edge are left-margin content (folio letters, section labels).
    - Narrow blocks whose left edge sits within 25pt of the body right edge are
      right-margin content (page numbers, running titles). The wider tolerance
      handles PDFs where the right margin column physically overlaps body text.
    - Blocks whose top edge starts more than 10pt below the body bottom edge
      are below-body content (page footers on Western-layout PDFs).
    """
    bx0, by0, bx1, by1 = block["bbox"]
    bw = bx1 - bx0
    px0 = preserve_rect[0] * page_w
    px1 = preserve_rect[2] * page_w
    py1 = preserve_rect[3] * page_h

    if bw < _BLOCK_NARROW_MAX_WIDTH:
        if bx1 < px0 + _BLOCK_LEFT_MARGIN_TOLERANCE:
            return False
        if bx0 > px1 - _BLOCK_RIGHT_MARGIN_TOLERANCE:
            return False
    if by0 > py1 + _BLOCK_BOTTOM_TOLERANCE:
        return False
    return True


_Y_MERGE_TOLERANCE = 3.0

_SHADOW_X_THRESHOLD = 5.0


def _dedup_within_row(
    row: list[tuple[float, float, list[str]]],
) -> list[tuple[float, float, list[str]]]:
    """Remove InDesign shadow copies from one merged visual row (see bulk/pdf_extract)."""
    first_x: dict[str, float] = {}
    result: list[tuple[float, float, list[str]]] = []
    for y, x, frags in row:
        text_key = _text_key_for_dedup(frags)
        if not text_key:
            result.append((y, x, frags))
            continue
        if text_key in first_x:
            if abs(x - first_x[text_key]) <= _SHADOW_X_THRESHOLD:
                continue
        else:
            first_x[text_key] = x
        result.append((y, x, frags))
    return result


def extract_pdf_pymupdf(
    pdf_path: Path,
    *,
    preserve_rect: Optional[Tuple[float, float, float, float]] = None,
) -> str:
    """
    Extract text using PyMuPDF ``rawdict``: one ``\\n`` per **visual** line.

    MuPDF often splits a single visual line into multiple ``line`` objects.
    We merge lines whose Y midpoints are within ``_Y_MERGE_TOLERANCE`` pts,
    sort left-to-right, and apply all six artefact fixes.

    Fix 2 (WinAnsi CMap correction) is applied once before the page loop by
    ``_patch_font_cmaps()``, which rewrites bad ToUnicode CMap entries in-memory
    so all subsequent page.get_text() calls decode characters correctly.

    Fix 6 (Dedris / TibetanMachine decoding) is applied per-span: fonts belonging
    to the TibetanMachine family are detected once via ``_build_dedris_font_set()``
    and their span text is decoded via ``decode_tibetan_machine()`` at extraction
    time, before any downstream normalisation.

    Margin redaction is handled by ``create_cropped_pdf()``, which accepts a
    ``preserve_rect=(x0, y0, x1, y1)`` in PDF points.  Pass ``None`` (default)
    to auto-detect margins via ``margin_detector.detect_margins()``.
    """
    logger.info(f"    Extracting (PyMuPDF rawdict): {pdf_path.name}")

    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF is required for --extractor pymupdf. pip install pymupdf")
        return ""

    tmp_pdf: Optional[Path] = None

    try:
        tmp_pdf = create_cropped_pdf(pdf_path, preserve_rect)

        target_pdf = tmp_pdf if tmp_pdf else pdf_path
        doc = fitz.open(str(target_pdf))

        # Fix 2: patch all bad ToUnicode CMap entries before any page extraction
        _patch_font_cmaps(doc)

        # Fix 6: build Dedris font name set once for the whole document
        dedris_fonts = _build_dedris_font_set(doc)

        parts: list[str] = []

        for page in doc:
            page_dict = page.get_text("rawdict")
            pw, ph = page.rect.width, page.rect.height

            # Resolve the effective preserve rect for block filtering.
            # If physical redaction was applied (tmp_pdf), we still filter blocks
            # so that margin content overlapping the body x-range is excluded.
            effective_rect = preserve_rect
            if effective_rect is None or (isinstance(effective_rect, tuple) and len(effective_rect) == 0):
                effective_rect = None

            raw_lines: list[tuple[float, float, list[str]]] = []

            for block in page_dict.get("blocks", []):
                if block.get("type", 1) != 0:
                    continue
                if effective_rect and not _should_keep_block(block, pw, ph, effective_rect):
                    continue
                for line in block.get("lines", []):
                    bbox = line.get("bbox", [0, 0, 0, 0])
                    y_mid = (bbox[1] + bbox[3]) / 2.0
                    x0 = bbox[0]
                    fragments = _extract_line_text(line, dedris_fonts=dedris_fonts)
                    if fragments:
                        raw_lines.append((y_mid, x0, fragments))

            # Fix 5: remove duplicate lines from overlapping PDF text layers
            if raw_lines:
                raw_lines = _deduplicate_raw_lines(raw_lines, _Y_MERGE_TOLERANCE)

            raw_lines.sort(key=lambda t: (t[0], t[1]))

            merged_rows: list[list[tuple[float, float, list[str]]]] = []
            for y_mid, x0, frags in raw_lines:
                if merged_rows:
                    avg_y = sum(e[0] for e in merged_rows[-1]) / len(merged_rows[-1])
                    if abs(y_mid - avg_y) <= _Y_MERGE_TOLERANCE:
                        merged_rows[-1].append((y_mid, x0, frags))
                        continue
                merged_rows.append([(y_mid, x0, frags)])

            for row in merged_rows:
                row.sort(key=lambda t: t[1])
                row = _dedup_within_row(row)
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
    preserve_rect: Optional[Tuple[float, float, float, float]] = None,
) -> str:
    """Dispatch to PyMuPDF or pytiblegenc.

    ``preserve_rect`` is ``(x0, y0, x1, y1)`` in PDF points — the region to
    keep after margin redaction.  Pass ``None`` (default) to auto-detect via
    ``margin_detector.detect_margins()``.
    """
    if extractor == "pytiblegenc":
        return extract_pdf_pytiblegenc(pdf_path, preserve_rect=preserve_rect)
    return extract_pdf_pymupdf(pdf_path, preserve_rect=preserve_rect)