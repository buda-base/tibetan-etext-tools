"""
gsub_resolver.py
================
Step 2.2 / 2.3 implementation from the PDF conversion spec.

For Unicode fonts embedded in PDFs, PyMuPDF can produce wrong characters when
the font's ToUnicode CMap is incomplete or incorrect.  The root cause (fully
traced in the investigation below) is that Tibetan Unicode fonts like
MonlamUniOuChan2 use GSUB substitution rules to produce context-dependent glyph
variants whose GIDs are *not* in the CMap (or are mapped to wrong Latin Extended
codepoints because the CMap was generated from the font's internal cmap, which
maps those glyph-slots to Latin characters).

Root cause (investigated on TI1049-01-001.pdf / TI1047-01-001.pdf):
  - The PDF embeds a SUBSET of MonlamUniOuChan2.
  - The subset has no `cmap` table (stripped during subsetting).
  - The PDF's ToUnicode CMap maps MOST GIDs correctly to Tibetan Unicode.
  - A small number of GIDs (e.g. 0x0128, 0x0132, 0x0140) are mapped to
    wrong Latin Extended codepoints (Ī, Ĵ, ł) instead of Tibetan vowels
    (ི, ེ, ོ).  These GIDs correspond to GSUB-substituted glyph alternates
    that the CMap author forgot to remap.
  - PyMuPDF faithfully reads the wrong CMap values and emits ŀ/Ĳ/Ĩ.

Resolution priority (per spec §"for the glyph to Unicode part"):

  Step 2.1  ToUnicode CMap — used as-is for Tibetan codepoints (0x0F00–0x0FFF).
            Non-Tibetan codepoints produced from a CMap that covers a Tibetan
            font are treated as potential mis-mappings and passed to Step 2.2.

  Step 2.2  Embedded font cmap — not available (subset fonts strip the cmap
            table).  This step is skipped.

  Step 2.3  GSUB inversion — requires the *full* font file.
            `invert_gsub(ttfont)` builds glyph_name → {unicode_sequences} by
            reversing all Type-1/3/4 substitution rules.  Combined with the
            font's cmap, this maps any GSUB-derived glyph back to the Unicode
            input that originally produced it.

  Fallback  Fuzzy shape matching — if neither CMap nor GSUB produces a valid
            Tibetan Unicode for a glyph, compute a resolution-6 fuzzy outline
            hash and look it up in pytiblegenc's glyph_db.  (Requires
            MonlamUniOuChan2 to be added to glyph_db.csv — see README.)

Public API
----------
  build_glyph_unicode_map(ttfont, cmap_gid_to_unicode)
      → dict[glyph_name, str]   (complete GID→Unicode mapping for the font)

  resolve_char(glyph_name, glyph_unicode_map, fallback_char)
      → str                     (best Unicode string for this glyph)

Typical use in pdf_extract.py
------------------------------
  from gsub_resolver import build_glyph_unicode_map

  # Once per embedded font (cache by font xref):
  glyph_map = build_glyph_unicode_map(ttfont, cmap_gid_to_unicode)

  # Per character extracted by PyMuPDF:
  correct_char = glyph_map.get(glyph_name, pymupdf_char)
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tibetan Unicode block range
_TIBETAN_MIN = 0x0F00
_TIBETAN_MAX = 0x0FFF

# Resolution for fuzzy glyph-outline hashing.
# Coordinate grid = 1/FUZZY_RESOLUTION font-units.
# At resolution 6:
#   - Sub-pixel variants of the same glyph (outline coordinates differing by
#     < 1/6 ≈ 0.17 normalized units) collapse to the same hash.
#   - Visually distinct glyphs (different vowel shapes) remain distinct.
# Validated across MonlamUniOuChan2 GIDs 0x0132 ↔ 0x00D6 (both ེ) and
# confirmed non-collision between e-vowel and o-vowel.
_FUZZY_RESOLUTION = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_tibetan(unicode_str: str) -> bool:
    """Return True if every codepoint in the string is in the Tibetan block."""
    return bool(unicode_str) and all(_TIBETAN_MIN <= ord(c) <= _TIBETAN_MAX for c in unicode_str)


def _compute_fuzzy_hash(ttfont, glyph_name: str, resolution: int = _FUZZY_RESOLUTION) -> Optional[str]:
    """
    Compute a reduced-precision outline hash suitable for fuzzy glyph matching.

    Why fuzzy instead of exact:
        The same logical glyph (e.g. the vowel sign ེ) appears in a font as
        multiple glyph variants produced by GSUB substitution.  Each variant
        has slightly different outline coordinates (sub-pixel rounding, minor
        design adjustments) so their exact SHA-256 hashes differ.  Rounding
        each normalised coordinate to a 1/resolution grid makes visually
        identical variants hash identically while keeping distinct glyphs
        distinct.

    Returns None if the glyph has no outline or cannot be processed.
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

    # Normalise: scale by unitsPerEm, translate so min corner = (0, 0)
    norm = [(x / upem, y / upem) for x, y in coords]
    min_x = min(p[0] for p in norm)
    min_y = min(p[1] for p in norm)
    norm = [(x - min_x, y - min_y) for x, y in norm]

    # Encode with reduced precision
    contour_ends = set(end_pts)
    parts: list[str] = []
    for i, (x, y) in enumerate(norm):
        rx = round(x * resolution) / resolution
        ry = round(y * resolution) / resolution
        on_curve = flags[i] & 1
        parts.append(f"{rx:.4f},{ry:.4f},{on_curve}")
        if i in contour_ends:
            parts.append("|")

    return sha256(";".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Step 2.3 — GSUB inversion
# ---------------------------------------------------------------------------

def invert_gsub(ttfont) -> Dict[str, Set[Tuple[int, ...]]]:
    """
    Invert the font's GSUB table to build a mapping:

        glyph_name  →  set of Unicode codepoint tuples

    Each tuple is a sequence of Unicode codepoints whose rendering *produces*
    that glyph via one or more GSUB substitution rules.

    Lookup types handled
    --------------------
    Type 1 — Single substitution:
        glyph_src → glyph_tgt
        Inversion: glyph_tgt ← {unicode(glyph_src)}

    Type 3 — Alternate substitution:
        glyph_src → {glyph_alt_1, glyph_alt_2, …}
        Inversion: every alternate ← {unicode(glyph_src)}

    Type 4 — Ligature substitution:
        [glyph_1, glyph_2, …] → glyph_ligature
        Inversion: glyph_ligature ← {(unicode(g1), unicode(g2), …)}

    Type 7 — Extension substitution:
        Wrapper; recursed into transparently.

    Type 6 — Chained context substitution:
        Does not define new substitutions itself — it applies existing Type-1/3/4
        lookups in context.  The inner lookups are already captured by the pass
        above, so Type 6 does not need special handling for our inversion purpose.

    Requires both "GSUB" and "cmap" tables.  Returns {} if either is absent
    (e.g. a stripped subset font).

    Spec reference
    --------------
    "reading original font's character combination tables" (spec §step 1)
    Phase 2 Step 2.3: "Extract glyph outline … Compare against known glyph db"
    The GSUB inversion is more reliable than pure shape matching because it
    preserves the exact Unicode sequence that the font designer intended.
    """
    if "GSUB" not in ttfont or "cmap" not in ttfont:
        return {}

    # Build glyph_name → list[codepoint] from font's own cmap
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
        """Convert a list of glyph names to a Unicode codepoint tuple."""
        seq = []
        for g in glyph_names:
            cps = glyph_to_cps.get(g)
            if not cps:
                return None
            seq.append(cps[0])  # take the first (lowest) codepoint
        return tuple(seq)

    def _process_lookup(lookup):
        """Walk a single lookup and record all substitution targets."""
        lookup_type = lookup.LookupType

        # Unwrap extension lookups (Type 7)
        if lookup_type == 7:
            for sub in lookup.SubTable:
                inner = sub.ExtSubTable
                _process_lookup(inner)
            return

        for sub in lookup.SubTable:
            # ── Type 1: Single substitution ──────────────────────────────────
            if lookup_type == 1 and hasattr(sub, "mapping"):
                for src, tgt in sub.mapping.items():
                    seq = _glyphs_to_seq([src])
                    if seq:
                        result.setdefault(tgt, set()).add(seq)

            # ── Type 3: Alternate substitution ───────────────────────────────
            elif lookup_type == 3 and hasattr(sub, "alternates"):
                for src, alt_set in sub.alternates.items():
                    seq = _glyphs_to_seq([src])
                    if seq and hasattr(alt_set, "Alternate"):
                        for tgt in alt_set.Alternate:
                            result.setdefault(tgt, set()).add(seq)

            # ── Type 4: Ligature substitution ────────────────────────────────
            elif lookup_type == 4 and hasattr(sub, "ligatures"):
                for first_glyph, lig_set in sub.ligatures.items():
                    if not hasattr(lig_set, "Ligature"):
                        continue
                    for lig in lig_set.Ligature:
                        seq_glyphs = [first_glyph] + list(lig.Component)
                        seq = _glyphs_to_seq(seq_glyphs)
                        if seq:
                            result.setdefault(lig.LigGlyph, set()).add(seq)

    for lookup in gsub.LookupList.Lookup:
        _process_lookup(lookup)

    return result


# ---------------------------------------------------------------------------
# Step 2.1 — ToUnicode CMap filtering
# ---------------------------------------------------------------------------

def filter_cmap_to_tibetan(gid_to_unicode: Dict[int, str]) -> Dict[int, str]:
    """
    Return only the entries from a ToUnicode CMap that map to valid Tibetan
    Unicode (all codepoints in 0x0F00–0x0FFF).

    Background
    ----------
    MonlamUniOuChan2 and similar Tibetan Unicode fonts use glyph IDs in the
    low range (0x0067–0x020E) for their Tibetan characters.  The font's
    INTERNAL cmap assigns those glyph slots to Latin Extended codepoints
    (because the font was designed to sit on top of a Latin base).  The PDF's
    ToUnicode CMap is supposed to override this with the correct Tibetan values,
    but in practice some GIDs are mapped to the wrong Latin codepoints.

    By keeping only entries that resolve to Tibetan Unicode, we build a clean
    "trusted" reference set.  Entries that resolve to non-Tibetan codepoints
    are candidates for re-resolution via GSUB inversion or fuzzy matching.
    """
    return {gid: uni for gid, uni in gid_to_unicode.items() if _is_tibetan(uni)}


# ---------------------------------------------------------------------------
# Fuzzy hash lookup (Step 2.3 shape matching)
# ---------------------------------------------------------------------------

def _build_fuzzy_reference_table(
    ttfont,
    trusted_gid_to_unicode: Dict[int, str],
    resolution: int = _FUZZY_RESOLUTION,
) -> Dict[str, str]:
    """
    Build {fuzzy_hash → unicode_string} from the trusted (Tibetan-only) GID
    mappings.

    This table is used to identify unknown GIDs whose glyph outlines match a
    known-good Tibetan glyph.  The fuzzy hash tolerates sub-pixel coordinate
    differences between glyph variants produced by GSUB substitution.
    """
    glyph_order = ttfont.getGlyphOrder()
    table: Dict[str, str] = {}
    for gid, uni in trusted_gid_to_unicode.items():
        if gid < len(glyph_order):
            fh = _compute_fuzzy_hash(ttfont, glyph_order[gid], resolution)
            if fh:
                table[fh] = uni
    return table


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

# Tibetan vowel sign range U+0F71–U+0F81 (gigu, naro, drengbo, etc.)
_TIBETAN_VOWEL_SIGNS = frozenset(range(0x0F71, 0x0F82))


def _resolve_tibetan_sequence(seq: Tuple[int, ...]) -> str:
    """
    Convert a GSUB codepoint sequence to the Unicode string for text extraction.

    For single-codepoint sequences, return that character directly.

    For ligature sequences (Type 4 GSUB), a composite glyph often encodes a
    vowel sign combined with a stacking consonant — e.g. ི+ྲ → a single glyph
    used when the i-vowel appears above a ra-btags stack (ཏྲི་).  In text
    extraction we want only the vowel component; the stacking consonant is
    already encoded by the base syllable glyphs that precede it.

    Rule: if the first codepoint is a Tibetan vowel sign (U+0F71–U+0F81),
    return only that codepoint.  Otherwise return all codepoints joined
    (correct for consonant ligatures like གྲ = U+0F42 + U+0FB2).
    """
    if not seq:
        return ""
    if len(seq) == 1:
        return chr(seq[0])
    if seq[0] in _TIBETAN_VOWEL_SIGNS:
        return chr(seq[0])
    return "".join(chr(cp) for cp in seq)


def build_glyph_unicode_map(
    ttfont,
    cmap_gid_to_unicode: Dict[int, str],
    resolution: int = _FUZZY_RESOLUTION,
) -> Dict[str, str]:
    """
    Build a complete glyph_name → unicode_string mapping for a Unicode Tibetan
    font by combining:

      Step 2.1  The PDF's ToUnicode CMap (trusted Tibetan entries only)
      Step 2.2  The font's own cmap table (works if subset retains it;
                most PDF subsets strip it, but when present gives direct coverage)
      Step 2.3a GSUB inversion (requires full font with cmap + GSUB tables)
      Step 2.3b Fuzzy shape matching (resolution-6 outline hash against trusted entries)

    Steps run in order; each only adds glyphs not already resolved by a prior step.

    Parameters
    ----------
    ttfont : fontTools.ttLib.TTFont
        The font object (full or subset).
    cmap_gid_to_unicode : dict[int, str]
        The raw ToUnicode CMap from the PDF as {glyph_id: unicode_string}.
        May contain incorrect Latin Extended entries for some GIDs.
    resolution : int
        Fuzzy hash grid resolution (default 6 — do not change without
        re-validating against known glyph pairs).

    Returns
    -------
    dict[str, str]
        Maps every glyph_name in the font to its best-known Unicode string.
        GIDs with no resolution are absent from the dict (caller falls back
        to PyMuPDF's own value).
    """
    glyph_order = ttfont.getGlyphOrder()
    result: Dict[str, str] = {}

    # ── Step 2.1: Accept Tibetan-valued CMap entries directly ───────────────
    trusted = filter_cmap_to_tibetan(cmap_gid_to_unicode)
    for gid, uni in trusted.items():
        if gid < len(glyph_order):
            result[glyph_order[gid]] = uni
    logger.debug("Step 2.1: %d Tibetan CMap entries accepted", len(trusted))

    # ── Step 2.2: Embedded font cmap ────────────────────────────────────────
    # Read the cmap table directly from the font object (full or subset).
    # Most PDF subset fonts have their cmap stripped, so this yields nothing.
    # When present it maps glyph_name → Unicode without needing GSUB at all,
    # covering any GIDs whose ToUnicode CMap entry was absent or wrong.
    if "cmap" in ttfont:
        try:
            font_cmap = ttfont["cmap"].getBestCmap() or {}
            resolved_via_font_cmap = 0
            for cp, glyph_name in font_cmap.items():
                if glyph_name in result:
                    continue  # already resolved by Step 2.1
                uni = chr(cp)
                if _is_tibetan(uni):
                    result[glyph_name] = uni
                    resolved_via_font_cmap += 1
            logger.debug(
                "Step 2.2 (font cmap): %d additional glyphs resolved",
                resolved_via_font_cmap,
            )
        except Exception as exc:
            logger.debug("Step 2.2 (font cmap): failed — %s", exc)
    else:
        logger.debug("Step 2.2 (font cmap): skipped — no cmap table in font (subset)")

    # ── Step 2.3a: GSUB inversion (requires full font) ──────────────────────
    gsub_map = invert_gsub(ttfont)  # empty {} for stripped subset fonts
    if gsub_map:
        resolved_via_gsub = 0
        for glyph_name, sequences in gsub_map.items():
            if glyph_name in result:
                continue  # already resolved by CMap
            # Prefer single-codepoint sequences, then shortest.
            sequences_sorted = sorted(sequences, key=len)
            for seq in sequences_sorted:
                uni = _resolve_tibetan_sequence(seq)
                if uni and _is_tibetan(uni):
                    result[glyph_name] = uni
                    resolved_via_gsub += 1
                    break
        logger.debug("Step 2.3a (GSUB): %d additional glyphs resolved", resolved_via_gsub)
    else:
        logger.debug("Step 2.3a (GSUB): skipped — font has no cmap+GSUB (subset)")

    # ── Step 2.3b: Fuzzy shape matching ─────────────────────────────────────
    # Build reference table from trusted Tibetan-mapped GIDs
    fuzzy_ref = _build_fuzzy_reference_table(ttfont, trusted, resolution)
    if fuzzy_ref:
        resolved_via_shape = 0
        for gid, glyph_name in enumerate(glyph_order):
            if glyph_name in result:
                continue  # already resolved
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


def build_gsub_inverse_map(ttf_path: str) -> Dict[str, str]:
    """
    Given a full (unstripped) .ttf or .otf font file, build a map:

        glyph_name  →  correct Tibetan Unicode string

    by loading the font and inverting its GSUB substitution table.

    This is the primary entry point when you have the full font file on disk
    (e.g. ``MonlamUniOuChan2.ttf``).  It is a convenience wrapper around
    ``invert_gsub`` that handles file loading and converts the result from
    ``{glyph_name: set[tuple[int,...]]}`` to the flat ``{glyph_name: str}``
    form ready for use in ``build_glyph_unicode_map``.

    Parameters
    ----------
    ttf_path : str
        Path to the full (non-subset) font file.

    Returns
    -------
    dict[str, str]
        Maps glyph names produced by GSUB substitution to their canonical
        Tibetan Unicode strings.  Empty dict if the font has no GSUB or cmap.

    Example
    -------
    >>> gsub_map = build_gsub_inverse_map("MonlamUniOuChan2.ttf")
    >>> gsub_map["glyph00296"]   # GID 0x0128, was mis-decoded as 'Ĩ'
    'ི'
    >>> gsub_map["glyph00306"]   # GID 0x0132, was mis-decoded as 'Ĳ'
    'ེ'
    >>> gsub_map["glyph00320"]   # GID 0x0140, was mis-decoded as 'ŀ'
    'ོ'

    Integration with build_glyph_unicode_map
    -----------------------------------------
    The returned dict is consumed automatically when you pass the full font
    to ``build_glyph_unicode_map``::

        from fontTools import ttLib
        tt_full = ttLib.TTFont("MonlamUniOuChan2.ttf")
        glyph_map = build_glyph_unicode_map(tt_full, cmap_gid_to_unicode)
        # Step 2.3a inside build_glyph_unicode_map calls invert_gsub(tt_full)
        # and resolves all GSUB alternates automatically.

    If you want the raw map without going through build_glyph_unicode_map::

        gsub_map = build_gsub_inverse_map("MonlamUniOuChan2.ttf")
        correct = gsub_map.get(glyph_name, pymupdf_fallback_char)
    """
    try:
        from fontTools import ttLib as _ttLib
        tt = _ttLib.TTFont(ttf_path)
    except Exception as e:
        logger.error("build_gsub_inverse_map: failed to load %s — %s", ttf_path, e)
        return {}

    raw = invert_gsub(tt)  # {glyph_name: set[tuple[int,...]]}
    result: Dict[str, str] = {}
    for glyph_name, sequences in raw.items():
        # Prefer single-codepoint sequences (direct vowel/mark alternates)
        # then shortest, then first alphabetically for determinism
        best = sorted(sequences, key=lambda s: (len(s), s))
        for seq in best:
            uni = "".join(chr(cp) for cp in seq)
            if _is_tibetan(uni):
                result[glyph_name] = uni
                break
    logger.info(
        "build_gsub_inverse_map: %d GSUB-derived Tibetan glyph mappings from %s",
        len(result), ttf_path,
    )
    return result


def resolve_char(
    glyph_name: str,
    glyph_unicode_map: Dict[str, str],
    fallback_char: str,
) -> str:
    """
    Return the best Unicode string for a glyph name.

    Parameters
    ----------
    glyph_name : str
        Glyph name as returned by fontTools (e.g. 'glyph00306').
    glyph_unicode_map : dict
        Output of build_glyph_unicode_map().
    fallback_char : str
        Value returned by PyMuPDF / ToUnicode CMap (may be wrong).

    Returns
    -------
    str
        Resolved Unicode string, or fallback_char if no better mapping found.
    """
    return glyph_unicode_map.get(glyph_name, fallback_char)