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
  5. Duplicate text-layer deduplication for InDesign-generated PDFs
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import traceback
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

logger = logging.getLogger(__name__)

PAGE_BREAK_STR = "ZZZZ"
_FONT_SIZE_FORMAT = "<fs:{}>"


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
      - A directory Path: all .ttf/.otf files inside it are candidates.
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
            paths.extend(f for f in p.iterdir() if f.suffix.lower() in (".ttf", ".otf"))
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
# Infrastructure
# ---------------------------------------------------------------------------

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
                page.add_redact_annot(fitz.Rect(r.x0, r.y0, r.x1, r.y0 + h * top_frac))
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
        if crop_top > 0.0 or crop_bottom > 0.0:
            tmp_pdf = create_cropped_pdf(pdf_path, crop_top, crop_bottom)
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


def _extract_line_text(line: dict) -> list[str]:
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
    """
    fragments: list[str] = []
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


def _deduplicate_raw_lines(
    raw_lines: list[tuple[float, float, list[str]]],
    y_tolerance: float,
) -> list[tuple[float, float, list[str]]]:
    """Remove duplicate raw lines from InDesign overlapping text layers."""
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


_Y_MERGE_TOLERANCE = 3.0


def extract_pdf_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
) -> str:
    """
    Extract text using PyMuPDF ``rawdict``: one ``\\n`` per **visual** line.

    MuPDF often splits a single visual line into multiple ``line`` objects.
    We merge lines whose Y midpoints are within ``_Y_MERGE_TOLERANCE`` pts,
    sort left-to-right, and apply all five artefact fixes.

    Fix 2 (WinAnsi CMap correction) is applied once before the page loop by
    ``_patch_font_cmaps()``, which rewrites bad ToUnicode CMap entries in-memory
    so all subsequent page.get_text() calls decode characters correctly.
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

        # Fix 2: patch all bad ToUnicode CMap entries before any page extraction
        _patch_font_cmaps(doc)

        parts: list[str] = []

        for page in doc:
            page_dict = page.get_text("rawdict")

            raw_lines: list[tuple[float, float, list[str]]] = []

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