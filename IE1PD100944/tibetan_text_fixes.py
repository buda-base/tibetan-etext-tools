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
# XML Tag Spacing Fixes
# =============================================================================

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

