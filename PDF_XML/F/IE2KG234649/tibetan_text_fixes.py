#!/usr/bin/env python3
"""
Tibetan Text Fixes Module

This module provides functions to fix common issues in Tibetan text that occur
during PDF/RTF extraction and Dedris-related conversion.
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


def fix_mixed_dedris_patterns(text: str) -> str:
    """
    Fix remaining mixed Dedris patterns that weren't converted during stream processing.

    Handles cases where ASCII Dedris stand-ins and Tibetan Unicode were in separate
    text streams and thus not detected as mixed content during conversion.

    Maps ASCII ``(`` / ``)`` to Tibetan ཡ / འ in these repairs, along with other stand-ins.
    """
    consonant_before_vowel = {
        '.': 'ད',
        '0': 'ས',
        '{': 'ཆ',
        '\\': 'ས',
        '/': 'ཤ',
        '(': 'ཡ',
        ')': 'འ',
        '}': 'ས',
        ',': 'ཐ',
    }

    syllable_before_consonant = {
        '.': 'དུ',
        '0': 'སུ',
        '{': 'ཆུ',
        '\\': 'སུ',
        '/': 'ཤུ',
        '(': 'ཡུ',
        ')': 'འུ',
        '}': 'སུ',
        ',': 'ཐུ',
    }

    tibetan_vowels_literal = 'ཱིེོུཾཿ'
    vowel_pattern = '[' + tibetan_vowels_literal + '\u0F71-\u0F84]'

    tibetan_consonants = 'ཀཁགངཅཆཇཉཏཐདནཔཕབམཙཚཛཝཞཟའཡརལཤསཧཨ'
    tsheg = '་'
    shad = '།'

    result = text

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = escaped_char + '(' + vowel_pattern + ')'
        result = re.sub(pattern, tibetan_consonant + r'\1', result)

    for ascii_char, tibetan_syllable in syllable_before_consonant.items():
        escaped_char = re.escape(ascii_char)
        pattern = (
            '([' + tibetan_consonants + '])'
            + escaped_char
            + '([' + tibetan_consonants + tsheg + '])'
        )
        result = re.sub(pattern, r'\1' + tibetan_syllable + r'\2', result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = escaped_char + '([' + tibetan_consonants + '])'
        result = re.sub(pattern, tibetan_consonant + r'\1', result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = escaped_char + tsheg
        result = re.sub(pattern, tibetan_consonant + tsheg, result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = (
            '([' + tibetan_consonants + tibetan_vowels_literal + '])'
            + escaped_char
            + '([' + shad + '])'
        )
        result = re.sub(pattern, r'\1' + tibetan_consonant + r'\2', result)

    result = re.sub(r'\.་', 'ད་', result)

    tibetan_range = '\u0F00-\u0FFF'
    hyphen_pattern = '([' + tibetan_range + '])-([' + tibetan_range + '])'

    result = re.sub(hyphen_pattern, r'\1' + tsheg + r'\2', result)
    result = re.sub(hyphen_pattern, r'\1' + tsheg + r'\2', result)

    result = re.sub(r'([' + tibetan_range + '])-(<(?:/hi|lb))', r'\1་\2', result)
    result = re.sub(r'(>)-([' + tibetan_range + '])', r'\1་\2', result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        result = re.sub(
            r'([' + tibetan_consonants + tibetan_vowels_literal + '])'
            + escaped_char
            + r'(<(?:\/hi|lb|,))',
            r'\1' + tibetan_consonant + r'\2',
            result,
        )

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        result = re.sub(
            r'([' + tibetan_consonants + tibetan_vowels_literal + '])' + escaped_char + r',',
            r'\1' + tibetan_consonant + ',',
            result,
        )

    result = re.sub(r'([' + tibetan_range + ']),', r'\1།', result)
    result = re.sub(r'([' + tibetan_range + ']),(<)', r'\1།\2', result)

    return result

