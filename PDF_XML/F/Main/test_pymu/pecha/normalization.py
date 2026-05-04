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

# Consecutive duplicate Tibetan vowel signs (PDF / layered extract artefacts).
# U+0F71–U+0F7D: dependent vowels (gigu, naro, ེ, ོ, …); U+0F80–U+0F81: vocalic marks.
# Subjoined consonants (U+0F8D–) are excluded so stacks like ྲྲ stay intact.
_COLLAPSE_DUP_TIB_VOWEL_MARK_RE = re.compile(r"([\u0f71-\u0f7d\u0f80-\u0f81])\1+")


def collapse_duplicate_tibetan_vowel_marks(text: str) -> str:
    """
    Collapse runs of two or more identical Tibetan vowel signs to one character.

    Overlapping InDesign text layers or mark+cluster cmap pairs often emit the
    same mark twice or thrice (e.g. གཞིི, དཔེེེ, མཚོོན).  Only *consecutive*
    identical codepoints in the ranges above are merged.
    """
    if not text:
        return text
    return _COLLAPSE_DUP_TIB_VOWEL_MARK_RE.sub(r"\1", text)


def fix_pdf_glyph_to_unicode_artifacts(text: str) -> str:
    """
    Repair common Monlam / legacy PDF ToUnicode mistakes (Latin PUA fallbacks).

    Observed in IE3KG647 et al.:
      - U+0140 (ŀ) used for Tibetan vowel sign o (U+0F7C)
      - U+0132 (Ĳ) used inside ཚིག / ཚེས / ཚིགས / མཛེས / …

    Additional artifacts from WinAnsiEncoding MonlamUniOuChan2 font and
    MuPDF GID-as-Unicode fallback (Identity-H, no matching ToUnicode entry):
      - U+013D (Ľ) produced by GID 0x013D → MuPDF uses GID as codepoint;
        glyph is tib.Naro.Anusvara (ོ + ཾ ligature on ཨ → OM context).
        Always appears as ཨĽ → correct to ཨོཾ (OM = ༀ in NFD form).
      - U+2020 (†) and U+2021 (‡) from WinAnsi byte 0x86/0x87 on the dot-leader
        glyph (uni0086); visually a period in Monlam font.

    TibetanMachine / Dedris PDF colophon boilerplate:
      - The Chinese Buddhist publisher 佛陀教育基金會 uses a fixed Tibetan notice
        encoded in TibetanMachine Type1 fonts whose glyph ordering is non-standard.
        Neither pytiblegenc nor any TibetanMachineWeb variant table can decode it
        algorithmically without the original .ttf file. The decode_tibetan_machine()
        function in dedris_resolver.py applies TibetanMachineWeb (best available
        approximation) and produces a consistent wrong result that is detectable
        here and replaced with the correct Unicode text.
    """
    if not text:
        return text
    s = text

    # ── 佛陀教育基金會 colophon notice ──────────────────────────────────────────
    # TibetanMachine font with non-standard glyph ordering produces this fixed
    # wrong decode. Replace with the correct Tibetan text (manually verified).
    # The raw PDF encoding is always: K$- .0J- :.A- (R?-.A/- .- :2=- o- =?,␣5S%- 2+<- 3A- (R$- 0- .$R%?- :)$?- 8,
    # After decode_tibetan_machine + normalize_spaces it always becomes this exact string:
    s = s.replace(
        "རྟང པབརྙ རཔཋ ཉལྐཨ པཋ ཕ པ རཙས ུ སཨནཝལྒཅ ཙདཤ ཚཋ ཉལྐང བ པངལྐཅཨ རཏངཨ འན",
        "ཕྱག་དཔེ་འདི་ཆོས་སྦྱིན་དུ་འབུལ་རྒྱུ་ལས། ཚོང་བསྒྱུར་མི་ཆོག་པ་དགོངས་འཇགས་ཞུ།",
    )
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

    Tibetan-specific rules:
      - Remove space after tsheg (U+0F0B, U+0F0C, U+0FD2) if followed by
        initial letter (U+0F40-U+0F6C) or shad (U+0F0D-U+0F11)
      - Remove space between final letter (U+0F40-U+0FBC) and tsheg
    """
    if not text:
        return ""

    s = text

    # 1) Collapse multiple newlines
    s = re.sub(r"\n{2,}", "\n", s)

    # 2) Remove spaces next to newlines
    s = re.sub(r"[ ]+\n", "\n", s)
    s = re.sub(r"\n[ ]+", "\n", s)

    # 3) Collapse space runs
    if collapse_internal_spaces:
        s = re.sub(r" {2,}", " ", s)

    # 4) Tibetan-specific space normalization
    if tibetan_specific:
        # Remove space after tsheg if followed by initial letter or shad
        s = re.sub(r"([\u0f0b\u0f0c\u0fd2]) +([\u0f40-\u0f6c\u0f0d-\u0f11])", r"\1\2", s)
        # Remove space between final letter and tsheg
        s = re.sub(r"([\u0f40-\u0fbc]) +([\u0f0b\u0f0c\u0fd2])", r"\1\2", s)

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
      2. Convert all line breaks to '\n'.
      3. Remove zero-width / invisible characters (incl. all BOMs).
      4. Map Unicode spaces and tabs to plain ASCII space.
      5. Optionally remove control characters (except newline).
      6. Normalize spaces (including Tibetan-specific rules).
      7. Remove stray Latin 'm' (Monlam extract artefacts).
      8. Remove Wingdings/Wingdings2 PUA symbols (U+F020–U+F0FF).
      9. Apply Tibetan Unicode normalization.
      10. Collapse consecutive duplicate Tibetan vowel marks (PDF layer artefacts).

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
    # 6c) Restore visible gaps after shad / before Tibetan digits (dates, headings)
    # s = normalize_tibetan_boundary_spaces(s)

    # 8) Wingdings/Wingdings2 bullets and dingbats (PUA safety net)
    s = remove_wingdings_private_use(s)

    # 9) Tibetan Unicode normalization
    s = normalize_unicode_tib(s)
    # 10) Duplicate gigu / naro / ེ / ོ from overlapping PDF text layers
    s = collapse_duplicate_tibetan_vowel_marks(s)
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
    + [Cats.Base]
    * 20  # 0F20-0F33, numbers can be followed by 0f18, 0f19 or exceptionally by vowels
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


def is_vowel(char):
    if re.search(r"[\u0f71-\u0f84]", char):
        return True
    return False


def is_suffix(char):
    if re.search(r"[\u0f90-\u0fbc]", char):
        return True
    return False


def normalize_invalid_start_string(s):
    if len(s) < 2:
        return s
    if is_vowel(s[0]) and not is_vowel(s[1]) and not is_suffix(s[1]):
        return s[1] + s[0] + (s[2:] if len(s) > 2 else "")
    if is_suffix(s[0]):
        return s[1:]
    return s