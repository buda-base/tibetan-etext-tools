#!/usr/bin/env python3
"""
Tibetan Text Fixes Module

This module provides functions to fix common issues in Tibetan text that occur
during RTF to Unicode conversion.
"""

import re

# Tibetan character ranges
TIBETAN_VOWELS = r'[\u0f71-\u0f84]'
TIBETAN_CONSONANTS = r'[\u0f40-\u0f6c]'
TIBETAN_SUBSCRIPTS = r'[\u0f90-\u0fbc]'
TIBETAN_TSEG = '\u0f0b'
TIBETAN_SHED = '\u0f0d'
TIBETAN_SHEDS = r'[\u0f0d-\u0f11]'
XML_TAGS_PATTERN = r'(?:<[^>]*>)*'


def fix_flying_vowels(text: str) -> str:
    """Fix flying vowels - vowels at start of line that should join previous consonant."""
    if not text:
        return text
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_VOWELS})'
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_subscripts(text: str) -> str:
    """Fix flying subscripts - subscript consonants at start of line that should join previous."""
    if not text:
        return text
    pattern = rf'({TIBETAN_CONSONANTS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_SUBSCRIPTS})'
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_tseg(text: str) -> str:
    """Fix flying tseg - tseg at start of line that should join previous text."""
    if not text:
        return text
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_TSEG})'
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_vowels_and_linebreaks(text: str) -> str:
    """Fix all flying vowel and line break issues in Tibetan text."""
    if not text:
        return text
    result = fix_flying_vowels(text)
    result = fix_flying_subscripts(result)
    result = fix_flying_tseg(result)
    return result


def fix_hi_tag_spacing(text: str) -> str:
    """Fix spacing around <hi> tags based on Tibetan punctuation rules."""
    if not text:
        return text
    text = re.sub(rf'({TIBETAN_SHED})(<hi[^>]*>)', r'\1 \2', text)
    text = re.sub(rf'({TIBETAN_SHED})(</hi>)([^\s])', r'\1\2 \3', text)
    return text


def fix_toc_leader_dots(text: str) -> str:
    """
    Fix TOC leader dots - repeated DA (ད) characters used as dots in table of contents.
    
    In Dedris encoding, the 'd' character maps to DA (ད), but when used as
    leader dots in TOC entries (to connect title to page number), they should
    be tseg (་) characters instead.
    
    This converts 3+ consecutive ད characters to ་ characters.
    """
    if not text:
        return text
    # Replace 3 or more consecutive ད with the same number of ་
    pattern = r'ད{3,}'
    def replace_with_tseg(match):
        return TIBETAN_TSEG * len(match.group())
    return re.sub(pattern, replace_with_tseg, text)


def is_tibetan_char(char: str) -> bool:
    """Check if a character is in the Tibetan Unicode block."""
    if len(char) != 1:
        return False
    code = ord(char)
    return 0x0F00 <= code <= 0x0FFF


def count_tibetan_chars(text: str) -> int:
    """Count the number of Tibetan characters in a string."""
    return sum(1 for c in text if is_tibetan_char(c))


# Latin-1 / CP1252 mojibake from bad PDF ToUnicode on TCRC-style fonts (not (cid:N) path).
_PDF_LATIN_MOJIBAKE_PATTERN = re.compile(
    "|".join(re.escape(k) for k in ("Ç", "Ý", "Æ"))
)
_PDF_LATIN_MOJIBAKE_MAP = {
    "Ç": "བ",
    "Ý": "ན",
    "Æ": "བྲ",
}


def fix_pdf_latin_mojibake(text: str) -> str:
    """
    Replace known garbage Latin letters that stand in for Tibetan glyphs.

    Map: Ç→བ, Ý→ན, Æ→བྲ.
    """
    if not text:
        return text

    def _repl(m: re.Match) -> str:
        return _PDF_LATIN_MOJIBAKE_MAP[m.group(0)]

    return _PDF_LATIN_MOJIBAKE_PATTERN.sub(_repl, text)


# After <pb/>, drop a line that is only one or more <lb/> + ASCII page number.
# Handles both convert_markup_to_tei output (<pb/>\n<lb/>1) and post_process_body,
# which inserts extra <lb/> after newlines (<pb/>\n<lb/><lb/>1).
_PB_STANDALONE_PAGE_NUM = re.compile(
    r"(<pb/>)\s*\n(?:\s*<lb/>)+\s*\d+\s*(?=\n|$)",
    re.MULTILINE,
)


def strip_pb_standalone_page_number_line(text: str) -> str:
    """
    Remove printed page numbers that appear on their own line right after <pb/>.

    Examples removed:
        <pb/>\\n<lb/>1
        <pb/>\\n<lb/><lb/>2   (after post_process_body newline expansion)
    """
    if not text:
        return text
    prev = None
    s = text
    while prev != s:
        prev = s
        s = _PB_STANDALONE_PAGE_NUM.sub(r"\1", s)
    return s


def dedupe_consecutive_lines(text: str) -> str:
    """
    Collapse runs of identical consecutive lines (e.g. repeated PDF headers extracted
    as separate <lb/> rows).
    """
    if not text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    prev: str | None = None
    for line in lines:
        if line == prev:
            continue
        out.append(line)
        prev = line
    return "\n".join(out)

