#!/usr/bin/env python3
"""
Tibetan Text Fixes Module

This module provides functions to fix common issues in Tibetan text that occur
during RTF to Unicode conversion, particularly:

1. Flying vowels - vowels that appear at the start of a line but should attach
   to the consonant at the end of the previous line
2. Flying subscripts - subscript consonants that should attach to previous consonant
3. Mid-word line breaks - words incorrectly split across lines
4. Spacing around XML tags - proper spacing after Tibetan punctuation

These issues typically arise from the original RTF formatting where line breaks
were inserted for display purposes but don't represent actual paragraph breaks.
"""

import re

# =============================================================================
# Tibetan Character Range Constants
# =============================================================================

# Tibetan vowel signs (combining marks that attach to consonants)
# U+0F71-U+0F84: a-chung, vowels i, u, e, o, reversed marks, etc.
TIBETAN_VOWELS = r'[\u0f71-\u0f84]'

# Tibetan base consonants (standalone letters)
# U+0F40-U+0F6C: ka through a
TIBETAN_CONSONANTS = r'[\u0f40-\u0f6c]'

# Tibetan subscript consonants (combining forms that go below base letters)
# U+0F90-U+0FBC: subjoined ka through subjoined fixed-form ra
TIBETAN_SUBSCRIPTS = r'[\u0f90-\u0fbc]'

# Tibetan punctuation
TIBETAN_TSEG = '\u0f0b'      # ་ - syllable separator (tsheg)
TIBETAN_SHED = '\u0f0d'      # ། - sentence/section marker (shad)
TIBETAN_SHEDS = r'[\u0f0d-\u0f11]'  # །༎༏༐ - all shad variants

# Pattern for optional XML tags (may appear between text due to font size changes)
XML_TAGS_PATTERN = r'(?:<[^>]*>)*'


# =============================================================================
# Flying Vowel and Line Break Fixes
# =============================================================================

def fix_flying_vowels(text: str) -> str:
    """
    Fix flying vowels - vowels at start of line that should join previous consonant.
    
    Example:
        "དང་པ\nོ་ནི།" -> "དང་པོ་ནི།"
        (vowel ོ joins previous པ)
    
    Also handles XML tags between text elements:
        "པ</hi>\n<hi>ོ" -> "པ</hi><hi>ོ"
    
    Args:
        text: Input text with potential flying vowels
        
    Returns:
        Text with flying vowels fixed
    """
    if not text:
        return text
    
    # Pattern: (consonant|subscript|vowel)(optional XML)(newlines)(optional XML)(vowel)
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_VOWELS})'
    
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_subscripts(text: str) -> str:
    """
    Fix flying subscripts - subscript consonants at start of line that should join previous.
    
    Example:
        "ག\nྱི་" -> "གྱི་"
        (subscript ྱ joins previous ག)
    
    Args:
        text: Input text with potential flying subscripts
        
    Returns:
        Text with flying subscripts fixed
    """
    if not text:
        return text
    
    # Pattern: (consonant)(optional XML)(newlines)(optional XML)(subscript)
    pattern = rf'({TIBETAN_CONSONANTS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_SUBSCRIPTS})'
    
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_mid_word_breaks(text: str) -> str:
    """
    Fix mid-word line breaks - consonants split across lines without proper boundary.
    
    Example:
        "བྱི\nན་" -> "བྱིན་"
        (consonant ན joins previous བྱི)
    
    Note: Line breaks after tseg (་) or shed (།) are PRESERVED as paragraph breaks.
    
    Args:
        text: Input text with potential mid-word breaks
        
    Returns:
        Text with mid-word breaks fixed
    """
    if not text:
        return text
    
    # Pattern: (consonant|subscript|vowel)(optional XML)(newlines)(optional XML)(consonant)
    # This only matches if the character before newline is NOT tseg or shed
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_CONSONANTS})'
    
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_tseg(text: str) -> str:
    """
    Fix flying tseg - tseg (་) at start of line that should join previous text.
    
    Example:
        "འབྱང\n་ཞིང" -> "འབྱང་ཞིང"
        (tseg ་ joins previous འབྱང)
    
    This handles cases where the syllable separator got split to a new line
    during RTF formatting.
    
    Args:
        text: Input text with potential flying tseg
        
    Returns:
        Text with flying tseg fixed
    """
    if not text:
        return text
    
    # Pattern: (consonant|subscript|vowel)(optional XML)(newlines)(optional XML)(tseg)
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_TSEG})'
    
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_vowels_and_linebreaks(text: str) -> str:
    """
    Fix all flying vowel and line break issues in Tibetan text.
    
    This is the main function that applies all fixes in the correct order:
    1. Flying vowels (vowel at line start joins previous consonant)
    2. Flying subscripts (subscript at line start joins previous consonant)
    3. Mid-word breaks (consonant joins previous consonant/vowel/subscript)
    4. Flying tseg (tseg at line start joins previous text)
    
    PARAGRAPH BREAKS ARE PRESERVED when they follow:
    - Tibetan sheds (།) - sentence/section markers
    - Tibetan tseg (་) - syllable separators (word boundaries)
    
    Examples:
        "དང་པ\nོ་ནི།" -> "དང་པོ་ནི།"  (flying vowel fixed)
        "ག\nྱི་" -> "གྱི་"  (flying subscript fixed)
        "བྱི\nན་" -> "བྱིན་"  (mid-word break fixed)
        "འབྱང\n་ཞིང" -> "འབྱང་ཞིང"  (flying tseg fixed)
        "བཤད། །\nསྐྱབས" -> "བཤད། །\nསྐྱབས"  (paragraph PRESERVED)
        "འབྱང་\nཞིང་" -> "འབྱང་\nཞིང་"  (break after tseg PRESERVED)
    
    Args:
        text: Input text with potential issues
        
    Returns:
        Text with all issues fixed
    """
    if not text:
        return text
    
    # Apply fixes in order - ONLY for combining characters that MUST attach
    result = fix_flying_vowels(text)
    result = fix_flying_subscripts(result)
    # REMOVED: fix_mid_word_breaks - was removing legitimate paragraph breaks from original RTF
    result = fix_flying_tseg(result)
    
    return result


# =============================================================================
# XML Tag Merging
# =============================================================================

def merge_consecutive_hi_tags(text: str) -> str:
    """
    Merge consecutive <hi rend="X">...</hi><hi rend="X">...</hi> into a single tag.
    Reduces tag soup when font-size runs are emitted per character.
    """
    if not text:
        return text
    # Merge two adjacent same-rend hi tags: <hi rend="R">c1</hi><hi rend="R">c2</hi> -> <hi rend="R">c1c2</hi>
    prev = None
    while prev != text:
        prev = text
        text = re.sub(
            r'<hi rend="([^"]+)">(.*?)</hi>\s*<hi rend="\1">(.*?)</hi>',
            r'<hi rend="\1">\2\3</hi>',
            text,
            count=1,
            flags=re.DOTALL
        )
    return text


# =============================================================================
# XML Tag Spacing Fixes
# =============================================================================

def ensure_space_after_shad(text: str) -> str:
    """
    Ensure a space after each shad ( ། U+0F0D–U+0F11 ) when followed by Tibetan or tag.
    Fixes text that has no space after ། (e.g. "ལི།བོད་" -> "ལི། བོད་") so phrase
    boundaries are readable. Does not add space when already followed by space or newline.
    """
    if not text:
        return text
    # After shad: if next char is Tibetan or < (tag), and there's no space/newline between, insert space
    return re.sub(
        rf'({TIBETAN_SHEDS})([^\s<])',
        r'\1 \2',
        text
    )


def fix_hi_tag_spacing(text: str) -> str:
    """
    Fix spacing around <hi> tags based on Tibetan punctuation rules.
    
    Rules:
    1. Add space BEFORE <hi> if preceded by shed (།) without space
       Example: །<hi... → ། <hi...
    
    2. Add space AFTER </hi> if:
       - Content inside <hi> ends with shed (།)
       - AND next character is not a space
       Example: །</hi>རྒྱ → །</hi> རྒྱ
    
    Args:
        text: Input text with <hi> tags
        
    Returns:
        Text with proper spacing around tags
    """
    if not text:
        return text
    
    # Rule 1: Add space before <hi> if preceded by shed without space
    text = re.sub(rf'({TIBETAN_SHED})(<hi[^>]*>)', r'\1 \2', text)
    
    # Rule 2: Add space after </hi> if content ends with shed and next char is not space
    text = re.sub(rf'({TIBETAN_SHED})(</hi>)([^\s])', r'\1\2 \3', text)
    
    return text


# =============================================================================
# Utility Functions
# =============================================================================

# Horizontal space chars (exclude newline): space, tab, no-break space, and all Unicode
# horizontal space categories so RTF/Word spacing is fully normalized.
_HORIZONTAL_SPACES = (
    r'[ \t'  # space, tab
    r'\u00A0'   # NO-BREAK SPACE
    r'\u1680'   # OGHAM SPACE
    r'\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u200B'  # en/em/figure etc.
    r'\u202F\u205F\u3000'  # narrow no-break, medium mathematical, ideographic
    r'\uFEFF'   # BOM / zero-width no-break
    r'\u005F' # underscore
    r']+'
    
)
_TIBETAN = r'[\u0F00-\u0FFF]'
# Tibetan syllable-boundary punctuation: after these we KEEP space (phrase/syllable break).
# Tsheg U+0F0B ( ་ ), shad variants U+0F0D–U+0F11 ( ། ༎ etc. )
_TIBETAN_TSHEG_SHAD = r'[\u0F0B\u0F0D-\u0F11]'
# Tibetan char that is NOT tsheg/shad: only remove space when this is the char BEFORE the space
# (so we don't remove space after ། or ་ — those are intentional phrase boundaries).
_TIBETAN_NOT_BOUNDARY = r'[\u0F00-\u0F0A\u0F12-\u0FFF]'

def remove_spaces_between_tibetan_chars(text: str) -> str:
    """
    Remove horizontal spaces only when they sit inside a syllable (between consonant/vowel
    stack parts). Preserve spaces after tsheg ( ་ ) and shad ( ། ) — those are phrase/syllable
    boundaries and should keep the space so text reads "ལི། བོད་" not "ལི།བོད་".
    RTF often has one run per character with spaces; this rejoins syllable-internal runs only.
    Example: "ར ྒ ྱ་ག ར་" -> "རྒྱ་ག ར་" (space after ་ kept if present); "ལི། བོད་" unchanged.
    Newlines are preserved (not collapsed).
    """
    if not text:
        return text
    prev = None
    while prev != text:
        prev = text
        # Only remove space when first Tibetan is NOT tsheg/shad (syllable-internal).
        def _remove_middle_spaces(m):
            middle = m.group(2)
            parts = re.split(r'(<[^>]*>)', middle)
            cleaned = []
            for part in parts:
                if part.startswith('<'):
                    cleaned.append(part)
                else:
                    cleaned.append(re.sub(_HORIZONTAL_SPACES, '', part))
            return m.group(1) + ''.join(cleaned) + m.group(3)
        # First char must be Tibetan but NOT tsheg/shad so we don't remove space after ། or ་
        text = re.sub(
            r'(' + _TIBETAN_NOT_BOUNDARY + r')((?:' + _HORIZONTAL_SPACES + r'|<[^>]*>)+)(' + _TIBETAN + r')',
            _remove_middle_spaces,
            text
        )
    return text


def is_tibetan_char(char: str) -> bool:
    """Check if a character is in the Tibetan Unicode block (U+0F00-U+0FFF)."""
    if len(char) != 1:
        return False
    code = ord(char)
    return 0x0F00 <= code <= 0x0FFF


def count_tibetan_chars(text: str) -> int:
    """Count the number of Tibetan characters in a string."""
    return sum(1 for c in text if is_tibetan_char(c))


def is_tibetan_punctuation(char: str) -> bool:
    """Check if a character is Tibetan punctuation (tseg or shed variants)."""
    if len(char) != 1:
        return False
    code = ord(char)
    # U+0F0B (tseg) and U+0F0D-U+0F11 (shad variants)
    return code == 0x0F0B or (0x0F0D <= code <= 0x0F11)


# =============================================================================
# Combined Normalization
# =============================================================================

def normalize_tibetan_text(text: str, fix_linebreaks: bool = True, 
                           fix_tag_spacing: bool = True) -> str:
    """
    Apply all Tibetan text normalization fixes.
    
    This is a convenience function that applies all fixes in one call.
    
    Args:
        text: Input text to normalize
        fix_linebreaks: Whether to fix flying vowels and line breaks
        fix_tag_spacing: Whether to fix spacing around <hi> tags
        
    Returns:
        Normalized text
    """
    if not text:
        return text
    
    result = text
    
    if fix_linebreaks:
        result = fix_flying_vowels_and_linebreaks(result)
    
    if fix_tag_spacing:
        result = fix_hi_tag_spacing(result)
    
    return result


# =============================================================================
# Dedris corruption substitution (table-based)
# =============================================================================
# Unambiguous replacements for common Dedris→Unicode corruption patterns.
# Apply in body text only (not inside XML tags).
# Order: longest strings first so specific phrases are fixed before generic ones.
CORRUPTION_SUBSTITUTIONS = [
    # Comma (U+002C) where ད (U+0F51) should be
    (',ོ', 'དོ'),
    (',གས', 'དགས'),
    (',ི', 'དི'),
    (',ན', 'དན'),
    (',ོད', 'དོད'),
    (',ོན', 'དོན'),
    (',ིག', 'དིག'),
    (',ག་', 'དག་'),
    (',ར་', 'དར་'),
    # Tsheg + full stop + tsheg → tsheg + ན + tsheg
    ('་.་', '་ན་'),
    ('མ.ད་', 'མཚད་'),
    # Digit 0 as ཏ (ta): 0་ → ཏུ་ in context
    ('གཅིག་0་ཡིན་པར་', 'གཅིག་ཏུ་ཡིན་པར་'),
    ('གྲོལ་བ་གཅིག་0་', 'གྲོལ་བ་གཅིག་ཏུ་'),
    ('རང་གཅིག་0-', 'རང་གཅིག་ཏུ་-'),
    ('གཅིག་0་', 'གཅིག་ཏུ་'),
    # .0 (dot-zero) as དེ
    ('.0ེ་དངོས་', 'དེ་དངོས་'),
    ('.0ེ་ཡང་', 'དེ་ཡང་'),
    ('.0ེར་', 'དེར་'),
    ('.0ེ་', 'དེ་'),
    # འ. (འ + dot) → འད for common syllables
    ('འ.ག་པའི་', 'འདག་པའི་'),
    ('འ.ག་སྟེ', 'འདག་སྟེ'),
    ('འ.ག་པ', 'འདག་པ'),
    ('འ.ས་པ', 'འདས་པ'),
    ('འ.ས་', 'འདས་'),
    ('འ.ག་', 'འདག་'),
    # .ེ compound phrases (dot as དེ)
    ('.ེའི་ཕྱིར་', 'དེའི་ཕྱིར་'),
    ('.ེ་བཞིན་ཉིད་', 'དེ་བཞིན་ཉིད་'),
    ('.ེ་ཕྱིར་', 'དེ་ཕྱིར་'),
    ('.ེ་ཡང་', 'དེ་ཡང་'),
    ('.ེ་ལྟར་', 'དེ་ལྟར་'),
    ('.ེ་ཉིད་', 'དེ་ཉིད་'),
    ('.ེ་དངོས་', 'དེ་དངོས་'),
    ('.ེ་ནི་', 'དེ་ནི་'),
    ('.ེ་བཞིན་', 'དེ་བཞིན་'),
    ('.ེ་དོན་', 'དེ་དོན་'),
    ('.ེ་ཚེ་', 'དེ་ཚེ་'),
    ('.ེ་དང་', 'དེ་དང་'),
    ('.ེའི་', 'དེའི་'),
    ('.ེ་', 'དེ་'),
    ('.ེ', 'དེ'),
    # .ོན (dot as དོན)
    ('.ོན་གྱི་', 'དོན་གྱི་'),
    ('.ོན་རང་', 'དོན་རང་'),
    ('.ོན་', 'དོན་'),
    # Known syllables: Tibetan + dot → Tibetan + ད
    ('མེ.', 'མེད'),
    ('ཆོ.', 'ཆོད'),
    # Misc dot-as-dedris
    ('.བུགས་', 'དབུགས་'),
    ('.མུ', 'དམུ'),
    ('.ེ་ཞལ་', 'དེ་ཞལ་'),
    ('.བུལ་', 'དབུལ་'),
    ('.ར་ཁྲོད་', 'དར་ཁྲོད་'),
    ('.ས་', 'དས་'),
]
# Curly braces in Tibetan context: { often = ཀྱི་ or གི་; } often = འི་ or similar
# Apply only when surrounded by Tibetan (conservative)
CORRUPTION_CURLY_OPEN = re.compile(r'(\s|[\u0F00-\u0FFF]){(\s|[\u0F00-\u0FFF])')
CORRUPTION_CURLY_CLOSE = re.compile(r'(\s|[\u0F00-\u0FFF])}(\s|[\u0F00-\u0FFF])')

# Dot as ད fallback: . + Tibetan vowel → ད + vowel (apply after literal substitutions)
CORRUPTION_DOT_VOWEL = re.compile(r'\.([\u0F71-\u0F84])')  # U+0F71-U+0F84: vowels ེ ོ ི ུ etc.


def fix_dedris_corruption(text: str) -> str:
    """
    Apply table-based corruption substitutions to body text.
    Replaces only in text; does not alter XML tag content.
    """
    if not text:
        return text
    result = text
    for old, new in CORRUPTION_SUBSTITUTIONS:
        result = result.replace(old, new)
    # Curly braces: { → ཀྱི་ (common), } → འི་ (common) when between Tibetan/space
    result = CORRUPTION_CURLY_OPEN.sub(r'\1ཀྱི་\2', result)
    result = CORRUPTION_CURLY_CLOSE.sub(r"\1འི་\2", result)
    # Fallback: . + Tibetan vowel → ད + vowel (catches any remaining .ེ .ོ etc.)
    result = CORRUPTION_DOT_VOWEL.sub(r'ད\1', result)
    return result


def fix_dedris_corruption_with_count(text: str) -> tuple:
    """
    Apply table-based corruption substitutions; return (fixed_text, replacement_count).
    """
    if not text:
        return text, 0
    count = 0
    result = text
    for old, new in CORRUPTION_SUBSTITUTIONS:
        n = result.count(old)
        if n:
            result = result.replace(old, new)
            count += n
    result, n_open = CORRUPTION_CURLY_OPEN.subn(r'\1ཀྱི་\2', result)
    count += n_open
    result, n_close = CORRUPTION_CURLY_CLOSE.subn(r"\1འི་\2", result)
    count += n_close
    result, n_dot_vowel = CORRUPTION_DOT_VOWEL.subn(r'ད\1', result)
    count += n_dot_vowel
    return result, count
