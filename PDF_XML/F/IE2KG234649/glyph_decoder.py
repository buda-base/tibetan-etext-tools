from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

# Known PUA / CID overrides found in IE2KG234649 PDFs.
# U+10FC09 is a private-use glyph that should decode to Tibetan stacked form སྡུ.
DEFAULT_PUA_TO_UNICODE_OVERRIDES: Dict[int, str] = {
    0x10FC09: "སྡུ",
}

# CID to Unicode mappings for Monlam fonts used in IE2KG234649 PDFs.
# These CIDs are not in the PDF's ToUnicode CMap and must be mapped manually.
# 
# NOTE: This is a partial mapping. Many CIDs are still unmapped.
# To add more mappings:
# 1. Find the CID number from the PDF (appears as (cid:N) in pdfminer output)
# 2. Determine the correct Unicode text by visual inspection or reference
# 3. Add the mapping below in the format: ("FontName", CID): "Unicode text"
#
# Common patterns observed:
# - CIDs 299-526 appear to be Tibetan stacked consonants and special forms
# - CIDs 1-85 (TTB444o00) appear to be decorative/special characters
DEFAULT_CID_TO_UNICODE_OVERRIDES: Dict[Tuple[str, int], str] = {
    # MonlamUniOuChan1 mappings
    ("MonlamUniOuChan1", 299): "སུ",
    ("MonlamUniOuChan1", 306): "གྱི",
    ("MonlamUniOuChan1", 320): "རྗེ",
    ("MonlamUniOuChan1", 345): "པ",
    ("MonlamUniOuChan1", 369): "གྱ",
    ("MonlamUniOuChan1", 399): "རྗ",
    ("MonlamUniOuChan1", 411): "སྟ",
    ("MonlamUniOuChan1", 428): "སྡུ",
    ("MonlamUniOuChan1", 453): "པ",
    ("MonlamUniOuChan1", 505): "སུ",
    
    # MonlamUniOuChan2 mappings (same as MonlamUniOuChan1 for known CIDs)
    ("MonlamUniOuChan2", 299): "སུ",
    ("MonlamUniOuChan2", 306): "གྱི",
    ("MonlamUniOuChan2", 320): "རྗེ",
    ("MonlamUniOuChan2", 345): "པ",
    ("MonlamUniOuChan2", 369): "གྱ",
    ("MonlamUniOuChan2", 399): "རྗ",
    ("MonlamUniOuChan2", 411): "སྟ",
    ("MonlamUniOuChan2", 428): "སྡུ",
    ("MonlamUniOuChan2", 453): "པ",
    ("MonlamUniOuChan2", 505): "སུ",
    
    # TODO: Add more CID mappings as they are discovered
    # To find unmapped CIDs, run the conversion and look for remaining (cid:N) tokens
}

try:
    from fontTools.ttLib import TTFont
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1

    FONTTOOLS_PDFMINER_AVAILABLE = True
except ImportError:
    FONTTOOLS_PDFMINER_AVAILABLE = False


def _normalize_font_key(font_name: str) -> str:
    """
    Normalize font name by removing prefixes, quotes, and suffixes.
    Examples:
        /'IGJIEA+MonlamUniOuChan1' -> MonlamUniOuChan1
        'TTB444o00-Identity-H' -> TTB444o00
    """
    if not font_name:
        return ""
    # Remove leading /' and quotes
    name = font_name.strip("/'\"")
    # Remove prefix before +
    if "+" in name:
        name = name.split("+", 1)[1]
    # Remove suffix after -
    if "-" in name:
        name = name.split("-", 1)[0]
    return name


def build_embedded_font_gid_map(
    pdf_path: Path,
    logger=None,
    pua_to_unicode_overrides: Optional[Dict[int, str]] = None,
) -> Dict[Tuple[str, int], str]:
    """
    Build (font_name, cid/glyph_id) -> unicode_text map from embedded fonts.
    
    Strategy:
    1. For CID-keyed fonts: Parse ToUnicode CMap from PDF font dict
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
                    
                    # Check if this is a CID font with ToUnicode CMap
                    if "ToUnicode" in font_dict:
                        try:
                            from pdfminer.cmapdb import CMap, CMapParser
                            tounicode_stream = resolve1(font_dict["ToUnicode"])
                            tounicode_data = tounicode_stream.get_data()
                            cmap = CMap()
                            CMapParser(cmap, io.BytesIO(tounicode_data)).run()
                            
                            # Try to decode all possible CIDs (0-4000 is reasonable for most fonts)
                            for cid in range(4000):
                                try:
                                    cid_bytes = cid.to_bytes(2, "big")
                                    result = cmap.decode(cid_bytes)
                                    if result:
                                        chars = "".join(chr(c) for c in result)
                                        key = (font_name, cid)
                                        gid_map.setdefault(key, chars)
                                except:
                                    pass
                        except Exception:
                            pass
                    
                    # Also try embedded font cmap (for non-CID fonts)
                    descriptor = (
                        resolve1(font_dict.get("FontDescriptor"))
                        if font_dict.get("FontDescriptor")
                        else {}
                    )
                    
                    # For CID fonts, check descendant fonts
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

                    # Build GID -> Unicode mapping from embedded font cmap
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
    """
    Decode unresolved (cid:N) token using known CID overrides and cmap-derived map.
    """
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
    """
    Monkey-patch pytiblegenc's convert_string to decode unresolved CID tokens.
    """
    gid_map = build_embedded_font_gid_map(
        pdf_path,
        logger=logger,
        pua_to_unicode_overrides=pua_to_unicode_overrides,
    )
    cid_stats = {"count": 0}
    original_convert_string = text_converter_module.convert_string

    def convert_string_with_cid_decode(s, font_name, stats, error_chr_fun=None, glyph_lookup=None):
        # pytiblegenc drops unresolved CIDs by returning "" for strings like "(cid:428)".
        # Decode those CIDs before they are lost.
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
        # Call original with all arguments it expects
        # Handle both old (4 args) and new (5 args) signatures
        try:
            return original_convert_string(s, font_name, stats, error_chr_fun, glyph_lookup)
        except TypeError:
            return original_convert_string(s, font_name, stats, error_chr_fun)

    text_converter_module.convert_string = convert_string_with_cid_decode
    try:
        yield cid_stats
    finally:
        text_converter_module.convert_string = original_convert_string
