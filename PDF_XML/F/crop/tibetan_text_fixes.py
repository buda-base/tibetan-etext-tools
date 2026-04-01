#!/usr/bin/env python3
"""
Tibetan Text Fixes Module

This module provides functions to fix common issues in Tibetan text that occur
during PDF to TEI XML conversion: flying vowels across line/page breaks, and
<hi> tags that split Tibetan syllables mid-character.
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

# Separator that can appear between a base consonant and its vowel/subscript
# in the final TEI: newlines, <lb/>, <pb/>, whitespace, any XML tags.
_TEI_BREAK = r'(?:\s|<lb/>|<pb/>|<[^>]*>)*'


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


# ── TEI-level flying-vowel fix ────────────────────────────────────────
# After TEI markup is generated, vowels/subscripts can be orphaned at
# <lb/> starts because <pb/>, <lb/>, and <hi> tags intervene between a
# base consonant and its combining mark.  This pass operates on the
# final TEI body.
#
# Only the safe case is handled: a consonant or subscript directly
# precedes the break (no tsheg between them).  When a tsheg precedes
# the break the vowel may belong to a different (missing) consonant,
# so those are left untouched.

_TEI_BREAK_SEQ = r'(?:\s|<[^>]*>)*'

_FLYING_AFTER_CONSONANT = re.compile(
    r'(' + TIBETAN_CONSONANTS + r'|' + TIBETAN_SUBSCRIPTS + r')'
    r'(' + _TEI_BREAK_SEQ + r'<lb/>)'
    r'(' + TIBETAN_VOWELS + r'|' + TIBETAN_SUBSCRIPTS + r')'
)


def fix_tei_flying_vowels(text: str) -> str:
    """
    Re-attach orphaned vowels/subscripts that start a <lb/> line.

    Only fires when a base consonant or subscript directly precedes
    the break sequence (whitespace, <pb/>, <hi> tags, etc.).
    Loops until stable to handle consecutive combining marks.
    """
    if not text:
        return text
    prev = None
    s = text
    while s != prev:
        prev = s
        s = _FLYING_AFTER_CONSONANT.sub(r'\1\3\2', s)
    return s


# ── <hi> tag syllable-split fix ───────────────────────────────────────
# Font-size spans from the PDF sometimes cut mid-syllable.  These
# patterns move stray combining characters and syllable remainders
# inside/outside the <hi> tag so the syllable stays intact.

# </hi> splits a combining mark (vowel/subscript) from its base.
# Captures the full syllable remainder: combiners + consonants up to
# the next tsheg (inclusive), so ཤ</hi>ིང་ → ཤིང་</hi>.
_HI_CLOSE_SPLITS_COMBINING = re.compile(
    r'([\u0f40-\u0f6c\u0f90-\u0fbc])'
    r'(</hi>)'
    r'([\u0f71-\u0f84\u0f90-\u0fbc]'
    r'[\u0f40-\u0f6c\u0f71-\u0f84\u0f90-\u0fbc]*'
    r'\u0f0b?)'
)

# </hi> orphans a tsheg: གིས</hi>་ → གིས་</hi>
_HI_CLOSE_SPLITS_TSHEG = re.compile(
    r'([\u0f40-\u0fbc])(</hi>)(\u0f0b)'
)

# <hi> opening splits a base consonant from its vowel:
# པ<hi ...>ོ → པོ<hi ...>
_HI_OPEN_SPLITS_VOWEL = re.compile(
    r'([\u0f40-\u0f6c])(<hi[^>]*>)([\u0f71-\u0f84\u0f90-\u0fbc]+)'
)


def fix_hi_tag_syllable_splits(text: str) -> str:
    """
    Repair <hi> boundaries that split a Tibetan syllable.

    Closing-tag cases:
        མཁས་ཤ</hi>ིང་  →  མཁས་ཤིང་</hi>
        ས</hi>ོགས་       →  སོགས་</hi>
        གིས</hi>་        →  གིས་</hi>

    Opening-tag case:
        པ<hi ...>ོ་</hi> →  པོ་<hi ...></hi>  (empty <hi> cleaned up)
    """
    if not text:
        return text
    s = _HI_CLOSE_SPLITS_COMBINING.sub(r'\1\3\2', text)
    s = _HI_CLOSE_SPLITS_TSHEG.sub(r'\1\3\2', s)
    s = _HI_OPEN_SPLITS_VOWEL.sub(r'\1\3\2', s)
    s = re.sub(r'<hi[^>]*></hi>', '', s)
    return s


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


