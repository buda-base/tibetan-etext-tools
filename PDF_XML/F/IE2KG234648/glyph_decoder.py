"""
glyph_decoder — drop-in replacement for glyph_decoder that loads
TCRC CID→Unicode overrides automatically from pytiblegenc's utfc.csv
instead of maintaining a hand-written dict.

Public API is identical to glyph_decoder:
    DEFAULT_PUA_TO_UNICODE_OVERRIDES
    DEFAULT_CID_TO_UNICODE_OVERRIDES
    build_embedded_font_gid_map()
    decode_cid_token()
    patch_pytiblegenc_cid_decoder()
"""
from __future__ import annotations

import csv
import io
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PUA overrides (same as glyph_decoder.py)
# ---------------------------------------------------------------------------
DEFAULT_PUA_TO_UNICODE_OVERRIDES: Dict[int, str] = {
    0x10FC09: "སྡུ",
}

# ---------------------------------------------------------------------------
# utfc.csv auto-loader
# ---------------------------------------------------------------------------

# Map utfc.csv font names → PDF-normalized names produced by _normalize_font_key.
# Extend this when new legacy Tibetan fonts appear in PDFs.
_UTFC_FONT_ALIASES: Dict[str, list[str]] = {
    "TCRC Youtso": ["TCRCYoutso", "TCRC Youtso"],
    "TCRC Bod-Yig": ["TCRCBod", "TCRC Bod-Yig", "TCRCBod-Yig"],
    "TCRC Youtsoweb": ["TCRCYoutsoweb", "TCRC Youtsoweb"],
    
}


def _load_utfc_overrides() -> Dict[Tuple[str, int], str]:
    """
    Load legacy font → Unicode tables from pytiblegenc's utfc.csv.

    Returns a dict keyed by (pdf_normalized_font_name, codepoint) → tibetan_string,
    covering every font family listed in _UTFC_FONT_ALIASES.
    """
    overrides: Dict[Tuple[str, int], str] = {}
    try:
        import pytiblegenc
        utfc_path = Path(pytiblegenc.__file__).parent / "font-tables" / "utfc.csv"
        if not utfc_path.is_file():
            _logger.debug("utfc.csv not found at %s", utfc_path)
            return overrides
    except ImportError:
        return overrides

    utfc_to_pdf: Dict[str, list[str]] = {
        utfc_name: pdf_names
        for utfc_name, pdf_names in _UTFC_FONT_ALIASES.items()
    }

    with utfc_path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 3:
                continue
            utfc_font = row[0].strip()
            pdf_names = utfc_to_pdf.get(utfc_font)
            if pdf_names is None:
                continue
            try:
                codepoint = int(row[1].strip())
            except ValueError:
                continue
            tibetan = row[2]
            if not tibetan:
                continue
            for pdf_name in pdf_names:
                overrides.setdefault((pdf_name, codepoint), tibetan)

    if overrides:
        _logger.debug("Loaded %d TCRC overrides from utfc.csv", len(overrides))
    return overrides


# Manual overrides for fonts NOT covered by utfc.csv (e.g. Monlam CID fonts).
_MANUAL_CID_TO_UNICODE_OVERRIDES: Dict[Tuple[str, int], str] = {
 
    ("TCRCYoutso", 197): "ས",  
    ("TCRCYoutso", 227): "ུ",  
    ("TCRCYoutso", 32): " ",
    ("TCRCYoutso", 130): "བྱ",
    ("TCRCYoutso", 159): "ཞ",
    ("TCRCYoutso", 136): "ཀྱ",
    ("TCRCYoutso", 137): "ྙ",
    ("TCRCYoutso", 199): "ས",
    ("TCRCYoutso", 221): "ུ",    
    ("TCRCYoutso", 122): "བ",
    ("TCRCYoutso", 198): "བྲ",
     # TCRCBod mappings 
    ("TCRCBod", 122): "བ",
    ("TCRCBod", 197): "ས",  
    ("TCRCBod", 227): "ཞ",  
    ("TCRCBod", 137): "ྙ",
    ("TCRCBod", 130): "བྱ",
    ("TCRCBod", 159): "ཞ",
    ("TCRCBod", 32): " ",
    ("TCRCBod", 136): "ཀྱ",
    ("TCRCBod", 198): "བྲ",
    ("TCRCBod", 221): "ན",
    ("TCRCBod", 199): "ས",
}

# utfc.csv (authoritative for TCRC) merged with manual (Monlam etc.)
DEFAULT_CID_TO_UNICODE_OVERRIDES: Dict[Tuple[str, int], str] = {
    **_load_utfc_overrides(),
    **_MANUAL_CID_TO_UNICODE_OVERRIDES,
}

# ---------------------------------------------------------------------------
# Optional heavy imports (fontTools + pdfminer)
# ---------------------------------------------------------------------------
try:
    from fontTools.ttLib import TTFont
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1

    FONTTOOLS_PDFMINER_AVAILABLE = True
except ImportError:
    FONTTOOLS_PDFMINER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers — identical to glyph_decoder.py
# ---------------------------------------------------------------------------

def _normalize_font_key(font_name: str) -> str:
    """Strip subset prefix (ABCDEF+) and encoding suffix (-Identity-H etc.)."""
    if not font_name:
        return ""
    name = font_name.strip("/'\"")
    if "+" in name:
        name = name.split("+", 1)[1]
    if "-" in name:
        name = name.split("-", 1)[0]
    return name


def build_embedded_font_gid_map(
    pdf_path: Path,
    logger=None,
    pua_to_unicode_overrides: Optional[Dict[int, str]] = None,
    use_pdf_tounicode: bool = True,
) -> Dict[Tuple[str, int], str]:
    """
    Build (font_name, cid/glyph_id) -> unicode_text map from embedded fonts.

    Strategy:
    1. For CID-keyed fonts: Parse ToUnicode CMap from PDF font dict (optional;
       set use_pdf_tounicode=False for Phase 2.2 retries when ToUnicode maps to garbage)
    2. For regular fonts: Use embedded font's cmap table
    3. Apply PUA overrides for known problematic characters
    """
    gid_map: Dict[Tuple[str, int], str] = {}
    pua_overrides = pua_to_unicode_overrides or DEFAULT_PUA_TO_UNICODE_OVERRIDES
    if not FONTTOOLS_PDFMINER_AVAILABLE:
        return gid_map

    seen_font_objids = set()
    try:
        with open(pdf_path, "rb") as f:
            parser = PDFParser(f)
            doc = PDFDocument(parser)

            for page in PDFPage.create_pages(doc):
                resources = resolve1(page.resources) or {}
                fonts = resolve1(resources.get("Font", {})) or {}
                for _, font_ref in fonts.items():
                    font_objid = getattr(font_ref, "objid", None)
                    if font_objid in seen_font_objids:
                        continue
                    if font_objid is not None:
                        seen_font_objids.add(font_objid)

                    font_dict = resolve1(font_ref) or {}
                    base_font_raw = font_dict.get("BaseFont", "")
                    if isinstance(base_font_raw, bytes):
                        base_font_raw = base_font_raw.decode("utf-8", "ignore")
                    else:
                        base_font_raw = str(base_font_raw)
                    font_name = _normalize_font_key(base_font_raw)

                    if use_pdf_tounicode and "ToUnicode" in font_dict:
                        try:
                            from pdfminer.cmapdb import CMap, CMapParser
                            tounicode_stream = resolve1(font_dict["ToUnicode"])
                            tounicode_data = tounicode_stream.get_data()
                            cmap = CMap()
                            CMapParser(cmap, io.BytesIO(tounicode_data)).run()

                            for cid in range(4000):
                                try:
                                    cid_bytes = cid.to_bytes(2, "big")
                                    result = cmap.decode(cid_bytes)
                                    if result:
                                        chars = "".join(chr(c) for c in result)
                                        key = (font_name, cid)
                                        gid_map.setdefault(key, chars)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    descriptor = (
                        resolve1(font_dict.get("FontDescriptor"))
                        if font_dict.get("FontDescriptor")
                        else {}
                    )

                    descendant_fonts = font_dict.get("DescendantFonts")
                    if descendant_fonts:
                        descendant_fonts = resolve1(descendant_fonts)
                        if descendant_fonts:
                            descendant_font_dict = resolve1(descendant_fonts[0])
                            desc_descriptor = resolve1(descendant_font_dict.get("FontDescriptor")) if descendant_font_dict.get("FontDescriptor") else {}
                            if desc_descriptor:
                                descriptor = desc_descriptor

                    descriptor = descriptor or {}
                    stream_ref = (
                        descriptor.get("FontFile2")
                        or descriptor.get("FontFile3")
                        or descriptor.get("FontFile")
                    )
                    if not stream_ref:
                        continue

                    stream = resolve1(stream_ref)
                    font_bytes = stream.get_data()
                    tt = TTFont(io.BytesIO(font_bytes), lazy=True)
                    if "cmap" not in tt:
                        continue

                    reverse_glyph_map = tt.getReverseGlyphMap(rebuild=True)
                    for cmap_table in tt["cmap"].tables:
                        if not cmap_table.isUnicode():
                            continue
                        for codepoint, glyph_name in cmap_table.cmap.items():
                            glyph_id = reverse_glyph_map.get(glyph_name)
                            if glyph_id is None:
                                continue

                            unicode_text = pua_overrides.get(codepoint, chr(codepoint))
                            key = (font_name, glyph_id)
                            gid_map.setdefault(key, unicode_text)
    except Exception as e:
        if logger:
            logger.warning(
                f"    Could not build embedded-font glyph map for {pdf_path.name}: {e}"
            )

    return gid_map


def decode_cid_token(
    font_name: str,
    cid: int,
    gid_map: Dict[Tuple[str, int], str],
    cid_to_unicode_overrides: Optional[Dict[Tuple[str, int], str]] = None,
) -> str:
    """Decode unresolved (cid:N) token using known CID overrides and cmap-derived map."""
    cid_overrides = cid_to_unicode_overrides or DEFAULT_CID_TO_UNICODE_OVERRIDES
    candidates = [_normalize_font_key(font_name), font_name]
    for candidate in candidates:
        override = cid_overrides.get((candidate, cid))
        if override:
            return override
        mapped = gid_map.get((candidate, cid))
        if mapped:
            return mapped
    return ""


@contextmanager
def patch_pytiblegenc_cid_decoder(
    pdf_path: Path,
    text_converter_module,
    logger=None,
    pua_to_unicode_overrides: Optional[Dict[int, str]] = None,
    cid_to_unicode_overrides: Optional[Dict[Tuple[str, int], str]] = None,
) -> Iterator[Dict[str, int]]:
    """Monkey-patch pytiblegenc's convert_string to decode unresolved CID tokens."""
    gid_map = build_embedded_font_gid_map(
        pdf_path,
        logger=logger,
        pua_to_unicode_overrides=pua_to_unicode_overrides,
    )
    cid_stats = {"count": 0}
    original_convert_string = text_converter_module.convert_string

    def convert_string_with_cid_decode(s, font_name, stats, error_chr_fun=None, glyph_lookup=None):
        if s.startswith("(cid:") and s.endswith(")"):
            try:
                cid = int(s[5:-1])
            except ValueError:
                return ""
            decoded = decode_cid_token(
                font_name=font_name,
                cid=cid,
                gid_map=gid_map,
                cid_to_unicode_overrides=cid_to_unicode_overrides,
            )
            if decoded:
                cid_stats["count"] += 1
            return decoded
        try:
            return original_convert_string(s, font_name, stats, error_chr_fun, glyph_lookup)
        except TypeError:
            return original_convert_string(s, font_name, stats, error_chr_fun)

    text_converter_module.convert_string = convert_string_with_cid_decode
    try:
        yield cid_stats
    finally:
        text_converter_module.convert_string = original_convert_string
