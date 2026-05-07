"""
PDF text extraction for Monlam-font PDFs: PyMuPDF ``rawdict`` or ``pytiblegenc.pdf_to_txt``.

Line breaks are layout-level (one ``\n`` per extractor line); ``PAGE_BREAK_STR`` marks pages.

Fixes applied (PyMuPDF path):
  1. Phantom space detection — space_x < prev_x + threshold
  2. WinAnsi vowel glyph mis-mappings — resolved via gsub_resolver (GSUB inversion +
     fuzzy shape matching).  ToUnicode CMap is patched in-memory before extraction.
     Set FONT_DIR in config.py to enable GSUB inversion from the full .ttf file.
  3. Phantom space check threaded across span boundaries
  4. Epsilon tolerance for near-zero-advance phantom spaces from WinAnsi vowel spans
  5. Duplicate text-layer deduplication for InDesign PDFs (NFC + ZW strip +
     whitespace / U+3000 normalisation; looser x-bucketing for CJK)
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
import traceback
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

# Footnote sentinels (consumed by convert_pdf_to_xml.convert_footnote_sentinels_to_tei)
_FN_SENTINEL_START = "ZZFN_START:"
_FN_SENTINEL_END = "ZZFN_END"

_TIBETAN_MIN = 0x0F00
_TIBETAN_MAX = 0x0FFF


def _is_tibetan(s: str) -> bool:
    return bool(s) and all(_TIBETAN_MIN <= ord(c) <= _TIBETAN_MAX for c in s)


# ─── Font path discovery (cached) ──────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_font_paths() -> List[Path]:
    """
    Return font file paths from config.FONT_DIR (cached after the first call).

    FONT_DIR may be a directory, a single .ttf/.otf file, a list of either,
    or None (GSUB correction disabled).
    """
    try:
        from config import FONT_DIR  # type: ignore
    except (ImportError, AttributeError):
        return []

    if FONT_DIR is None:
        return []

    entries = FONT_DIR if isinstance(FONT_DIR, (list, tuple)) else [FONT_DIR]
    paths: List[Path] = []
    for entry in entries:
        p = Path(entry)
        if p.is_dir():
            paths.extend(
                f for f in p.rglob("*")
                if f.is_file() and f.suffix.lower() in (".ttf", ".otf")
            )
        elif p.is_file() and p.suffix.lower() in (".ttf", ".otf"):
            paths.append(p)
        else:
            logger.debug("_get_font_paths: skipping non-existent or unsupported path: %s", p)
    return paths


@lru_cache(maxsize=64)
def _find_font_file(basefont_name: str) -> Optional[Path]:
    """
    Find a font file whose stem matches *basefont_name* (case-insensitive,
    separators ignored).  Strips the PDF subset prefix (e.g. "FPDEGJ+…").
    Cached per basefont name.
    """
    stem = basefont_name.split("+")[-1] if "+" in basefont_name else basefont_name

    def _norm(s: str) -> str:
        return s.lower().replace("_", "").replace("-", "").replace(" ", "")

    target = _norm(stem)
    for font_path in _get_font_paths():
        if _norm(font_path.stem) == target:
            return font_path
    return None


# ─── Fix 2 — GSUB-based CMap patching ──────────────────────────────────────────

def _parse_tounicode_cmap(cmap_text: str) -> Dict[int, str]:
    """Parse a PDF ToUnicode CMap stream into {glyph_id: unicode_string}."""
    result: Dict[int, str] = {}

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
    Resolution-6 fuzzy outline hash for cross-GID glyph shape matching.

    Delegates to gsub_resolver._compute_fuzzy_hash when available; otherwise
    uses a local fallback so this module stays self-contained.
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
    scaled = [(x / upem, y / upem) for x, y in coords]
    cends = set(end_pts)
    parts: List[str] = []
    start = 0
    for end_idx in sorted(cends):
        contour = scaled[start: end_idx + 1]
        cx = min(p[0] for p in contour)
        cy = min(p[1] for p in contour)
        for j, (x, y) in enumerate(contour):
            rx = round((x - cx) * resolution) / resolution
            ry = round((y - cy) * resolution) / resolution
            parts.append(f"{rx:.4f},{ry:.4f},{flags[start + j] & 1}")
        parts.append("|")
        start = end_idx + 1
    return sha256(";".join(parts).encode()).hexdigest()


def _build_cmap_corrections(
    font_bytes: bytes,
    basefont: str,
    cmap_gid_to_unicode: Dict[int, str],
) -> Dict[int, str]:
    """
    Return {gid: correct_unicode} for GIDs whose CMap value is absent or wrong.

    Matches subset GIDs to full-font glyphs by outline shape (fuzzy hash) since
    subsetting renumbers GIDs and makes direct GID comparison unreliable.
    """
    if not FONTTOOLS_AVAILABLE or not GSUB_RESOLVER_AVAILABLE:
        return {}

    font_file = _find_font_file(basefont)
    if not font_file:
        logger.debug(
            "_build_cmap_corrections: no full font for %s — skipping GSUB correction", basefont
        )
        return {}

    try:
        full_font = _ttLib.TTFont(str(font_file))
    except Exception as exc:
        logger.debug("_build_cmap_corrections: failed to load %s: %s", font_file, exc)
        return {}

    # Build GSUB-derived map from the full font (ignore PDF subset CMap)
    glyph_map = build_glyph_unicode_map(full_font, {})

    # Build full-font hash table: outline_hash → unicode
    full_hash_table: Dict[str, str] = {}
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

    if not font_bytes:
        return {}
    try:
        subset_font = _ttLib.TTFont(io.BytesIO(font_bytes))
    except Exception as exc:
        logger.debug("_build_cmap_corrections: failed to load subset: %s", exc)
        return {}

    subset_order = subset_font.getGlyphOrder()
    corrections: Dict[int, str] = {}
    for gid, glyph_name in enumerate(subset_order):
        current_uni = cmap_gid_to_unicode.get(gid)
        if current_uni is not None and _is_tibetan(current_uni):
            continue  # already correct

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

    logger.info("_build_cmap_corrections: %d corrections for %s", len(corrections), basefont)
    return corrections


def _patch_cmap_stream(cmap_text: str, corrections: Dict[int, str]) -> str:
    """Inject *corrections* as bfchar entries into a ToUnicode CMap stream."""
    if not corrections:
        return cmap_text
    entries = [
        f"<{gid:04x}> <{''.join(f'{ord(c):04x}' for c in uni)}>"
        for gid, uni in sorted(corrections.items())
    ]
    patch = f"\n{len(entries)} beginbfchar\n" + "\n".join(entries) + "\nendbfchar\n"
    return cmap_text.replace("endcmap", patch + "endcmap")


def _patch_font_cmaps(doc) -> None:
    """
    Patch all ToUnicode CMap streams in *doc* in-memory before text extraction.

    Must be called once per document, before any page.get_text() call.
    After patching, PyMuPDF decodes characters correctly without per-character
    post-processing.
    """
    if not FONTTOOLS_AVAILABLE or not GSUB_RESOLVER_AVAILABLE:
        return

    patched_tou_xrefs: set[int] = set()

    for pn in range(len(doc)):
        page = doc[pn]
        for font_entry in page.get_fonts(full=True):
            font_xref = font_entry[0]
            if font_entry[5] != "Identity-H":
                continue

            basefont = font_entry[3]
            font_obj = doc.xref_object(font_xref, compressed=False)

            tou_m = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", font_obj)
            if not tou_m:
                continue
            tou_xref = int(tou_m.group(1))
            if tou_xref in patched_tou_xrefs:
                continue

            # Extract embedded subset font bytes
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

            try:
                cmap_text = doc.xref_stream(tou_xref).decode("latin-1", "replace")
            except Exception as exc:
                logger.debug("_patch_font_cmaps: cannot read CMap xref=%d: %s", tou_xref, exc)
                continue

            cmap_gid_to_unicode = _parse_tounicode_cmap(cmap_text)
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
                        "_patch_font_cmaps: failed to update CMap xref=%d: %s", tou_xref, exc,
                    )

            patched_tou_xrefs.add(tou_xref)


# ─── Infrastructure ─────────────────────────────────────────────────────────────

def create_cropped_pdf(pdf_path: Path, top_frac: float, bottom_frac: float) -> Optional[Path]:
    """Return a temp PDF with header/footer bands physically redacted."""
    if top_frac == 0.0 and bottom_frac == 0.0:
        return None
    if not PYMUPDF_AVAILABLE:
        logger.warning(
            "Header/footer redaction requested but PyMuPDF is not installed — "
            "continuing without redaction."
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
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=tempfile.gettempdir())
        tmp_path = Path(tmp.name)
        tmp.close()
        doc.save(str(tmp_path), garbage=4, deflate=True)
        doc.close()
        logger.info(
            "Redacted temp PDF: %s (top=%.1f%%, bottom=%.1f%%)",
            tmp_path.name, top_frac * 100, bottom_frac * 100,
        )
        return tmp_path
    except Exception as e:
        logger.warning("Failed to redact header/footer on %s: %s — using original.", pdf_path.name, e)
        return None


def _is_wingdings_font(font_name: str) -> bool:
    if not font_name:
        return False
    base = font_name.split("+")[-1]
    return "wingdings" in base.lower().replace(" ", "")


# ─── Fix 1, 3, 4 — Phantom space detection ─────────────────────────────────────

_PHANTOM_SPACE_ADVANCE_THRESHOLD = 1.5  # points


def _is_phantom_space(char_obj: dict, prev_char_obj: Optional[dict]) -> bool:
    """Return True when *char_obj* is a phantom glyph-advance space."""
    if char_obj.get("c") != " " or prev_char_obj is None:
        return False
    space_x = char_obj.get("origin", (0, 0))[0]
    prev_x = prev_char_obj.get("origin", (0, 0))[0]
    return space_x < prev_x + _PHANTOM_SPACE_ADVANCE_THRESHOLD


def _extract_line_text(line: dict) -> List[str]:
    """
    Extract text fragments from a MuPDF ``line`` dict.

    Returns a list of strings (font-size tags interleaved with characters).
    Wingdings fonts are skipped.  Phantom spaces are dropped (Fix 1+3+4).
    """
    fragments: List[str] = []
    span_prev_char_obj: Optional[dict] = None

    for span in line.get("spans", []):
        if _is_wingdings_font(span.get("font") or ""):
            continue
        fs = round(span.get("size", 12))
        fragments.append(_FONT_SIZE_FORMAT.format(fs))
        char_objs = span.get("chars") or []
        if char_objs:
            for char_obj in char_objs:
                if _is_phantom_space(char_obj, span_prev_char_obj):
                    continue
                fragments.append(char_obj.get("c", ""))
                span_prev_char_obj = char_obj
        else:
            fragments.append(span.get("text") or "")
            span_prev_char_obj = None

    return fragments


# ─── Fix 5 — Duplicate text-layer deduplication ────────────────────────────────

_FS_TAG_RE = re.compile(r"<fs:\d+>")
_ZW_STRIP_FOR_DEDUP_KEY = dict.fromkeys(
    map(ord, "\u200B\u200C\u200D\u2060\uFEFF\u034F\u180E")
)

_CJK_RE = re.compile(
    r"[\u2E80-\u2EFF\u2F00-\u2FDF\u3000-\u303F\u3040-\u309F\u30A0-\u30FF"
    r"\u3100-\u312F\u3200-\u32FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    r"\uFE30-\uFE4F\uFF00-\uFFEF\U00020000-\U0002A6DF]"
)

_DEDUP_X_BUCKET_PT = 3.0
_DEDUP_X_BUCKET_CJK_PT = 10.0
_SHADOW_X_THRESHOLD = 5.0
_SHADOW_X_THRESHOLD_CJK = 12.0


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _text_key_for_dedup(frags: List[str]) -> str:
    """Normalised text key for duplicate-layer detection."""
    raw = _FS_TAG_RE.sub("", "".join(frags))
    raw = raw.translate(_ZW_STRIP_FOR_DEDUP_KEY)
    raw = unicodedata.normalize("NFC", raw)
    raw = raw.replace("\u3000", " ")
    raw = re.sub(
        r"[\uFF01-\uFF5E]",
        lambda m: chr(ord(m.group()) - 0xFEE0),
        raw,
    )
    return re.sub(r"\s+", " ", raw).strip()


def _deduplicate_raw_lines(
    raw_lines: List[Tuple[float, float, List[str]]],
    y_tolerance: float,
) -> List[Tuple[float, float, List[str]]]:
    """Remove duplicate raw lines from InDesign overlapping text layers."""
    seen: set = set()
    cjk_y_text_first_x: Dict[Tuple[float, str], float] = {}
    deduped: List[Tuple[float, float, List[str]]] = []

    for y_mid, x0, frags in raw_lines:
        y_bucket = round(y_mid / y_tolerance) * y_tolerance
        text_key = _text_key_for_dedup(frags)
        is_cjk_line = _has_cjk(text_key)

        xb = _DEDUP_X_BUCKET_CJK_PT if is_cjk_line else _DEDUP_X_BUCKET_PT
        x_bucket = round(x0 / xb) * xb
        key = (y_bucket, x_bucket, text_key)
        if key in seen:
            logger.debug(
                "_deduplicate_raw_lines: dropped bucket-dup CJK line y=%.1f x=%.1f %r",
                y_mid, x0, text_key[:40],
            )
            continue
        seen.add(key)

        if is_cjk_line and text_key:
            yt_key = (y_bucket, text_key)
            if yt_key in cjk_y_text_first_x:
                if abs(x0 - cjk_y_text_first_x[yt_key]) <= _DEDUP_X_BUCKET_CJK_PT * 2:
                    logger.debug(
                        "_deduplicate_raw_lines: dropped y-text-dup CJK line y=%.1f "
                        "x=%.1f (first_x=%.1f) %r",
                        y_mid, x0, cjk_y_text_first_x[yt_key], text_key[:40],
                    )
                    continue
            else:
                cjk_y_text_first_x[yt_key] = x0

        deduped.append((y_mid, x0, frags))

    return deduped


_Y_MERGE_TOLERANCE = 3.0


def _dedup_within_row(
    row: List[Tuple[float, float, List[str]]],
) -> List[Tuple[float, float, List[str]]]:
    """Remove InDesign drop-shadow copies within a single merged visual row."""
    first_x: Dict[str, float] = {}
    result: List[Tuple[float, float, List[str]]] = []
    for y, x, frags in row:
        text_key = _text_key_for_dedup(frags)
        if not text_key:
            result.append((y, x, frags))
            continue
        threshold = _SHADOW_X_THRESHOLD_CJK if _has_cjk(text_key) else _SHADOW_X_THRESHOLD
        if text_key in first_x:
            if abs(x - first_x[text_key]) <= threshold:
                logger.debug(
                    "_dedup_within_row: dropped shadow frag x=%.1f (first_x=%.1f) %r",
                    x, first_x[text_key], text_key[:40],
                )
                continue
        else:
            first_x[text_key] = x
        result.append((y, x, frags))
    return result


def _dedup_output_lines(parts: List[str]) -> List[str]:
    """
    Final-pass deduplication on the assembled output line list for a page.

    Catches CJK duplicate lines that survived the earlier two dedup layers
    (e.g. InDesign layers far enough apart in x to land in different merged rows).
    Fast-path exits if no CJK is present.
    """
    combined = "".join(parts)
    if not _has_cjk(combined):
        return parts

    lines = combined.split("\n")
    seen_cjk: set = set()
    result_lines: List[str] = []

    for line in lines:
        if PAGE_BREAK_STR in line:
            seen_cjk.clear()
            result_lines.append(line)
            continue

        stripped = _FS_TAG_RE.sub("", line).strip()
        if not stripped:
            result_lines.append(line)
            continue

        cjk_chars = len(_CJK_RE.findall(stripped))
        if cjk_chars == 0 or cjk_chars / len(stripped) < 0.5:
            result_lines.append(line)
            continue

        key = _text_key_for_dedup([line])
        if key in seen_cjk:
            logger.debug("_dedup_output_lines: suppressed duplicate CJK line %r", key[:60])
            continue
        seen_cjk.add(key)
        result_lines.append(line)

    return ["\n".join(result_lines)]


# ─── Main extractors ────────────────────────────────────────────────────────────

def extract_pdf_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
) -> str:
    """
    Extract text using PyMuPDF ``rawdict``: one ``\n`` per visual line.

    MuPDF may split a visual line across multiple ``line`` objects; we merge
    lines whose Y midpoints are within ``_Y_MERGE_TOLERANCE`` pts, sort
    left-to-right, and apply all artefact fixes.
    """
    logger.info("    Extracting (PyMuPDF rawdict): %s", pdf_path.name)

    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF is required for --extractor pymupdf. pip install pymupdf")
        return ""

    tmp_pdf: Optional[Path] = None
    try:
        if crop_top > 0.0 or crop_bottom > 0.0:
            tmp_pdf = create_cropped_pdf(pdf_path, crop_top, crop_bottom)

        target_pdf = tmp_pdf if tmp_pdf else pdf_path
        doc = fitz.open(str(target_pdf))
        _patch_font_cmaps(doc)

        parts: List[str] = []

        for page in doc:
            page_dict = page.get_text("rawdict")
            raw_lines: List[Tuple[float, float, List[str]]] = []

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

            if raw_lines:
                raw_lines = _deduplicate_raw_lines(raw_lines, _Y_MERGE_TOLERANCE)

            raw_lines.sort(key=lambda t: (t[0], t[1]))

            merged_rows: List[List[Tuple[float, float, List[str]]]] = []
            for y_mid, x0, frags in raw_lines:
                if merged_rows:
                    avg_y = sum(e[0] for e in merged_rows[-1]) / len(merged_rows[-1])
                    if abs(y_mid - avg_y) <= _Y_MERGE_TOLERANCE:
                        merged_rows[-1].append((y_mid, x0, frags))
                        continue
                merged_rows.append([(y_mid, x0, frags)])

            page_parts: List[str] = []
            for row in merged_rows:
                row.sort(key=lambda t: t[1])
                row = _dedup_within_row(row)
                for _y, _x, frags in row:
                    page_parts.extend(frags)
                page_parts.append("\n")

            page_parts = _dedup_output_lines(page_parts)
            parts.extend(page_parts)
            parts.append(f"\n{PAGE_BREAK_STR}\n")

        doc.close()
        return "".join(parts)

    except Exception as e:
        logger.error("    ERROR extracting %s: %s", pdf_path.name, e)
        traceback.print_exc()
        return ""
    finally:
        if tmp_pdf is not None and tmp_pdf.exists():
            try:
                os.unlink(tmp_pdf)
            except OSError:
                pass


def extract_pdf_pytiblegenc(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
) -> str:
    """Extract via ``pytiblegenc.pdf_to_txt``."""
    logger.info("    Extracting (pytiblegenc pdf_to_txt): %s", pdf_path.name)

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
        return pdf_to_txt(
            str(target_pdf),
            page_break_str=f"\n{PAGE_BREAK_STR}\n",
            track_font_size=True,
            font_size_format=_FONT_SIZE_FORMAT,
            normalize=False,
            simplify_font_sizes_option=False,
        )
    except Exception as e:
        logger.error("    ERROR extracting %s: %s", pdf_path.name, e)
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
    """Dispatch to the chosen extraction backend."""
    if extractor == "pytiblegenc":
        return extract_pdf_pytiblegenc(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom)
    return extract_pdf_pymupdf(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom)
