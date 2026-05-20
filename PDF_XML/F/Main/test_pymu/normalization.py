import re
import unicodedata
from enum import Enum


# Wingdings / Wingdings2 ToUnicode often maps bullets and symbols to U+F020–U+F0FF (PUA).
_WINGDINGS_MS_PUA = re.compile(r"[\uF020-\uF0FF]")


def remove_wingdings_private_use(text: str) -> str:
    """Remove legacy Microsoft Wingdings/Wingdings2 private-use symbols from extracted text."""
    if not text:
        return text
    return _WINGDINGS_MS_PUA.sub("", text)


# ── Consonant-cluster duplicate removal ─────────────────────────────────────────
#
# InDesign archival PDFs sometimes emit each syllable's consonant stack twice in a
# single text run.  The two copies are adjacent (no tsheg/shad between them) and
# differ only in whether vowel signs are present on the first copy:
#
#   Pattern A — vowel only on second copy (shadow has bare consonants):
#       གྱགྱི   →  གྱི     རྒྱརྒྱལ  →  རྒྱལ
#
#   Pattern B — vowel present on BOTH copies (identical units):
#       ཆུཆུབ  →  ཆུབ    ཙཱཙཱ    →  ཙཱ

_UNIT_RE = re.compile(
    r'[\u0f40-\u0f6c]'                                   # Tibetan base consonant
    r'[\u0f8d-\u0fbc]*'                                   # subjoined consonants (0+)
    r'[\u0f71-\u0f84\u0f86\u0f87\u0f7e\u0f7f]*'         # vowel signs + marks (0+)
)
_NON_UNIT_RE = re.compile(
    r'[^\u0f40-\u0f6c\u0f8d-\u0fbc\u0f71-\u0f84\u0f86\u0f87\u0f7e\u0f7f]+'
)
_VOWEL_MARK_RE = re.compile(r'[\u0f71-\u0f84\u0f86\u0f87\u0f7e\u0f7f]')


def _has_tibetan_vowel_mark(unit: str) -> bool:
    """True if *unit* contains at least one Tibetan vowel / dependent vowel mark."""
    return bool(_VOWEL_MARK_RE.search(unit))


def _consonant_skeleton(unit: str) -> str:
    """Return *unit* with all vowel signs stripped, leaving only base + subjoineds."""
    return _VOWEL_MARK_RE.sub("", unit)


def collapse_duplicate_consonant_clusters(text: str) -> str:
# Remove InDesign shadow stacks: bare consonant copy + vowelled copy (Pattern A),
    if not text:
        return text

    tokens: list[tuple[str, bool]] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _UNIT_RE.match(text, pos)
        if m:
            tokens.append((m.group(), True))
            pos = m.end()
            continue
        m = _NON_UNIT_RE.match(text, pos)
        if m:
            tokens.append((m.group(), False))
            pos = m.end()
            continue
        tokens.append((text[pos], False))
        pos += 1

    result: list[str] = []
    i = 0
    while i < len(tokens):
        tok, is_unit = tokens[i]
        if is_unit and i + 1 < len(tokens) and tokens[i + 1][1]:
            nxt = tokens[i + 1][0]
            if _consonant_skeleton(tok) == _consonant_skeleton(nxt):
                pattern_a = (
                    not _has_tibetan_vowel_mark(tok)
                    and _has_tibetan_vowel_mark(nxt)
                )
                pattern_b = (
                    tok == nxt
                    and (
                        _has_tibetan_vowel_mark(tok)
                        or len(tok) > 1
                    )
                )
                if pattern_a or pattern_b:
                    i += 1  # skip shadow copy; next iteration keeps the real copy
                    continue
        result.append(tok)
        i += 1

    return "".join(result)


# -------------------------------------------------------------------------
# Precompiled patterns & translation tables

# Normalize all line breaks to '\n'
_LINEBREAKS_RE = re.compile(r"\r\n?|\u0085|\u2028|\u2029")

# Zero-width and invisible characters to remove (includes BOM everywhere)
_ZERO_WIDTH_STRIP = dict.fromkeys(map(ord, [
    "\u200B",  # ZERO WIDTH SPACE
    "\u2060",  # WORD JOINER
    "\uFEFF",  # ZERO WIDTH NO-BREAK SPACE / BOM (remove even mid-text)
    "\u180E",  # MONGOLIAN VOWEL SEPARATOR (deprecated)
    "\u034F",  # COMBINING GRAPHEME JOINER
]))

# Map all Unicode spaces (and horizontal ASCII whitespace) to ASCII space
_UNICODE_SPACES = [
    "\u00A0",  # NO-BREAK SPACE
    "\u1680", "\u2000", "\u2001", "\u2002", "\u2003", "\u2004",
    "\u2005", "\u2006", "\u2007", "\u2008", "\u2009", "\u200A",
    "\u202F", "\u205F", "\u3000",  # narrow, medium, ideographic spaces
    "\t", "\x0b", "\x0c"           # TAB, VT, FF
]
_SPACE_TO_ASCII = {ord(ch): " " for ch in _UNICODE_SPACES}

# Consecutive duplicate Tibetan combining marks (vowels, subjoined, etc.) from
# layered PDF extraction.  Broader than vowel-only; see normalize_unicode step 10.
_COLLAPSE_DUP_TIB_MARKS_RE = re.compile(
    r"([\u0f71-\u0f87\u0f8d-\u0fbc\u0f35\u0f37\u0f39])\1+"
)

# InDesign section running headers: UTF-16-BE code units in angle brackets.
# <FEFF0053006500630031003A> = BOM + "Sec1:" ; 0032003A = "Sec2:"
_INDESIGN_SECTION_MARKER_RE = re.compile(
    r"<FEFF005300650063003[12]003A>"
    r"(?:[IVXLCDMivxlcdm]+|\d+)?"
)
_FS_ONLY_ROMAN_HEADER_RE = re.compile(
    r"(?:^|\n)<fs:\d+>\s*[IVXLCDMivxlcdm]+\s*(?=\n)"
)
_ROMAN_LINE_BEFORE_PAGE_BREAK_RE = re.compile(
    r"(?:^|\n)\s*[IVXLCDMivxlcdm]{1,6}\s*(?=\n+\s*ZZZZ:)"
)


def collapse_duplicate_tibetan_marks(text: str) -> str:
    """
    Universally collapse consecutive identical Tibetan combining marks caused by overlapping text layers in PDFs.
    """
    if not text:
        return text
    return _COLLAPSE_DUP_TIB_MARKS_RE.sub(r"\1", text)


def remove_indesign_section_markers(text: str) -> str:
    """
    Remove InDesign section running headers encoded as UTF-16-BE hex in angle brackets,
    e.g. ``<FEFF0053006500630031003A>III`` (BOM + "Sec1:" + roman numeral).
    """
    if not text:
        return text
    s = _INDESIGN_SECTION_MARKER_RE.sub("", text)
    s = _FS_ONLY_ROMAN_HEADER_RE.sub("\n", s)
    s = _ROMAN_LINE_BEFORE_PAGE_BREAK_RE.sub("\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s


def fix_pdf_glyph_to_unicode_artifacts(text: str) -> str:
    """
    Repair common Monlam / legacy PDF ToUnicode mistakes (Latin PUA fallbacks).
    Observed in IE3KG647 et al.:
      - U+0140 (ŀ) used for Tibetan vowel sign o (U+0F7C)
      - U+0132 (Ĳ) used inside ཚིག / ཚེས / ཚིགས / མཛེས / …
    """
    if not text:
        return text
    s = text
    # Ľ (U+013D): MuPDF GID-as-Unicode fallback for tib.Naro.Anusvara ligature.
    # Always follows ཨ to form OM (ཨོཾ). Map to ོཾ so preceding ཨ completes it.
    s = s.replace("Ľ", "\u0f7c\u0f7e")
    # † / ‡ (U+2020 / U+2021): WinAnsi CP byte 0x86/0x87 → Monlam dot-leader glyph.
    s = s.replace("\u2020", ".").replace("\u2021", ".")
    # ŀ: fix syllables that must stay མཚན (mtshan) before global ŀ → ོ
    s = s.replace("མཚŀན", "མཚན")
    s = s.replace("ŀ", "\u0f7c")

    # Ĳ: longer matches first
    s = s.replace("མཛĲས", "མཛེས")
    s = s.replace("མཛĲད", "མཛེད")
    s = s.replace("འཚĲར", "འཆར")
    s = s.replace("ཚĲག", "ཚིག")
    s = re.sub(r"ཚĲས(?=་[\u0f20-\u0f29])", "ཚེས", s)
    s = re.sub(r"ཚĲས(?=\s+སྐ)", "ཚིགས", s)
    s = re.sub(r"ཚĲས(?=\s+སྣ)", "ཚིགས", s)
    s = re.sub(r"ཚĲས(?=\s)", "ཚིགས", s)
    s = s.replace("ཚĲས", "ཚེས")
    # Colophon / grammar: ཚĲ་སྐབས (tsheg after Ĳ, not ASCII space)
    s = re.sub(r"ཚĲ(?=་སྐ)", "ཚིགས", s)
    s = re.sub(r"ཚĲ(?=་སྣ)", "ཚིགས", s)
    s = re.sub(r"ཚĲ(?=[བཔ])", "ཚིག", s)
    s = re.sub(r"ཚĲ(?=\s)", "ཚིགས", s)
    s = s.replace("ཚĲ", "ཚེ")
    s = re.sub(r"([\u0f00-\u0fff])Ĳ", r"\1" + "\u0f7a", s)
    return s


def normalize_tibetan_boundary_spaces(text: str) -> str:
    """Insert a single ASCII space where print PDFs separate shad/tsheg from the next unit."""
    if not text:
        return text
    s = text
    s = re.sub(r"(\u0f0d)([\u0f40-\u0f6c])", r"\1 \2", s)
    s = re.sub(r"(\u0f0b)([\u0f20-\u0f33])", r"\1 \2", s)
    s = re.sub(r"(\u0f0d)([\u0f20-\u0f33])", r"\1 \2", s)
    # e.g. ༢༠༡༣ཟླ་ → ༢༠༡༣ ཟླ་ (Tibetan digits then syllable, common in colophons)
    s = re.sub(r"([\u0f20-\u0f33])([\u0f40-\u0f6c])", r"\1 \2", s)
    s = re.sub(r" {2,}", " ", s)
    return s


def normalize_spaces(
    text: str,
    collapse_internal_spaces: bool = True,
    tibetan_specific: bool = True,
) -> str:
    """
    Normalize spaces in text.
    Steps:
      1. Collapse multiple newlines to one.
      2. Remove spaces next to newlines.
      3. Collapse multiple spaces to one.
      4. Apply Tibetan-specific space normalization rules.
    """
    if not text:
        return ""

    s = text

    # 1) Collapse multiple newlines
    s = re.sub(r"\n{2,}", "\n", s)

    # 2) Remove spaces next to newlines, but preserve a single space that
    # may be the only separator between a line-ending shad/letter and the
    # content beginning the next line (edge case: keep at most one space).
    s = re.sub(r"[ ]{2,}\n", "\n", s)   # collapse multiple trailing spaces → nothing
    s = re.sub(r"[ ]\n", "\n", s)        # drop the single trailing space
    s = re.sub(r"\n[ ]{2,}", "\n", s)    # collapse multiple leading spaces → nothing
    # Do NOT strip single leading space after \n — it may be a word separator

    # 3) Collapse space runs
    if collapse_internal_spaces:
        s = re.sub(r" {2,}", " ", s)

    # 4) Tibetan-specific space normalization
    if tibetan_specific:
        # Remove space between a Tibetan consonant/stack and its following tsheg or
        # shad — both are punctuation that belong to the preceding syllable.
        # U+0F0B/0F0C/0FD2 = tsheg variants; U+0F0D–U+0F11 = shad variants.
        s = re.sub(r"([\u0f40-\u0fbc]) +([\u0f0b\u0f0c\u0fd2\u0f0d-\u0f11])", r"\1\2", s)
        # Remove space after tsheg ONLY when it is immediately followed by another
        # tsheg/shad — that is pure punctuation noise. Do NOT strip the space after
        # tsheg when it precedes a consonant or digit: that space is a legitimate
        # inter-syllable or inter-word separator in printed Tibetan.
        s = re.sub(r"([\u0f0b\u0f0c\u0fd2]) +([\u0f0b\u0f0c\u0fd2\u0f0d-\u0f11])", r"\1\2", s)
        # NOTE: spaces after shad (U+0F0D–U+0F11) before a consonant are kept;
        # they are sentence/paragraph separators and must be preserved in the XML.

    return s


def normalize_unicode(
    text: str,
    strip_control: bool = True,
    collapse_internal_spaces: bool = True,
) -> str:
    """
    General-purpose Unicode normalization.

    Steps:
      1. Normalize to NFC.
      2. Convert all line breaks to '\\n'.
      3. Remove zero-width / invisible characters (incl. all BOMs).
      4. Map Unicode spaces and tabs to plain ASCII space.
      5. Optionally remove control characters (except newline).
      6. Normalize spaces (including Tibetan-specific rules).
      6b. Fix PDF cmap / legacy font mis-encodings (Latin PUA → Tibetan).
      8. Remove Wingdings/Wingdings2 PUA symbols (U+F020–U+F0FF).
      9. Apply Tibetan Unicode normalization (decomposition, reorder).
      9b. Collapse intra-line consonant-cluster duplicates (InDesign shadow text).
      10. Safety-net: collapse consecutive duplicate Tibetan combining marks.

    Keeps ZWJ/ZWNJ (joiners) intact.
    """
    if not text:
        return ""

    # 1) NFC normalization
    s = unicodedata.normalize("NFC", text)

    # 2) Normalize line breaks
    s = _LINEBREAKS_RE.sub("\n", s)

    # 3) Remove zero-width & BOM
    s = s.translate(_ZERO_WIDTH_STRIP)

    # 4) Normalize spaces to ASCII space
    s = s.translate(_SPACE_TO_ASCII)

    # 5) Optionally strip control characters (but keep newline)
    if strip_control:
        s = "".join(
            ch for ch in s
            if ch == "\n" or (unicodedata.category(ch)[0] != "C")
        )

    # 6) Normalize spaces
    s = normalize_spaces(s, collapse_internal_spaces=collapse_internal_spaces)

    # 6b) PDF cmap / legacy font mis-encodings (Latin letters standing in for Tibetan)
    s = fix_pdf_glyph_to_unicode_artifacts(s)

    # 6c) InDesign section running headers (UTF-16-BE hex + roman/arabic page labels)
    s = remove_indesign_section_markers(s)

    # 8) Wingdings/Wingdings2 bullets and dingbats (PUA safety net)
    s = remove_wingdings_private_use(s)

    # 9) Tibetan Unicode normalization
    s = normalize_unicode_tib(s)
    # 9b) Intra-line consonant-cluster duplicates from InDesign shadow text layers.
    s = collapse_duplicate_consonant_clusters(s)
    # 10) Safety-net: collapse consecutive identical Tibetan combining marks.
    s = collapse_duplicate_tibetan_marks(s)
    # no graphical distinction between 0f0b and 0f0c
    s = s.replace("\u0f0c", "\u0f0b")
    # double shad is just two shad
    s = s.replace("\u0f0e", "\u0f0d\u0f0d")

    return s


class Cats(Enum):
    Other = 0
    Base = 1
    Subscript = 2
    BottomVowel = 3
    BottomMark = 4
    TopVowel = 5
    TopMark = 6
    RightMark = 7


CATEGORIES = (
    [Cats.Other]  # 0F00
    + [Cats.Base]  # 0F01, often followed by 0f083
    + [Cats.Other] * 22  # 0F02-0F17
    + [Cats.BottomVowel] * 2  # 0F18-0F19
    + [Cats.Other] * 6  # 0F1A-0F1F
    + [Cats.Base] * 20  # 0F20-0F33: digits + occasional vowels
    + [Cats.Other]  # 0F34
    + [Cats.BottomMark]  # 0F35
    + [Cats.Other]  # 0F36
    + [Cats.BottomMark]  # OF37
    + [Cats.Other]  # 0F38
    + [Cats.Subscript]  # 0F39, kind of cheating but works
    + [Cats.Other] * 4  # 0F3A-0F3D
    + [Cats.RightMark]  # 0F3E
    + [Cats.Other]  # 0F3F, not quite sure
    + [Cats.Base] * 45  # 0F40-0F6C
    + [Cats.Other] * 4  # 0F6D-0F70
    + [Cats.BottomVowel]  # 0F71
    + [Cats.TopVowel]  # 0F72
    + [Cats.TopVowel]  # 0F73
    + [Cats.BottomVowel] * 2  # 0F74-0F75
    + [Cats.TopVowel] * 8  # 0F76-0F7D
    + [Cats.TopMark]  # 0F7E
    + [Cats.RightMark]  # 0F7F
    + [Cats.TopVowel] * 2  # 0F80-0F81
    + [Cats.TopMark] * 2  # 0F82-0F83
    + [Cats.BottomMark]  # 0F84
    + [Cats.Other]  # 0F85
    + [Cats.TopMark] * 2  # 0F86-0F87
    + [Cats.Base] * 2  # 0F88-0F89
    + [Cats.Base]  # 0F8A always followed by 0f82 (required by the Unicode spec)
    + [Cats.Other]  # 0F8B
    + [Cats.Base]  # 0F8C
    + [Cats.Subscript] * 48  # 0F8D-0FBC
)


def charcat(c):
    """Returns the category for a single char string"""
    o = ord(c)
    if 0x0F00 <= o <= 0x0FBC:
        return CATEGORIES[o - 0x0F00]
    return Cats.Other


def unicode_reorder(txt):
    charcats = [charcat(c) for c in txt]
    i = 0
    res = []
    valid = True
    while i < len(charcats):
        c = charcats[i]
        if c != Cats.Base:
            if c.value > Cats.Base.value:
                valid = False
            res.append(txt[i])
            i += 1
            continue
        j = i + 1
        while j < len(charcats) and charcats[j].value > Cats.Base.value:
            j += 1
        newindices = sorted(range(i, j), key=lambda e: (charcats[e].value, e))
        replaces = "".join(txt[n] for n in newindices)
        res.append(replaces)
        i = j
    return "".join(res), valid


def normalize_unicode_tib(s, form="nfd"):
    s = s.replace("\u0f73", "\u0f71\u0f72")
    s = s.replace("\u0f75", "\u0f71\u0f74")
    s = s.replace("\u0f77", "\u0fb2\u0f71\u0f80")
    s = s.replace("\u0f79", "\u0fb3\u0f71\u0f80")
    s = s.replace("\u0f81", "\u0f71\u0f80")
    if form == "nfd":
        s = s.replace("\u0f43", "\u0f42\u0fb7")
        s = s.replace("\u0f4d", "\u0f4c\u0fb7")
        s = s.replace("\u0f52", "\u0f51\u0fb7")
        s = s.replace("\u0f57", "\u0f56\u0fb7")
        s = s.replace("\u0f5c", "\u0f5b\u0fb7")
        s = s.replace("\u0f69", "\u0f40\u0fb5")
        s = s.replace("\u0f76", "\u0fb2\u0f80")
        s = s.replace("\u0f78", "\u0fb3\u0f80")
        s = s.replace("\u0f93", "\u0f92\u0fb7")
        s = s.replace("\u0f9d", "\u0f9c\u0fb7")
        s = s.replace("\u0fa2", "\u0fa1\u0fb7")
        s = s.replace("\u0fa7", "\u0fa6\u0fb7")
        s = s.replace("\u0fac", "\u0fab\u0fb7")
        s = s.replace("\u0fb9", "\u0f90\u0fb5")
    else:
        s = s.replace("\u0f42\u0fb7", "\u0f43")
        s = s.replace("\u0f4c\u0fb7", "\u0f4d")
        s = s.replace("\u0f51\u0fb7", "\u0f52")
        s = s.replace("\u0f56\u0fb7", "\u0f57")
        s = s.replace("\u0f5b\u0fb7", "\u0f5c")
        s = s.replace("\u0f40\u0fb5", "\u0f69")
        s = s.replace("\u0fb2\u0f80", "\u0f76")
        s = s.replace("\u0fb3\u0f80", "\u0f78")
        s = s.replace("\u0f92\u0fb7", "\u0f93")
        s = s.replace("\u0f9c\u0fb7", "\u0f9d")
        s = s.replace("\u0fa1\u0fb7", "\u0fa2")
        s = s.replace("\u0fa6\u0fb7", "\u0fa7")
        s = s.replace("\u0fab\u0fb7", "\u0fac")
        s = s.replace("\u0f90\u0fb5", "\u0fb9")
    s = s.replace("\u0f00", "\u0f68\u0f7c\u0f7e")
    s, valid = unicode_reorder(s)
    s = re.sub("\u0f6a(?![\u0f90-\u0f97\u0f9a-\u0fac\u0fae\u0faf\u0fb4-\u0fbc])", "ར", s)
    s = normalize_invalid_start_string(s)
    return s


def is_vowel(char: str) -> bool:
    return bool(re.search(r"[\u0f71-\u0f84]", char))


def is_suffix(char: str) -> bool:
    return bool(re.search(r"[\u0f90-\u0fbc]", char))


def normalize_invalid_start_string(s):
    if len(s) < 2:
        return s
    if is_vowel(s[0]) and not is_vowel(s[1]) and not is_suffix(s[1]):
        return s[1] + s[0] + (s[2:] if len(s) > 2 else "")
    if is_suffix(s[0]):
        return s[1:]
    return s