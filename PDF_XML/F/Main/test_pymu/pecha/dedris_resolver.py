"""
dedris_resolver.py — TibetanMachine / Dedris legacy font decoder for PDF extraction
=====================================================================================

Converts ASCII text extracted by PyMuPDF from legacy TibetanMachine /
TibetanMachineWeb (Dedris-family) Type1 PDF fonts into proper Unicode Tibetan.

Integration with dedris_converter.py
-------------------------------------
This module handles the **PDF** side of Dedris decoding.  The companion
``dedris_converter.py`` handles the **RTF / DOCX** side, where the font name in
the source document is literally ``"Dedris-a"``, ``"Dedris-vowa"`` etc. and the
text is already in the raw Dedris byte encoding.

In PDFs the situation is different:

* Font names are obfuscated subset names like ``"TT1EA4o00"``.
* PyMuPDF has already resolved PostScript glyph names → ASCII:
  ``/K`` → ``"K"``, ``/dollar`` → ``"$"``, ``/hyphen`` → ``"-"`` …
* Spaces (U+0020) between spans are **font-subset fragment separators** — they
  do NOT correspond to the TibetanMachineWeb space glyph (which would map to
  ཇ in the base table, clearly wrong).  They must be stripped before conversion
  and re-inserted after.

Conversion backend
------------------
When ``pytiblegenc`` is available (the same library used by ``dedris_converter.py``),
``convert_string`` is called with ``font_name="TibetanMachineWeb"`` — confirmed
to be the highest-scoring TM variant against real PDFs.

A compact fallback table (derived from pytiblegenc's own ``utfc.csv``) is used
when pytiblegenc is not installed, keeping the module self-contained.

Public API
----------
``is_dedris_font(font_obj_str) -> bool``
    Returns True if the combined PDF font dict / FontDescriptor / Encoding
    object string belongs to a TibetanMachine-family Type1 font.

``decode_tibetan_machine(text) -> str``
    Decode one span's worth of text.  Splits on spaces (fragment separators),
    converts each fragment via pytiblegenc (or the fallback table), rejoins.

``should_decode_span(text, decoded) -> bool``
    Post-decode guard: True only when decoded is genuine Tibetan and the
    original is not an English title, catalog ID, or Latin sentence.

``get_stats() -> dict``
    Returns the pytiblegenc conversion stats dict (same shape as
    ``dedris_converter.STATS``).  Populated only when pytiblegenc is available.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# pytiblegenc backend — preferred when available
# ---------------------------------------------------------------------------
try:
    from pytiblegenc import convert_string as _pytiblegenc_convert_string
    _PYTIBLEGENC_AVAILABLE = True
except ImportError:
    _PYTIBLEGENC_AVAILABLE = False
    _pytiblegenc_convert_string = None  # type: ignore

# Shared stats dict — same shape as dedris_converter.STATS so callers can
# inspect a single object regardless of which module did the conversion.
_STATS: dict = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0,
    "skipped_non_dedris": [],
    "converted_suspicious": [],
}


def get_stats() -> dict:
    """Return the current pytiblegenc conversion stats (same shape as dedris_converter.STATS)."""
    return _STATS


# ---------------------------------------------------------------------------
# Fallback table — used only when pytiblegenc is NOT installed.
# Source: pytiblegenc/font-tables/utfc.csv, variant "TibetanMachineWeb".
# Keys are the single ASCII characters that PyMuPDF outputs after resolving
# PostScript glyph names.
# NOTE: space (U+0020) is intentionally absent — in PDF spans, spaces are
# font-subset fragment separators, not TibetanMachineWeb glyphs.
# ---------------------------------------------------------------------------
_FALLBACK_TABLE: dict[str, str] = {
    "!": "\u0f40",          # ཀ  KA
    '"': "\u0f41",          # ཁ  KHA
    "#": "\u0f42",          # ག  GA
    "$": "\u0f44",          # ང  NGA
    "%": "\u0f45",          # ཅ  CA
    "&": "\u0f46",          # ཆ  CHA
    "'": "\u0f47",          # ཇ  JA
    "(": "\u0f49",          # ཉ  NYA
    ")": "\u0f4f",          # ཏ  TA
    "*": "\u0f50",          # ཐ  THA
    "+": "\u0f51",          # ད  DA
    ",": "\u0f53",          # ན  NA
    "-": "\u0f0b",          # ་  tsheg
    ".": "\u0f54",          # པ  PA
    "/": "\u0f55",          # ཕ  PHA
    "0": "\u0f56",          # བ  BA
    "1": "\u0f58",          # མ  MA
    "2": "\u0f59",          # ཙ  TSA
    "3": "\u0f5a",          # ཚ  TSHA
    "4": "\u0f5b",          # ཛ  DZA
    "5": "\u0f5d",          # ཝ  WA
    "6": "\u0f5e",          # ཞ  ZHA
    "7": "\u0f5f",          # ཟ  ZA
    "8": "\u0f60",          # འ  -A
    "9": "\u0f61",          # ཡ  YA
    ":": "\u0f62",          # ར  RA
    ";": "\u0f63",          # ལ  LA
    "<": "\u0f64",          # ཤ  SHA
    "=": "\u0f66",          # ས  SA
    ">": "\u0f67",          # ཧ  HA
    "?": "\u0f68",          # ཨ  A
    "@": "\u0f4a",          # ཊ  TTRA (Sanskrit retroflex)
    "A": "\u0f4b",          # ཋ  TTHA
    "B": "\u0f4c",          # ཌ  DDA
    "C": "\u0f4e",          # ཎ  NNA
    "D": "\u0f65",          # ཥ  SSHA
    "E": "\u0f40\u0fb5",    # ཀྵ  KA+subj.SSA
    "F": "\u0f62\u0f90",    # རྐ  RA+subj.KA
    "G": "\u0f62\u0f92",    # རྒ  RA+subj.GA
    "H": "\u0f62\u0f94",    # རྔ  RA+subj.NGA
    "I": "\u0f62\u0f97",    # རྗ  RA+subj.JA
    "J": "\u0f62\u0f99",    # རྙ  RA+subj.NYA
    "K": "\u0f62\u0f9f",    # རྟ  RA+subj.TA
    "L": "\u0f62\u0fa1",    # རྡ  RA+subj.DA
    "M": "\u0f62\u0fa3",    # རྣ  RA+subj.NA
    "N": "\u0f62\u0fa6",    # རྦ  RA+subj.BA
    "O": "\u0f62\u0fa8",    # རྨ  RA+subj.MA
    "P": "\u0f62\u0fa9",    # རྩ  RA+subj.TSA
    "Q": "\u0f62\u0fab",    # རྫ  RA+subj.DZA
    "R": "\u0f63\u0f90",    # ལྐ  LA+subj.KA
    "S": "\u0f63\u0f92",    # ལྒ  LA+subj.GA
    "T": "\u0f63\u0f94",    # ལྔ  LA+subj.NGA
    "U": "\u0f63\u0f95",    # ལྕ  LA+subj.CA
    "V": "\u0f63\u0f97",    # ལྗ  LA+subj.JA
    "W": "\u0f63\u0f9f",    # ལྟ  LA+subj.TA
    "X": "\u0f63\u0fa1",    # ལྡ  LA+subj.DA
    "Y": "\u0f63\u0fa5",    # ལྤ  LA+subj.PHA
    "Z": "\u0f63\u0fa6",    # ལྦ  LA+subj.BA
    "[": "\u0f63\u0fb7",    # ལྷ  LA+subj.HA
    "\\": "\u0f40",         # ཀ  KA (alternate)
    "]": "\u0f42",          # ག  GA (alternate)
    "^": "\u0f49",          # ཉ  NYA (alternate)
    "_": "\u0f4f",          # ཏ  TA (alternate)
    "`": "\u0f51",          # ད  DA (alternate)
    "a": "\u0f53",          # ན  NA (alternate)
    "b": "\u0f5e",          # ཞ  ZHA (alternate)
    "c": "\u0f64",          # ཤ  SHA (alternate)
    "d": "\u0f67",          # ཧ  HA (alternate)
    "e": "\u0f62\u0f9f",    # རྟ  RA+subj.TA (alternate)
    "f": "\u0f67",          # ཧ  HA (alternate)
    "g": "\u0f11",          # ༑  MARK CLOSING BRACES
    "h": "\u0f08",          # ༈  MARK INTERSYLLABIC
    "i": "\u0f14",          # ༔  MARK CLOSING
    "j": "\u0f34",          # ༴  MARK DELIMITER
    "k": "\u0f0d",          # །  SHAD (sentence delimiter)
    "l": "\u0f0b",          # ་  tsheg (alternate)
    "m": "\u0f72",          # ི  I vowel
    "n": "\u0f72",          # ི  I vowel (alternate)
    "o": "\u0f74",          # ུ  U vowel
    "p": "\u0f74",          # ུ  U vowel (alternate)
    "q": "\u0f74",          # ུ  U vowel (alternate)
    "r": "\u0f74",          # ུ  U vowel (alternate)
    "s": "\u0f74",          # ུ  U vowel (alternate)
    "t": "\u0f74",          # ུ  U vowel (alternate)
    "u": "\u0f74",          # ུ  U vowel (alternate)
    "v": "\u0f74",          # ུ  U vowel (alternate)
    "w": "\u0f74",          # ུ  U vowel (alternate)
    "x": "\u0f74",          # ུ  U vowel (alternate)
    "y": "\u0f74",          # ུ  U vowel (alternate)
    "z": "\u0f74",          # ུ  U vowel (alternate)
    "{": "\u0f7a",          # ེ  E vowel
    "|": "\u0f7a",          # ེ  E vowel (alternate)
    "}": "\u0f7c",          # ོ  O vowel
    "~": "\u0f7c",          # ོ  O vowel (alternate)
}

# The TibetanMachineWeb "visiblespace" glyph (U+2423 ␣).
# PyMuPDF occasionally emits this from WinAnsiEncoding.  Treat as a word-break
# space, not a Tibetan glyph.
_VISIBLE_SPACE = "\u2423"

# Font name to pass to pytiblegenc.convert_string for TM-family PDF spans.
_TM_FONT_NAME = "TibetanMachineWeb"


# ---------------------------------------------------------------------------
# Font detection helpers
# ---------------------------------------------------------------------------

_TM_GLYPH_NAMES = frozenset({
    "A","B","C","D","E","F","G","H","I","J","K","L","M",
    "N","O","P","Q","R","S","T","U","V","W","X","Y","Z",
    "a","b","c","d","e","f","g","h","i","j","k","l","m",
    "n","o","p","q","r","s","t","u","v","w","x","y","z",
    "exclam","quotedbl","numbersign","dollar","percent","ampersand",
    "quoteright","parenleft","parenright","asterisk","plus","comma",
    "hyphen","period","slash","colon","semicolon","less","equal",
    "greater","question","at","bracketleft","backslash","bracketright",
    "asciicircum","underscore","grave","braceleft","bar","braceright",
    "asciitilde","space","visiblespace","zero","one","two","three",
    "four","five","six","seven","eight","nine",
})

# Glyph names that indicate a Latin body-text font, not TM.
# A CharSet with ≥ 2 of these → reject.
_LATIN_ONLY_GLYPH_NAMES = frozenset({
    "a", "e", "i", "u",
    "quoteright", "quoteleft",
    "exclam", "quotedbl",
    "at",
})

_DIFF_NAME_RE = re.compile(r"/([A-Za-z][A-Za-z0-9]*)")
_BBOX_RE      = re.compile(r"/FontBBox\s*\[\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")
_CHARSET_RE   = re.compile(r"/CharSet\s*\(([^)]+)\)")


def is_dedris_font(font_obj_str: str) -> bool:
    """
    Return True if *font_obj_str* belongs to a TibetanMachine-family Type1 font.

    Pass the **concatenated** text of the PDF font dict + FontDescriptor object +
    Encoding object (see ``_build_dedris_font_set`` in ``pdf_extract.py``).
    CharSet lives in FontDescriptor; WinAnsiEncoding lives in the Encoding object —
    neither is present in the top-level font dict alone.

    Detection rules (all must pass)
    --------------------------------
    1. No Tibetan Unicode glyph names (``g0F40``, ``uni0F40``) → Monlam font.
    2. Not an Identity-H CID font → Monlam Unicode.
    3. A ``/CharSet`` must be present whose glyph names are all standard PS
       glyph names (letters, digit names, punctuation names like ``hyphen``,
       ``dollar`` …).  ``WinAnsiEncoding`` alone (without a CharSet) is NOT
       sufficient — generic TrueType fonts (Monlam TrueType companion,
       Calibri, Cambria) also carry WinAnsiEncoding but have no CharSet.
       Real TibetanMachine subset fonts always have a /CharSet.
    4. CharSet must NOT contain ≥ 2 Latin-only names (``a e i u quoteright`` …).
    5. FontBBox height ≥ 700 units (Tibetan tall ascenders + descenders).
    """
    # Rule 1: Tibetan Unicode glyph names → Monlam font, never TM
    if re.search(r"/(?:uni0[Ff][0-9A-Fa-f]{2}|g0[Ff][0-9A-Fa-f]{2})", font_obj_str):
        return False
    # Rule 2: CID/Identity-H → Monlam Unicode
    if "Identity-H" in font_obj_str or "/CIDFont" in font_obj_str:
        return False

    # Rule 3: CharSet is REQUIRED and must contain only standard PS glyph names.
    # WinAnsiEncoding alone is not accepted — it is present on many non-TM fonts
    # (e.g. Monlam Uni OuChan2 TrueType companion, Calibri, Cambria) that carry
    # no CharSet and should not be treated as TibetanMachine.
    charset_m = _CHARSET_RE.search(font_obj_str)
    if not charset_m:
        return False

    glyph_names = set(_DIFF_NAME_RE.findall(charset_m.group(1)))
    if not glyph_names or not glyph_names.issubset(_TM_GLYPH_NAMES):
        return False

    # Rule 4: reject Latin body-text fonts (a, e, i, u, quoteright …)
    if len(glyph_names & _LATIN_ONLY_GLYPH_NAMES) >= 2:
        return False

    # Rule 5: FontBBox height ≥ 700 units
    bbox_m = _BBOX_RE.search(font_obj_str)
    if bbox_m:
        if int(bbox_m.group(4)) - int(bbox_m.group(2)) < 700:
            return False

    return True


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def _convert_fragment(fragment: str) -> str:
    """
    Convert a single space-free TM-encoded fragment to Tibetan Unicode.

    Uses pytiblegenc.convert_string (same library as dedris_converter.py) when
    available, falling back to the built-in table otherwise.
    """
    if not fragment:
        return fragment

    # Strip visible-space glyph — treat as word-break, not a Tibetan character
    fragment = fragment.replace(_VISIBLE_SPACE, "")
    if not fragment:
        return ""

    if _PYTIBLEGENC_AVAILABLE:
        result = _pytiblegenc_convert_string(fragment, _TM_FONT_NAME, _STATS)
        if result is not None:
            return result
        # Fallback below if pytiblegenc returns None (shouldn't happen for TibetanMachineWeb)

    return "".join(_FALLBACK_TABLE.get(ch, ch) for ch in fragment)


def decode_tibetan_machine(text: str) -> str:
    """
    Decode a PyMuPDF span's worth of TibetanMachine-encoded ASCII text.

    Why spaces are split out
    ------------------------
    In TibetanMachine PDFs, a single Tibetan cluster is split across several
    tiny Type1 font subsets.  PyMuPDF merges those span texts into one string
    with spaces as separators, e.g. ``"K$- .0J- :.A-"``.  The space character
    is a fragment separator in this context — it does NOT correspond to a
    Tibetan glyph.  (The TibetanMachineWeb ``base`` table maps space to ཇ,
    which is wrong here and would corrupt the output.)

    Each space-delimited fragment is converted independently, then rejoined
    with spaces intact so downstream normalisation can handle spacing.

    Backend
    -------
    Delegates to ``pytiblegenc.convert_string("TibetanMachineWeb", …)`` when
    pytiblegenc is installed, which is the same library used by the companion
    ``dedris_converter.py`` module.  Falls back to the built-in table when
    pytiblegenc is not available.
    """
    if not text:
        return text
    fragments = text.split(" ")
    return " ".join(_convert_fragment(f) for f in fragments)


# ---------------------------------------------------------------------------
# Post-decode validation
# ---------------------------------------------------------------------------

def should_decode_span(text: str, decoded: str) -> bool:
    """
    Return True if the span should be replaced with its decoded Tibetan form.

    Filters out false positives on fonts that pass ``is_dedris_font`` but
    encode English titles, catalog IDs, or other non-Tibetan content.

    Rules
    -----
    1. Decoded must contain ≥ 1 Tibetan codepoint.
    2. Reject multi-token ALL-CAPS strings (len > 4, ``[A-Z0-9 -.]`` only) —
       matches "DEDICATION OF MERIT", "TI1055 - 12364" etc.
    3. Accept if original contains a TM-specific special char
       (``$%<>=?/()`` or visible-space U+2423) — never in genuine Latin text.
    4. Accept if decoded is 100 % Tibetan AND (single char OR no lowercase).
       - Single-char catches vowel/mark glyphs: ``"o"`` → ``ུ``, ``"8"`` → ``འ``.
       - No-lowercase guard rejects "Printed in Taiwan" / email addresses.
       - Uppercase+punct spans like ``"- :."`` → ``་རཔ`` pass (no lowercase).
    """
    if not text or not decoded:
        return False

    tib = sum(1 for c in decoded if 0x0F00 <= ord(c) <= 0x0FFF)
    if tib == 0:
        return False

    stripped = text.strip()

    # Rule 2: multi-token all-caps / catalog ID
    if len(stripped) > 4 and re.match(r'^[A-Z0-9\s\-\.]+$', stripped):
        return False

    # Rule 3: TM-specific special chars are a strong positive signal
    if any(c in '$%<>=?/()' for c in text) or _VISIBLE_SPACE in text:
        return True

    # Rule 4: 100 % Tibetan decode + no lowercase (or single char)
    decoded_no_space = decoded.replace(" ", "")
    if decoded_no_space and all(0x0F00 <= ord(c) <= 0x0FFF for c in decoded_no_space):
        if len(stripped) == 1 or not re.search(r'[a-z]', text):
            return True

    return False