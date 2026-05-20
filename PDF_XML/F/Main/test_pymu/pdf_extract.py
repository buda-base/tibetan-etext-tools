"""
PDF text extraction for Monlam-font PDFs: PyMuPDF ``rawdict`` or ``pytiblegenc.pdf_to_txt``.

Line breaks are layout-level (one ``\n`` per extractor line); ``PAGE_BREAK_STR`` marks pages.
"""

from __future__ import annotations

import io
import logging
import os
import re
import string
import tempfile
import unicodedata
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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
PAGE_BREAK_PREFIX_RE = re.compile(r"\nZZZZ:[^\n]*\n")
_FONT_SIZE_FORMAT = "<fs:{}>"
_FN_SENTINEL_START = "ZZFN_START:"
_FN_SENTINEL_END = "ZZFN_END"

_TIBETAN_MIN = 0x0F00
_TIBETAN_MAX = 0x0FFF


def _is_tibetan(s: str) -> bool:
    return bool(s) and all(_TIBETAN_MIN <= ord(c) <= _TIBETAN_MAX for c in s)


# ─── Font path discovery ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_font_paths() -> List[Path]:
    """Return font file paths from config.FONT_DIR (None = GSUB disabled)."""
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
            paths.extend(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in (".ttf", ".otf"))
        elif p.is_file() and p.suffix.lower() in (".ttf", ".otf"):
            paths.append(p)
    return paths


@lru_cache(maxsize=64)
def _find_font_file(basefont_name: str) -> Optional[Path]:
    """Find a font file matching basefont_name (strips PDF subset prefix, case-insensitive)."""
    stem = basefont_name.split("+")[-1] if "+" in basefont_name else basefont_name
    def _norm(s: str) -> str:
        return s.lower().replace("_", "").replace("-", "").replace(" ", "")
    target = _norm(stem)
    return next((p for p in _get_font_paths() if _norm(p.stem) == target), None)


# ─── GSUB-based CMap patching ──────────────────────────────────────────────────

def _parse_tounicode_cmap(cmap_text: str) -> Dict[int, str]:
    """Parse a PDF ToUnicode CMap stream into {glyph_id: unicode_string}."""
    result: Dict[int, str] = {}
    for m in re.finditer(r"<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]+)>", cmap_text):
        gid, uni_hex = int(m.group(1), 16), m.group(2)
        result[gid] = "".join(chr(int(uni_hex[i:i+4], 16)) for i in range(0, len(uni_hex), 4))
    for m in re.finditer(r"<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]+)>", cmap_text):
        start, end, base_hex = int(m.group(1), 16), int(m.group(2), 16), m.group(3)
        if len(base_hex) == 4:
            base_cp = int(base_hex, 16)
            for i in range(end - start + 1):
                result[start + i] = chr(base_cp + i)
    for m in re.finditer(r"<([0-9a-fA-F]{2,4})>\s+<([0-9a-fA-F]{2,4})>\s+\[<([^>]+)>", cmap_text):
        start, uni_hex = int(m.group(1), 16), m.group(3)
        result[start] = "".join(chr(int(uni_hex[i:i+4], 16)) for i in range(0, len(uni_hex), 4))
    return result


def _compute_fuzzy_hash(tt, glyph_name: str, resolution: int = 6) -> Optional[str]:
    """Resolution-6 fuzzy outline hash for cross-GID glyph shape matching."""
    try:
        if "glyf" not in tt:
            return None
        glyf_tbl = tt["glyf"]
        coords, end_pts, flags = glyf_tbl[glyph_name].getCoordinates(glyf_tbl)
    except Exception:
        return None
    upem = tt["head"].unitsPerEm
    if not coords:
        return None
    scaled = [(x / upem, y / upem) for x, y in coords]
    parts: List[str] = []
    start = 0
    for end_idx in sorted(set(end_pts)):
        contour = scaled[start:end_idx + 1]
        cx, cy = min(p[0] for p in contour), min(p[1] for p in contour)
        for j, (x, y) in enumerate(contour):
            parts.append(f"{round((x-cx)*resolution)/resolution:.4f},{round((y-cy)*resolution)/resolution:.4f},{flags[start+j]&1}")
        parts.append("|")
        start = end_idx + 1
    return sha256(";".join(parts).encode()).hexdigest()


def _build_cmap_corrections(font_bytes: bytes, basefont: str, cmap_gid_to_unicode: Dict[int, str]) -> Dict[int, str]:
    """Return {gid: correct_unicode} for GIDs with absent or wrong CMap entries."""
    if not FONTTOOLS_AVAILABLE or not GSUB_RESOLVER_AVAILABLE:
        return {}
    font_file = _find_font_file(basefont)
    if not font_file:
        return {}
    try:
        full_font = _ttLib.TTFont(str(font_file))
    except Exception:
        return {}

    glyph_map = build_glyph_unicode_map(full_font, {})
    full_hash_table = {fh: uni for name, uni in glyph_map.items()
                       if _is_tibetan(uni) and (fh := _compute_fuzzy_hash(full_font, name))}
    if not full_hash_table or not font_bytes:
        return {}

    try:
        subset_font = _ttLib.TTFont(io.BytesIO(font_bytes))
    except Exception:
        return {}

    corrections: Dict[int, str] = {}
    for gid, glyph_name in enumerate(subset_font.getGlyphOrder()):
        if cmap_gid_to_unicode.get(gid) is not None and _is_tibetan(cmap_gid_to_unicode[gid]):
            continue
        fh = _compute_fuzzy_hash(subset_font, glyph_name)
        if fh and (resolved := full_hash_table.get(fh)) and _is_tibetan(resolved):
            corrections[gid] = resolved
    logger.info("_build_cmap_corrections: %d corrections for %s", len(corrections), basefont)
    return corrections


def _patch_cmap_stream(cmap_text: str, corrections: Dict[int, str]) -> str:
    """Inject corrections as bfchar entries into a ToUnicode CMap stream."""
    if not corrections:
        return cmap_text
    entries = [f"<{gid:04x}> <{''.join(f'{ord(c):04x}' for c in uni)}>"
               for gid, uni in sorted(corrections.items())]
    patch = f"\n{len(entries)} beginbfchar\n" + "\n".join(entries) + "\nendbfchar\n"
    return cmap_text.replace("endcmap", patch + "endcmap")


def _patch_font_cmaps(doc) -> None:
    """Patch all Identity-H ToUnicode CMap streams in doc before text extraction."""
    if not FONTTOOLS_AVAILABLE or not GSUB_RESOLVER_AVAILABLE:
        return
    patched: set[int] = set()
    for pn in range(len(doc)):
        for font_entry in doc[pn].get_fonts(full=True):
            font_xref = font_entry[0]
            if font_entry[5] != "Identity-H":
                continue
            basefont = font_entry[3]
            font_obj = doc.xref_object(font_xref, compressed=False)
            tou_m = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", font_obj)
            if not tou_m:
                continue
            tou_xref = int(tou_m.group(1))
            if tou_xref in patched:
                continue

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

            corrections = _build_cmap_corrections(font_bytes, basefont, _parse_tounicode_cmap(cmap_text))
            if corrections:
                try:
                    doc.update_stream(tou_xref, _patch_cmap_stream(cmap_text, corrections).encode("latin-1"))
                    logger.info("_patch_font_cmaps: patched %d GIDs xref=%d (%s)", len(corrections), tou_xref, basefont)
                except Exception as exc:
                    logger.warning("_patch_font_cmaps: failed to update CMap xref=%d: %s", tou_xref, exc)
            patched.add(tou_xref)


# ─── Page labels ──────────────────────────────────────────────────────────────

# InDesign stores section prefixes as UTF-16-BE code units, e.g. BOM + "Sec1:".
_INDESIGN_SECTION_PREFIX_RE = re.compile(
    r"^<FEFF005300650063003[12]003A>$"
)


def get_page_labels(pdf_path: Path) -> List[Optional[str]]:
    """Return a dense per-page list of PDF PageLabel strings (None when absent)."""
    if not PYMUPDF_AVAILABLE:
        return []
    try:
        doc = fitz.open(str(pdf_path))
        n = doc.page_count
        labels: List[Optional[str]] = [None] * n
        try:
            label_dicts = doc.get_page_labels() or []
        except AttributeError:
            label_dicts = []

        if label_dicts:
            def _roman(num: int, upper: bool = True) -> str:
                vals = [1000,900,500,400,100,90,50,40,10,9,5,4,1]
                syms = ["M","CM","D","CD","C","XC","L","XL","X","IX","V","IV","I"]
                r = ""
                for v, s in zip(vals, syms):
                    while num >= v:
                        r += s; num -= v
                return r if upper else r.lower()

            def _alpha(num: int, upper: bool = True) -> str:
                base = string.ascii_uppercase if upper else string.ascii_lowercase
                r = ""
                while num > 0:
                    num, rem = divmod(num - 1, 26)
                    r = base[rem] + r
                return r

            def _label_for(style: str, prefix: str, num: int) -> str:
                # InDesign section markers (Sec1:/Sec2: as UTF-16-BE hex) are running headers, not page labels.
                if _INDESIGN_SECTION_PREFIX_RE.match(prefix or ""):
                    return ""
                prefix = prefix or ""
                suffix = {"D": str(num), "R": _roman(num), "r": _roman(num, False),
                          "A": _alpha(num), "a": _alpha(num, False)}.get(style, "")
                return prefix + suffix

            ranges = sorted(label_dicts, key=lambda d: d.get("startpage", 0))
            for ri, rng in enumerate(ranges):
                start = rng.get("startpage", 0)
                end = ranges[ri + 1].get("startpage", n) if ri + 1 < len(ranges) else n
                style = rng.get("style", "")
                prefix = rng.get("prefix", "") or ""
                first_num = rng.get("firstpagenum", 1) or 1
                for pi in range(start, end):
                    lbl = _label_for(style, prefix, first_num + (pi - start))
                    labels[pi] = lbl or None

        doc.close()
        return labels
    except Exception as exc:
        logger.warning("get_page_labels: could not read labels from %s: %s", pdf_path.name, exc)
        return []


# ─── Margin redaction ─────────────────────────────────────────────────────────

def create_cropped_pdf(
    pdf_path: Path,
    top_frac: float,
    bottom_frac: float,
    preserve_box: Optional[List[float]] = None,
) -> Optional[Path]:
    """Return a temp PDF with margins physically redacted.

    preserve_box=[x0,y0,x1,y1] (normalised 0–1) keeps only that region.
    Falls back to top_frac/bottom_frac percentage mode when preserve_box is None.
    Returns None when no redaction is needed or PyMuPDF is unavailable.
    """
    use_box = preserve_box is not None
    use_pct = (top_frac > 0.0 or bottom_frac > 0.0) and not use_box
    if not use_box and not use_pct:
        return None
    if not PYMUPDF_AVAILABLE:
        logger.warning("Margin redaction requested but PyMuPDF is not installed.")
        return None

    if use_box:
        if len(preserve_box) != 4:
            raise ValueError(f"preserve_box must have 4 elements, got {len(preserve_box)}")
        px0, py0, px1, py1 = preserve_box
        for name, v in (("x0", px0), ("y0", py0), ("x1", px1), ("y1", py1)):
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"preserve_box '{name}' must be in [0,1], got {v}")
        if px0 >= px1 or py0 >= py1:
            raise ValueError(f"preserve_box requires x0<x1 and y0<y1, got {preserve_box}")

    try:
        doc = fitz.open(str(pdf_path))
        redact_kw = dict(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0, text=fitz.PDF_REDACT_TEXT_REMOVE)
        for page in doc:
            r = page.rect
            w, h = r.width, r.height
            if use_box:
                ax0, ay0 = r.x0 + px0*w, r.y0 + py0*h
                ax1, ay1 = r.x0 + px1*w, r.y0 + py1*h
                for rect in [fitz.Rect(r.x0,r.y0,r.x1,ay0), fitz.Rect(r.x0,ay1,r.x1,r.y1),
                              fitz.Rect(r.x0,ay0,ax0,ay1), fitz.Rect(ax1,ay0,r.x1,ay1)]:
                    if rect.width > 0 and rect.height > 0:
                        page.add_redact_annot(rect)
            else:
                if top_frac > 0.0:
                    page.add_redact_annot(fitz.Rect(r.x0, r.y0, r.x1, r.y0 + h*top_frac))
                if bottom_frac > 0.0:
                    page.add_redact_annot(fitz.Rect(r.x0, r.y0 + h*(1-bottom_frac), r.x1, r.y1))
            page.apply_redactions(**redact_kw)

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, dir=tempfile.gettempdir())
        tmp_path = Path(tmp.name)
        tmp.close()
        doc.save(str(tmp_path), garbage=4, deflate=True)
        doc.close()
        logger.info("Redacted temp PDF: %s", tmp_path.name)
        return tmp_path
    except Exception as e:
        logger.warning("Failed to redact margins on %s: %s — using original.", pdf_path.name, e)
        return None


# ─── Text extraction helpers ──────────────────────────────────────────────────

# Phantom space: a space glyph with near-zero advance (≤ 0.5 pt).
_PHANTOM_SPACE_ADVANCE_THRESHOLD = 0.5

def _is_wingdings_font(font_name: str) -> bool:
    return bool(font_name) and "wingdings" in font_name.split("+")[-1].lower().replace(" ", "")

def _is_phantom_space(char_obj: dict, prev_char_obj: Optional[dict]) -> bool:
    if char_obj.get("c") != " " or prev_char_obj is None:
        return False
    return char_obj.get("origin", (0,0))[0] < prev_char_obj.get("origin", (0,0))[0] + _PHANTOM_SPACE_ADVANCE_THRESHOLD

def _extract_line_text(line: dict) -> List[str]:
    """Extract font-size-tagged text fragments from a MuPDF line dict."""
    fragments: List[str] = []
    prev_char: Optional[dict] = None
    for span in line.get("spans", []):
        if _is_wingdings_font(span.get("font") or ""):
            continue
        fragments.append(_FONT_SIZE_FORMAT.format(round(span.get("size", 12))))
        char_objs = span.get("chars") or []
        if char_objs:
            for ch in char_objs:
                if not _is_phantom_space(ch, prev_char):
                    fragments.append(ch.get("c", ""))
                    prev_char = ch
        else:
            fragments.append(span.get("text") or "")
            prev_char = None
    return fragments


# ─── Deduplication helpers ────────────────────────────────────────────────────

_FS_TAG_RE = re.compile(r"<fs:\d+>")
_ZW_STRIP = dict.fromkeys(map(ord, "\u200B\u200C\u200D\u2060\uFEFF\u034F\u180E"))
_CJK_RE = re.compile(
    r"[\u2E80-\u2EFF\u2F00-\u2FDF\u3000-\u303F\u3040-\u309F\u30A0-\u30FF"
    r"\u3100-\u312F\u3200-\u32FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    r"\uFE30-\uFE4F\uFF00-\uFFEF\U00020000-\U0002A6DF]"
)
# Tibetan combining marks + punctuation stripped for skeletal shadow-key comparison
_TIB_COMBINING_RE = re.compile(r"[\u0f0b\u0f0c\u0f0d-\u0f14\u0f35\u0f37\u0f39\u0f71-\u0f87\u0f8d-\u0fbc]")
_TIB_BASE_RE = re.compile(r"[\u0f40-\u0f6c\u0f88-\u0f8c\u0f20-\u0f33\u0f00\u0f01]")
_STRUCT_ONLY_RE = re.compile(r"^(<fs:\d+>|\s)*$")

_DEDUP_X_BUCKET_PT = 3.0
_DEDUP_X_BUCKET_CJK_PT = 10.0
_SHADOW_X_THRESHOLD = 5.0
_SHADOW_X_THRESHOLD_CJK = 12.0
_Y_MERGE_TOLERANCE = 3.0
_Y_MERGE_TOLERANCE_TIBETAN = 5.0
_TIBETAN_LINE_FRACTION = 0.4


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))

def _tibetan_fraction(text: str) -> float:
    return sum(1 for c in text if _TIBETAN_MIN <= ord(c) <= _TIBETAN_MAX) / len(text) if text else 0.0

def _y_tolerance_for_frags(frags: List[str]) -> float:
    raw = _FS_TAG_RE.sub("", "".join(frags))
    return _Y_MERGE_TOLERANCE_TIBETAN if _tibetan_fraction(raw) >= _TIBETAN_LINE_FRACTION else _Y_MERGE_TOLERANCE

def _text_key_for_dedup(frags: List[str]) -> str:
    raw = _FS_TAG_RE.sub("", "".join(frags)).translate(_ZW_STRIP)
    raw = unicodedata.normalize("NFC", raw).replace("\u3000", " ")
    raw = re.sub(r"[\uFF01-\uFF5E]", lambda m: chr(ord(m.group()) - 0xFEE0), raw)
    return re.sub(r"\s+", " ", raw).strip()

def _text_key_skeletal(frags: List[str]) -> str:
    skeletal = _TIB_COMBINING_RE.sub("", _text_key_for_dedup(frags))
    return skeletal if skeletal and _TIB_BASE_RE.search(skeletal) else ""

def _frags_are_structural_only(frags: List[str]) -> bool:
    return bool(_STRUCT_ONLY_RE.match("".join(frags)))


def _deduplicate_raw_lines(
    raw_lines: List[Tuple[float, float, List[str]]],
    y_tolerance: float,
) -> List[Tuple[float, float, List[str]]]:
    """Remove duplicate InDesign shadow-layer lines (full-key, skeletal-key, and CJK y-text dedup)."""
    seen_full: Set[tuple] = set()
    seen_skel: Set[tuple] = set()
    seen_empty_pos: Set[tuple] = set()
    cjk_first_x: Dict[Tuple[float, str], float] = {}
    deduped: List[Tuple[float, float, List[str]]] = []

    for y_mid, x0, frags in raw_lines:
        y_bucket = round(y_mid / y_tolerance) * y_tolerance
        full_key = _text_key_for_dedup(frags)
        is_cjk = _has_cjk(full_key)
        xb = _DEDUP_X_BUCKET_CJK_PT if is_cjk else _DEDUP_X_BUCKET_PT
        x_bucket = round(x0 / xb) * xb

        if not full_key:
            if _frags_are_structural_only(frags):
                deduped.append((y_mid, x0, frags))
            else:
                pos = (y_bucket, x_bucket)
                if pos not in seen_empty_pos:
                    seen_empty_pos.add(pos)
                    deduped.append((y_mid, x0, frags))
            continue

        full_bk = (y_bucket, x_bucket, full_key)
        if full_bk in seen_full:
            continue

        skel_key = _text_key_skeletal(frags)
        if skel_key:
            skel_bk = (y_bucket, x_bucket, skel_key)
            if skel_bk in seen_skel:
                continue
            seen_skel.add(skel_bk)

        seen_full.add(full_bk)

        if is_cjk:
            yt = (y_bucket, full_key)
            if yt in cjk_first_x:
                if abs(x0 - cjk_first_x[yt]) <= _DEDUP_X_BUCKET_CJK_PT * 2:
                    continue
            else:
                cjk_first_x[yt] = x0

        deduped.append((y_mid, x0, frags))
    return deduped


def _dedup_within_row(
    row: List[Tuple[float, float, List[str]]],
) -> List[Tuple[float, float, List[str]]]:
    """Remove InDesign drop-shadow copies within a merged visual row (passes 2 & 3)."""
    first_x_full: Dict[str, float] = {}
    first_x_skel: Dict[str, float] = {}
    seen_empty_pos: Set[Tuple[float, float]] = set()
    result: List[Tuple[float, float, List[str]]] = []

    for y, x, frags in row:
        full_key = _text_key_for_dedup(frags)
        if not full_key:
            if _frags_are_structural_only(frags):
                result.append((y, x, frags))
            elif (round(y), round(x)) not in seen_empty_pos:
                seen_empty_pos.add((round(y), round(x)))
                result.append((y, x, frags))
            continue

        is_cjk = _has_cjk(full_key)
        thr = _SHADOW_X_THRESHOLD_CJK if is_cjk else _SHADOW_X_THRESHOLD

        if full_key in first_x_full and abs(x - first_x_full[full_key]) <= thr:
            continue
        skel_key = _text_key_skeletal(frags)
        if skel_key and skel_key in first_x_skel and abs(x - first_x_skel[skel_key]) <= thr:
            continue

        first_x_full[full_key] = x
        if skel_key and skel_key not in first_x_skel:
            first_x_skel[skel_key] = x
        result.append((y, x, frags))

    # Remove prefix/suffix split-line shadows (Fix 8):
    # InDesign sometimes emits one visual line as three objects: a prefix fragment
    # at the same x0 as the full line, the full line, and a suffix fragment at a
    # different x0. Strict prefix/suffix matches are removed; the full line survives.
    if len(result) >= 2:
        keys = [(_text_key_for_dedup(f), x, y, f) for y, x, f in result]
        shadow = [False] * len(keys)
        for i, (ki, xi, _, _) in enumerate(keys):
            if not ki:
                continue
            for j, (kj, xj, _, _) in enumerate(keys):
                if i == j or shadow[j] or not kj or len(kj) <= len(ki):
                    continue
                if kj.startswith(ki) and abs(xi - xj) <= _SHADOW_X_THRESHOLD:
                    shadow[i] = True; break
                if kj.endswith(ki) and abs(xi - xj) > _SHADOW_X_THRESHOLD:
                    shadow[i] = True; break
        result = [(y, x, f) for (_, x, y, f), s in zip(keys, shadow) if not s]

    return result


def _dedup_output_lines(parts: List[str]) -> List[str]:
    """Final-pass deduplication of assembled CJK lines that survived earlier passes."""
    combined = "".join(parts)
    if not _has_cjk(combined):
        return parts
    seen: set[str] = set()
    result: List[str] = []
    for line in combined.split("\n"):
        if PAGE_BREAK_STR in line:
            seen.clear()
            result.append(line)
            continue
        stripped = _FS_TAG_RE.sub("", line).strip()
        if not stripped:
            result.append(line)
            continue
        cjk_chars = len(_CJK_RE.findall(stripped))
        if cjk_chars == 0 or cjk_chars / len(stripped) < 0.5:
            result.append(line)
            continue
        key = _text_key_for_dedup([line])
        if key not in seen:
            seen.add(key)
            result.append(line)
    return ["\n".join(result)]


# ─── Two-column reading order ─────────────────────────────────────────────────
#
# For two-column pages, sorting by (y_mid, x0) interleaves both columns.
# We detect the layout and read the left column fully before the right column.
#
# Detection uses two veto checks to avoid false positives on single-column
# paragraphs where some lines are stored as two runs with a large mid-line gap:
#   Veto 1 — right side must hold ≥ 30% of total lines.
#   Veto 2 — if right side is thin AND all right lines share Y with a left line,
#             they are split-line continuations, not an independent column.

_COL_MIN_LINES = 3
_COL_MIN_GAP_PT = 30.0
_COL_MIN_RIGHT_FRACTION = 0.30
_COL_MAX_SAME_Y_FRACTION = 0.60
_COL_Y_BUCKET_PT = 5.0


def _same_y_fraction(raw_lines: List[Tuple[float, float, List[str]]], boundary: float) -> float:
    """Fraction of right-column lines that share a Y bucket with a left-column line."""
    left_buckets = {round(y / _COL_Y_BUCKET_PT) for y, x, _ in raw_lines if x < boundary}
    right = [(y, x, f) for y, x, f in raw_lines if x >= boundary]
    if not right:
        return 0.0
    return sum(1 for y, _, _ in right if round(y / _COL_Y_BUCKET_PT) in left_buckets) / len(right)


def _detect_column_boundary(raw_lines: List[Tuple[float, float, List[str]]], page_width: float) -> Optional[float]:
    """Return the column split x-coordinate for two-column pages, or None."""
    if page_width <= 0 or len(raw_lines) < _COL_MIN_LINES * 2:
        return None

    x0_vals = sorted(set(round(x, 1) for _, x, _ in raw_lines))
    if len(x0_vals) < 2:
        return None

    centre_lo, centre_hi = page_width * 0.25, page_width * 0.75
    total = len(raw_lines)
    best_boundary, best_balance, best_gap = None, total + 1, 0.0

    for i in range(len(x0_vals) - 1):
        gap = x0_vals[i+1] - x0_vals[i]
        if gap < _COL_MIN_GAP_PT:
            continue
        mid = (x0_vals[i] + x0_vals[i+1]) / 2.0
        if not (centre_lo <= mid <= centre_hi):
            continue
        left_count = sum(1 for _, x, _ in raw_lines if x < mid)
        right_count = sum(1 for _, x, _ in raw_lines if x >= mid)
        if left_count < _COL_MIN_LINES or right_count < _COL_MIN_LINES:
            continue
        if right_count / total < _COL_MIN_RIGHT_FRACTION:
            continue
        if _same_y_fraction(raw_lines, mid) > _COL_MAX_SAME_Y_FRACTION:
            continue
        balance = abs(left_count - right_count)
        if balance < best_balance or (balance == best_balance and gap > best_gap):
            best_balance, best_boundary, best_gap = balance, mid, gap

    if best_boundary is not None:
        lc = sum(1 for _, x, _ in raw_lines if x < best_boundary)
        rc = sum(1 for _, x, _ in raw_lines if x >= best_boundary)
        logger.debug("_detect_column_boundary: two-column (left=%d, right=%d, boundary=%.1f)", lc, rc, best_boundary)
    return best_boundary


def _merge_rows_for_column(col_lines: List[Tuple[float, float, List[str]]]) -> List[List[Tuple[float, float, List[str]]]]:
    """Y-merge a sorted list of lines into visual rows, confined to one column."""
    merged: List[List[Tuple[float, float, List[str]]]] = []
    for y_mid, x0, frags in col_lines:
        tol = _y_tolerance_for_frags(frags)
        if merged and abs(y_mid - sum(e[0] for e in merged[-1]) / len(merged[-1])) <= tol:
            merged[-1].append((y_mid, x0, frags))
        else:
            merged.append([(y_mid, x0, frags)])
    return merged


# ─── Footnote detection (PyMuPDF only) ────────────────────────────────────────
#
# Detection strategy (per page):
#   1. Find a horizontal separator line in page.get_drawings() whose width is in
#      [FOOTNOTE_SEPARATOR_MIN_WIDTH_PT, FOOTNOTE_SEPARATOR_MAX_WIDTH_PT] and
#      whose y-coordinate is in the lower half of the page.
#   2. Lines whose y_mid is below the separator are footnote lines, provided
#      their dominant font size is ≤ FOOTNOTE_BODY_FONT_SIZE_MAX.
#   3. Within the footnote zone, group consecutive lines into footnote entries
#      by leading numeric marker (e.g. "1 ...", "2 ...", "1.", "1)").
#   4. Body lines (above the separator) are returned for normal processing.
#   5. Footnotes are emitted as ZZFN_START:n:body ZZFN_END sentinels appended
#      to the page output; convert_footnote_sentinels_to_tei() then turns them
#      into <note n="N" place="foot">…</note> on the last body line per BDRC §4.7.

_FN_SEPARATOR_MAX_HEIGHT_PT: float = 2.0          # near-zero-height = horizontal rule
_FN_SEPARATOR_MIN_Y_FRACTION: float = 0.40        # must be in lower 60% of page
_FN_MARKER_RE = re.compile(r"^\s*(\d{1,3})[.\)\s\u3001\u3002]")
_FN_LEADING_NUM_RE = re.compile(r"^\s*\d{1,3}[.\)\s\u3001\u3002]?\s*")


def _get_footnote_config() -> Optional[dict]:
    """Return footnote-detection config dict, or None if disabled / unavailable."""
    try:
        from config import (
            FOOTNOTE_DETECTION,
            FOOTNOTE_SEPARATOR_MIN_WIDTH_PT,
            FOOTNOTE_SEPARATOR_MAX_WIDTH_PT,
            FOOTNOTE_MARKER_MAX_FONT_SIZE,
            FOOTNOTE_BODY_FONT_SIZE_MAX,
        )
    except (ImportError, AttributeError):
        return None
    if not FOOTNOTE_DETECTION:
        return None
    return {
        "sep_min_w": float(FOOTNOTE_SEPARATOR_MIN_WIDTH_PT),
        "sep_max_w": float(FOOTNOTE_SEPARATOR_MAX_WIDTH_PT),
        "marker_max_fs": float(FOOTNOTE_MARKER_MAX_FONT_SIZE),
        "body_max_fs": float(FOOTNOTE_BODY_FONT_SIZE_MAX),
    }


def _detect_footnote_separator_y(page, cfg: dict) -> Optional[float]:
    """Return the y-coordinate of the page's footnote separator rule, or None.

    Picks the lowest qualifying horizontal rule on the page (the one closest to
    the page bottom) to handle pages that contain other thin horizontals.
    """
    try:
        drawings = page.get_drawings() or []
    except Exception:
        return None

    page_h = page.rect.height
    min_y = page.rect.y0 + page_h * _FN_SEPARATOR_MIN_Y_FRACTION
    best_y: Optional[float] = None

    for d in drawings:
        for item in d.get("items", []) or []:
            # Each item is a tuple like ("l", p0, p1) for a line, or ("re", rect)
            # for a thin filled rect used as a separator.
            if not item:
                continue
            op = item[0]
            x0 = y0 = x1 = y1 = None
            if op == "l" and len(item) >= 3:
                p0, p1 = item[1], item[2]
                x0, y0 = float(p0.x), float(p0.y)
                x1, y1 = float(p1.x), float(p1.y)
            elif op == "re" and len(item) >= 2:
                r = item[1]
                x0, y0, x1, y1 = float(r.x0), float(r.y0), float(r.x1), float(r.y1)
            else:
                continue

            width = abs(x1 - x0)
            height = abs(y1 - y0)
            if height > _FN_SEPARATOR_MAX_HEIGHT_PT:
                continue
            if not (cfg["sep_min_w"] <= width <= cfg["sep_max_w"]):
                continue
            y_mid = (y0 + y1) / 2.0
            if y_mid < min_y:
                continue
            if best_y is None or y_mid > best_y:
                best_y = y_mid

    if best_y is not None:
        logger.debug("Footnote separator detected at y=%.1f on page %d", best_y, page.number)
    return best_y


def _line_dominant_font_size(line: dict) -> float:
    """Return the dominant font size in a MuPDF rawdict line, weighted by char count."""
    weighted: Dict[int, int] = {}
    for span in line.get("spans", []):
        if _is_wingdings_font(span.get("font") or ""):
            continue
        size = round(span.get("size", 0))
        if size <= 0:
            continue
        n_chars = len(span.get("chars") or []) or len(span.get("text") or "")
        weighted[size] = weighted.get(size, 0) + max(n_chars, 1)
    if not weighted:
        return 0.0
    return float(max(weighted.items(), key=lambda kv: kv[1])[0])


def _frags_plain_text(frags: List[str]) -> str:
    """Strip font-size markup from a fragment list and return the plain text."""
    return _FS_TAG_RE.sub("", "".join(frags))


def _group_footnote_lines(
    fn_lines: List[Tuple[float, float, List[str]]],
) -> List[Tuple[str, str]]:
    """Group footnote-zone lines into [(number, body_text), …] entries.

    Lines are read top-to-bottom. A line starting with a numeric marker opens a
    new entry; subsequent lines are appended to the current entry's body until
    the next numeric marker.
    """
    fn_lines = sorted(fn_lines, key=lambda t: (t[0], t[1]))
    entries: List[Tuple[str, List[str]]] = []
    for _, _, frags in fn_lines:
        text = _frags_plain_text(frags).strip()
        if not text:
            continue
        m = _FN_MARKER_RE.match(text)
        if m:
            number = m.group(1)
            body = _FN_LEADING_NUM_RE.sub("", text, count=1).strip()
            entries.append((number, [body] if body else []))
        elif entries:
            entries[-1][1].append(text)
        # Else: orphan text above the first marker — ignored (likely a stray
        # artefact that slipped past the separator filter).

    return [(num, " ".join(parts).strip()) for num, parts in entries if parts]


def _separate_footnote_lines(
    raw_lines: List[Tuple[float, float, List[str]]],
    raw_line_meta: List[float],
    sep_y: float,
    body_max_fs: float,
) -> Tuple[
    List[Tuple[float, float, List[str]]],
    List[Tuple[float, float, List[str]]],
]:
    """Split raw_lines into (body_lines, footnote_lines) using the separator.

    A line is a footnote line iff its y_mid is below sep_y AND its dominant
    font size is ≤ body_max_fs (i.e. small text, not a stray body line that
    dropped below the rule).
    """
    body: List[Tuple[float, float, List[str]]] = []
    fns:  List[Tuple[float, float, List[str]]] = []
    for line, fs in zip(raw_lines, raw_line_meta):
        y_mid = line[0]
        if y_mid > sep_y and (fs == 0.0 or fs <= body_max_fs):
            fns.append(line)
        else:
            body.append(line)
    return body, fns


def _format_footnote_sentinels(entries: List[Tuple[str, str]]) -> str:
    """Render [(n, body), …] as ZZFN_START:n:body\\nZZFN_END\\n sentinels."""
    if not entries:
        return ""
    out: List[str] = []
    for n, body in entries:
        out.append(f"{_FN_SENTINEL_START}{n}:{body}\n{_FN_SENTINEL_END}\n")
    return "".join(out)


# ─── Main extractors ──────────────────────────────────────────────────────────

def _open_target_pdf(
    pdf_path: Path,
    crop_top: float,
    crop_bottom: float,
    preserve_box: Optional[List[float]],
) -> Tuple[Path, Optional[Path]]:
    """Return (target_path, tmp_path_or_None) after applying any margin redaction."""
    if preserve_box is not None:
        tmp = create_cropped_pdf(pdf_path, crop_top, crop_bottom, preserve_box=preserve_box)
    elif crop_top > 0.0 or crop_bottom > 0.0:
        tmp = create_cropped_pdf(pdf_path, crop_top, crop_bottom)
    else:
        tmp = None
    return (tmp if tmp else pdf_path), tmp


def extract_pdf_pymupdf(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    preserve_box: Optional[List[float]] = None,
) -> str:
    """Extract text via PyMuPDF rawdict with column-aware reading order."""
    logger.info("    Extracting (PyMuPDF rawdict): %s", pdf_path.name)
    if not PYMUPDF_AVAILABLE:
        logger.error("PyMuPDF is required. pip install pymupdf")
        return ""

    target_path, tmp_pdf = _open_target_pdf(pdf_path, crop_top, crop_bottom, preserve_box)
    fn_cfg = _get_footnote_config()
    try:
        doc = fitz.open(str(target_path))
        _patch_font_cmaps(doc)
        page_labels = get_page_labels(pdf_path)
        parts: List[str] = []

        for page in doc:
            raw_lines: List[Tuple[float, float, List[str]]] = []
            raw_line_fs: List[float] = []
            for block in page.get_text("rawdict").get("blocks", []):
                if block.get("type", 1) != 0:
                    continue
                for line in block.get("lines", []):
                    bbox = line.get("bbox", [0, 0, 0, 0])
                    frags = _extract_line_text(line)
                    if frags:
                        raw_lines.append(((bbox[1]+bbox[3])/2.0, bbox[0], frags))
                        raw_line_fs.append(_line_dominant_font_size(line))

            # ── Footnote detection ──────────────────────────────────────────
            fn_sentinels = ""
            if fn_cfg is not None and raw_lines:
                sep_y = _detect_footnote_separator_y(page, fn_cfg)
                if sep_y is not None:
                    body_lines, fn_lines = _separate_footnote_lines(
                        raw_lines, raw_line_fs, sep_y, fn_cfg["body_max_fs"],
                    )
                    if fn_lines:
                        entries = _group_footnote_lines(fn_lines)
                        if entries:
                            fn_sentinels = _format_footnote_sentinels(entries)
                            logger.info(
                                "    Page %d: detected %d footnote(s)",
                                page.number + 1, len(entries),
                            )
                            raw_lines = body_lines

            if raw_lines:
                raw_lines = _deduplicate_raw_lines(raw_lines, _Y_MERGE_TOLERANCE)

            #boundary = _detect_column_boundary(raw_lines, page.rect.width)
            boundary = None
            if boundary is not None:
                merged_rows = (
                    _merge_rows_for_column(sorted([l for l in raw_lines if l[1] < boundary], key=lambda t: (t[0], t[1])))
                    + _merge_rows_for_column(sorted([l for l in raw_lines if l[1] >= boundary], key=lambda t: (t[0], t[1])))
                )
            else:
                merged_rows = _merge_rows_for_column(sorted(raw_lines, key=lambda t: (t[0], t[1])))

            page_parts: List[str] = []
            for row in merged_rows:
                row.sort(key=lambda t: t[1])
                for _, _, frags in _dedup_within_row(row):
                    page_parts.extend(frags)
                page_parts.append("\n")

            parts.extend(_dedup_output_lines(page_parts))
            if fn_sentinels:
                parts.append(fn_sentinels)
            pn = page.number
            label = page_labels[pn] if pn < len(page_labels) and page_labels[pn] is not None else ""
            parts.append(f"\n{PAGE_BREAK_STR}:{label}\n")

        doc.close()
        return "".join(parts)
    except Exception:
        logger.exception("    ERROR extracting %s", pdf_path.name)
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
    preserve_box: Optional[List[float]] = None,
) -> str:
    """Extract via pytiblegenc.pdf_to_txt with page labels injected."""
    logger.info("    Extracting (pytiblegenc): %s", pdf_path.name)
    if not PYTIBLEGENC_AVAILABLE:
        logger.error("pytiblegenc is required. pip install git+https://github.com/buda-base/py-tiblegenc.git")
        return ""

    page_labels = get_page_labels(pdf_path)
    target_path, tmp_pdf = _open_target_pdf(pdf_path, crop_top, crop_bottom, preserve_box)
    try:
        raw = pdf_to_txt(
            str(target_path),
            page_break_str=f"\n{PAGE_BREAK_STR}\n",
            track_font_size=True,
            font_size_format=_FONT_SIZE_FORMAT,
            normalize=False,
            simplify_font_sizes_option=False,
        )
        page_index = 0
        def _inject_label(m: re.Match) -> str:
            nonlocal page_index
            label = page_labels[page_index] if page_index < len(page_labels) and page_labels[page_index] is not None else ""
            page_index += 1
            return f"\n{PAGE_BREAK_STR}:{label}\n"
        return re.sub(rf"\n{re.escape(PAGE_BREAK_STR)}\n", _inject_label, raw)
    except Exception:
        logger.exception("    ERROR extracting %s", pdf_path.name)
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
    preserve_box: Optional[List[float]] = None,
) -> str:
    """Dispatch to the chosen extraction backend (pymupdf or pytiblegenc)."""
    if extractor == "pytiblegenc":
        return extract_pdf_pytiblegenc(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom, preserve_box=preserve_box)
    return extract_pdf_pymupdf(pdf_path, crop_top=crop_top, crop_bottom=crop_bottom, preserve_box=preserve_box)