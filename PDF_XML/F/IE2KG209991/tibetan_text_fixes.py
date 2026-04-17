#!/usr/bin/env python3
"""
Tibetan Text Fixes Module

This module provides functions to fix common issues in Tibetan text that occur
during PDF to unicode conversion.
"""

import re

# Tibetan character ranges
TIBETAN_VOWELS = r'[\u0f71-\u0f84]'
TIBETAN_CONSONANTS = r'[\u0f40-\u0f6c]'
TIBETAN_SUBSCRIPTS = r'[\u0f90-\u0fbc]'
TIBETAN_TSEG = '\u0f0b'
TIBETAN_SHED = '\u0f0d'
TIBETAN_SHEDS = r'[\u0f0d-\u0f11]'
TIBETAN_YA = '\u0f61'  # often wrong decode for ASCII '(' in Qomolangma PDFs
TIBETAN_ACHUNG = '\u0f60'  # often wrong decode for ASCII ')' in Qomolangma PDFs
XML_TAGS_PATTERN = r'(?:<[^>]*>)*'

# Qomolangma ToUnicode can map '(' (CID 40) to U+0F61 ཡ. Replace only when ཡ is
# not a normal syllable: no following tsek, no vowels/subscripts on this letter,
# and next char is འ (e.g. (འཆོས…)), tibetan punctuation, non-Tibetan, or EOS—
# not another stacked consonant like བ in ཡབ.
_MISTAKEN_YA_OPEN_PAREN = re.compile(
    r'(?<![\u0F40-\u0F6C\u0F90-\u0FBC\u0F71-\u0F84])'
    + TIBETAN_YA
    + r'(?!\u0F0B)'
    + r'(?![\u0F71-\u0F84\u0F90-\u0FBC])'
    + r'(?=\u0F60|[\u0F0D-\u0F11]|[^\u0F00-\u0FFF]|$)'
)

# Qomolangma ToUnicode can map ')' (CID 41) to U+0F60 འ. Example: བའ → བ)).
# Require a main Tibetan consonant immediately before (so ་འདུལ་ / leading འ are untouched).
# Forbid tsek right after this འ, vowels (མའི), and following consonants/subscripts (འདུལ).
_MISTAKEN_ACHUNG_CLOSE_PAREN = re.compile(
    r'(?<=[\u0F40-\u0F6C])'
    + TIBETAN_ACHUNG
    + r'(?!\u0F0B)'
    + r'(?![\u0F71-\u0F84\u0F40-\u0F6C\u0F90-\u0FBC])'
)

# གླེགས vs གྲེགས (ླ U+0FB3 / ྲ U+0FB2) — Qomolangma extract often uses the wrong stack here
GLEG_BAM_STACK = r'ག[\u0FB2\u0FB3]ེགས'
# U+0F0B tsek is often present between གླེགས་ and བམ; allow omit for broken extract
GLEG_BAM_DANG_PO = GLEG_BAM_STACK + r'་?བམ་དང་པོ།'
GLEG_BAM_GNYIS_PA = GLEG_BAM_STACK + r'་?བམ་གཉིས་པ།'
GLEG_BAM_BZHI_PA = GLEG_BAM_STACK + r'་?བམ་བཞི་པ།'
_HY = r'[\u2212\-]'


def fix_phantom_volume_headers(text: str) -> str:
    """
    Drop a duplicate "volume 1" line before vol. 2/3/4 title blocks.
    Handles raw extract (<fs:N> plus newline) and TEI (<lb/> plus newline).
    Matches both གླེགས and གྲེགས (wrong subjoined letter in extract).
    """
    if not text:
        return text
    p_fs = r'(<fs:\d+>)'
    # post_process_body inserts \n<lb/> into text that already has <lb/> per line,
    # so lines often look like <lb/><lb/>ཡིག — match one or more <lb/> with space.
    p_lb = r'(?:<lb/>\s*)+'

    text = re.sub(
        p_fs + GLEG_BAM_DANG_PO + r'\r?\n'
        + p_fs + r'ཇ' + _HY + r'པ།\r?\n'
        + p_fs + r'2013\r?\n'
        + p_fs + GLEG_BAM_GNYIS_PA,
        r'\g<4>གླེགས་བམ་གཉིས་པ།\n\g<2>ཇ−པ།\n\g<3>2013',
        text,
    )
    text = re.sub(
        p_lb + GLEG_BAM_DANG_PO + r'\r?\n'
        + p_lb + r'ཇ' + _HY + r'པ།\r?\n'
        + p_lb + r'2013\r?\n'
        + p_lb + GLEG_BAM_GNYIS_PA,
        r'<lb/>གླེགས་བམ་གཉིས་པ།\n<lb/>ཇ−པ།\n<lb/>2013',
        text,
    )

    text = re.sub(
        p_fs + GLEG_BAM_DANG_PO + r'\r?\n'
        + p_fs + r'ཕ' + _HY + r'ཞ།\r?\n'
        + p_fs + r'2013\r?\n'
        + p_fs + r'གླེགས་བམ་གsམ་པ།',
        r'\g<4>གླེགས་བམ་གསུམ་པ།\n\g<2>ཕ−ཞ།\n\g<3>2013',
        text,
    )
    text = re.sub(
        p_lb + GLEG_BAM_DANG_PO + r'\r?\n'
        + p_lb + r'ཕ' + _HY + r'ཞ།\r?\n'
        + p_lb + r'2013\r?\n'
        + p_lb + r'གླེགས་བམ་གsམ་པ།',
        r'<lb/>གླེགས་བམ་གསུམ་པ།\n<lb/>ཕ−ཞ།\n<lb/>2013',
        text,
    )

    text = re.sub(
        p_fs + GLEG_BAM_DANG_PO + r'\r?\n'
        + p_fs + r'ཟ' + _HY + r'ཨ།\r?\n'
        + p_fs + r'2013\r?\n'
        + p_fs + GLEG_BAM_BZHI_PA,
        r'\g<4>གླེགས་བམ་བཞི་པ།\n\g<2>ཟ−ཨ།\n\g<3>2013',
        text,
    )
    text = re.sub(
        p_lb + GLEG_BAM_DANG_PO + r'\r?\n'
        + p_lb + r'ཟ' + _HY + r'ཨ།\r?\n'
        + p_lb + r'2013\r?\n'
        + p_lb + GLEG_BAM_BZHI_PA,
        r'<lb/>གླེགས་བམ་བཞི་པ།\n<lb/>ཟ−ཨ།\n<lb/>2013',
        text,
    )
    return text


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


def fix_qomolangma_ligatures(text: str) -> str:
    """
    DISABLED: The original function actively destroyed valid ligatures 
    like སྒོ, སྡེ, and དྲེ. We now handle Qomolangma artifacts safely 
    in `cleanup_qomolangma_artifacts` without destroying valid bases.
    """
    return text


def cleanup_qomolangma_artifacts(text: str) -> str:
    """
    Sweeps up rogue Latin characters, font collisions, and OCR artifacts
    that bypass the CID map.
    """
    if not text:
        return text

    # --- 0. '(' mis-decoded as ཡ (no tsek; safe syllable boundary only) ---
    text = _MISTAKEN_YA_OPEN_PAREN.sub('(', text)
    # --- 0b. ')' mis-decoded as འ after syllable-final consonant (not འདུལ་ / མའི) ---
    text = _MISTAKEN_ACHUNG_CLOSE_PAREN.sub(')', text)

    # --- 1. Sweep up rogue Latin characters ---
    text = text.replace("ŝ", "ི")
    text = re.sub(r'g([\u0F00-\u0FFF])', r'ག\1', text)
    text = re.sub(r'([\u0F00-\u0FFF])g', r'\1ག', text)
    text = re.sub(r'd([\u0F00-\u0FFF])', r'ད\1', text)
    text = re.sub(r'K([\u0F00-\u0FFF])', r'\1', text)
    text = re.sub(r'([\u0F00-\u0FFF])K', r'\1', text)
    
    # 0FA1 0F7A (ྡེ) anomalies
    text = text.replace("མྡེ", "མེ")
    text = text.replace("ཆྡེ", "ཆེ")
    text = text.replace("རྡེ", "རེ")
    
    # The font maps both ླེ and ྲེ to ྡེ depending on the base
    text = text.replace("གྡེགས", "གླེགས")
    text = text.replace("གེགས", "གླེགས") # Catch stripped version
    
    text = text.replace("འགྡེལ", "འགྲེལ")
    text = text.replace("འགེལ", "འགྲེལ") # Catch stripped version
    
    text = text.replace("དྡེ", "དྲེ") 
    
    # 0FB2 0F72 (ྲི) anomalies
    text = text.replace("འྲི", "འི")
    text = text.replace("ཡྲི", "ཡི")
    text = text.replace("པྲི", "པི")

    text = text.replace("གླེགས་བམ་གsམ་པ།", "གླེགས་བམ་གསུམ་པ།")

    # --- 4. Duplicate/phantom volume headers (see fix_phantom_volume_headers) ---
    text = fix_phantom_volume_headers(text)

    return text


  

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

