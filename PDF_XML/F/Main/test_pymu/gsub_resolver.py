"""
gsub_resolver.py
================
Resolve Tibetan glyphs whose ToUnicode CMap entries are absent or wrong.

Root cause: Tibetan Unicode fonts (e.g. MonlamUniOuChan2) use GSUB substitution
to produce context-dependent glyph variants.  In PDF subsets the cmap table is
stripped, so some GIDs are mapped to wrong Latin Extended codepoints instead of
the correct Tibetan vowels.

Resolution hierarchy (applied in build_glyph_unicode_map):
  2.1  ToUnicode CMap — trusted Tibetan entries accepted directly.
  2.3a GSUB inversion — requires the full font file (cmap + GSUB tables).
  2.3b Fuzzy shape matching — resolution-6 outline hash against trusted entries.

Public API
----------
  build_glyph_unicode_map(ttfont, cmap_gid_to_unicode) -> dict[glyph_name, str]
  resolve_char(glyph_name, glyph_unicode_map, fallback_char) -> str
"""

from __future__ import annotations

import logging
from functools import lru_cache
from hashlib import sha256
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────────
_TIBETAN_MIN = 0x0F00
_TIBETAN_MAX = 0x0FFF

# Resolution for fuzzy glyph-outline hashing.
# At resolution 6, sub-pixel variants of the same glyph collapse to the same
# hash while visually distinct glyphs (different vowel shapes) remain distinct.
_FUZZY_RESOLUTION = 6

# Tibetan vowel sign range U+0F71–U+0F81
_TIBETAN_VOWEL_SIGNS = frozenset(range(0x0F71, 0x0F82))


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _is_tibetan(unicode_str: str) -> bool:
    """Return True if every codepoint is in the Tibetan Unicode block."""
    return bool(unicode_str) and all(_TIBETAN_MIN <= ord(c) <= _TIBETAN_MAX for c in unicode_str)


def _compute_fuzzy_hash(ttfont, glyph_name: str, resolution: int = _FUZZY_RESOLUTION) -> Optional[str]:
    """
    Compute a reduced-precision outline hash for fuzzy glyph matching.

    Each contour is normalised independently (shifted so its own min corner
    is at the origin) so the hash is position-independent.  Returns None if
    the glyph has no outline or cannot be processed.
    """
    try:
        if "glyf" not in ttfont:
            return None
        glyf_table = ttfont["glyf"]
        glyph = glyf_table[glyph_name]
        coords, end_pts, flags = glyph.getCoordinates(glyf_table)
    except Exception:
        return None

    upem = ttfont["head"].unitsPerEm
    if not coords:
        return sha256(f"EMPTY:{glyph_name}".encode()).hexdigest()

    scaled = [(x / upem, y / upem) for x, y in coords]
    contour_ends = set(end_pts)
    parts: list[str] = []
    start = 0
    for end_idx in sorted(contour_ends):
        contour = scaled[start: end_idx + 1]
        cx_min = min(p[0] for p in contour)
        cy_min = min(p[1] for p in contour)
        for j, (x, y) in enumerate(contour):
            rx = round((x - cx_min) * resolution) / resolution
            ry = round((y - cy_min) * resolution) / resolution
            parts.append(f"{rx:.4f},{ry:.4f},{flags[start + j] & 1}")
        parts.append("|")
        start = end_idx + 1

    return sha256(";".join(parts).encode()).hexdigest()


# ─── Step 2.3a — GSUB inversion ────────────────────────────────────────────────

def invert_gsub(ttfont) -> Dict[str, Set[Tuple[int, ...]]]:
    """
    Invert the font's GSUB table to produce:

        glyph_name → set of Unicode codepoint tuples

    Handles lookup types 1 (single), 3 (alternate), 4 (ligature), and 7
    (extension wrapper).  Returns {} if the font lacks cmap or GSUB tables.
    """
    if "GSUB" not in ttfont or "cmap" not in ttfont:
        return {}

    try:
        cmap = ttfont["cmap"].getBestCmap() or {}
    except Exception:
        return {}

    glyph_to_cps: Dict[str, list[int]] = {}
    for cp, gname in cmap.items():
        glyph_to_cps.setdefault(gname, []).append(cp)

    gsub = ttfont["GSUB"].table
    result: Dict[str, Set[Tuple[int, ...]]] = {}

    def _glyphs_to_seq(glyph_names: list[str]) -> Optional[Tuple[int, ...]]:
        seq = []
        for g in glyph_names:
            cps = glyph_to_cps.get(g)
            if not cps:
                return None
            seq.append(cps[0])
        return tuple(seq)

    def _process_lookup(lookup):
        lookup_type = lookup.LookupType
        if lookup_type == 7:
            for sub in lookup.SubTable:
                _process_lookup(sub.ExtSubTable)
            return
        for sub in lookup.SubTable:
            if lookup_type == 1 and hasattr(sub, "mapping"):
                for src, tgt in sub.mapping.items():
                    seq = _glyphs_to_seq([src])
                    if seq:
                        result.setdefault(tgt, set()).add(seq)
            elif lookup_type == 3 and hasattr(sub, "alternates"):
                for src, alt_set in sub.alternates.items():
                    seq = _glyphs_to_seq([src])
                    if seq and hasattr(alt_set, "Alternate"):
                        for tgt in alt_set.Alternate:
                            result.setdefault(tgt, set()).add(seq)
            elif lookup_type == 4 and hasattr(sub, "ligatures"):
                for first_glyph, lig_set in sub.ligatures.items():
                    ligs = lig_set if isinstance(lig_set, list) else (
                        lig_set.Ligature if hasattr(lig_set, "Ligature") else []
                    )
                    for lig in ligs:
                        seq = _glyphs_to_seq([first_glyph] + list(lig.Component))
                        if seq:
                            result.setdefault(lig.LigGlyph, set()).add(seq)

    for lookup in gsub.LookupList.Lookup:
        _process_lookup(lookup)

    return result


# ─── Step 2.1 — CMap filtering ─────────────────────────────────────────────────

def filter_cmap_to_tibetan(gid_to_unicode: Dict[int, str]) -> Dict[int, str]:
    """Return only CMap entries that map to valid Tibetan Unicode codepoints."""
    return {gid: uni for gid, uni in gid_to_unicode.items() if _is_tibetan(uni)}


# ─── Step 2.3b — Fuzzy shape reference table ───────────────────────────────────

def _build_fuzzy_reference_table(
    ttfont,
    trusted_gid_to_unicode: Dict[int, str],
    resolution: int = _FUZZY_RESOLUTION,
) -> Dict[str, str]:
    """Build {fuzzy_hash → unicode_string} from trusted Tibetan GID mappings."""
    glyph_order = ttfont.getGlyphOrder()
    table: Dict[str, str] = {}
    for gid, uni in trusted_gid_to_unicode.items():
        if gid < len(glyph_order):
            fh = _compute_fuzzy_hash(ttfont, glyph_order[gid], resolution)
            if fh:
                table[fh] = uni
    return table


# ─── Sequence resolution helper ────────────────────────────────────────────────

def _resolve_tibetan_sequence(seq: Tuple[int, ...]) -> str:
    """
    Convert a GSUB codepoint sequence to the Unicode string for text extraction.

    For a ligature sequence whose first codepoint is a vowel sign, return only
    that vowel (the stacking consonant is encoded by preceding syllable glyphs).
    """
    if not seq:
        return ""
    if len(seq) == 1:
        return chr(seq[0])
    if seq[0] in _TIBETAN_VOWEL_SIGNS:
        return chr(seq[0])
    return "".join(chr(cp) for cp in seq)


# ─── Main public API ────────────────────────────────────────────────────────────

def build_glyph_unicode_map(
    ttfont,
    cmap_gid_to_unicode: Dict[int, str],
    resolution: int = _FUZZY_RESOLUTION,
) -> Dict[str, str]:
    """
    Build a complete glyph_name → unicode_string mapping by combining:

      1. ToUnicode CMap (trusted Tibetan entries only)
      2. GSUB inversion (requires full font with cmap + GSUB tables)
      3. Fuzzy shape matching (resolution-6 outline hash)

    GIDs with no resolution are absent from the returned dict; callers fall
    back to PyMuPDF's own decoded value.
    """
    glyph_order = ttfont.getGlyphOrder()
    result: Dict[str, str] = {}

    # Step 2.1 — accept Tibetan-valued CMap entries
    trusted = filter_cmap_to_tibetan(cmap_gid_to_unicode)
    for gid, uni in trusted.items():
        if gid < len(glyph_order):
            result[glyph_order[gid]] = uni
    logger.debug("Step 2.1: %d Tibetan CMap entries accepted", len(trusted))

    # Step 2.3a — GSUB inversion (requires full font)
    gsub_map = invert_gsub(ttfont)
    if gsub_map:
        resolved_via_gsub = 0
        for glyph_name, sequences in gsub_map.items():
            if glyph_name in result:
                continue
            for seq in sorted(sequences, key=len):
                uni = _resolve_tibetan_sequence(seq)
                if uni and _is_tibetan(uni):
                    result[glyph_name] = uni
                    resolved_via_gsub += 1
                    break
        logger.debug("Step 2.3a (GSUB): %d additional glyphs resolved", resolved_via_gsub)
    else:
        logger.debug("Step 2.3a (GSUB): skipped — font has no cmap+GSUB (subset)")

    # Step 2.3b — fuzzy shape matching
    fuzzy_ref = _build_fuzzy_reference_table(ttfont, trusted, resolution)
    if fuzzy_ref:
        resolved_via_shape = 0
        for gid, glyph_name in enumerate(glyph_order):
            if glyph_name in result:
                continue
            fh = _compute_fuzzy_hash(ttfont, glyph_name, resolution)
            if fh and fh in fuzzy_ref:
                result[glyph_name] = fuzzy_ref[fh]
                resolved_via_shape += 1
        logger.debug(
            "Step 2.3b (fuzzy shape): %d additional glyphs resolved (ref table: %d entries)",
            resolved_via_shape, len(fuzzy_ref),
        )
    else:
        logger.debug("Step 2.3b (fuzzy shape): skipped — no trusted Tibetan reference entries")

    logger.info(
        "build_glyph_unicode_map: %d / %d glyphs resolved",
        len(result), len(glyph_order),
    )
    return result


def resolve_char(
    glyph_name: str,
    glyph_unicode_map: Dict[str, str],
    fallback_char: str,
) -> str:
    """Return the best Unicode string for a glyph, or fallback_char if unknown."""
    return glyph_unicode_map.get(glyph_name, fallback_char)
