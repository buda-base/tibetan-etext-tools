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
    1. ASCII to Tibetan character fixes (. - 0 , -> Tibetan equivalents)
    2. Flying vowels (vowel at line start joins previous consonant)
    3. Flying subscripts (subscript at line start joins previous consonant)
    4. Mid-word breaks (consonant joins previous consonant/vowel/subscript)
    5. Flying tseg (tseg at line start joins previous text)
    
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
    
    # Apply fixes in order
    # First fix ASCII to Tibetan character mappings
    result = fix_ascii_to_tibetan(text)
    
    # Then fix combining characters that MUST attach
    result = fix_flying_vowels(result)
    result = fix_flying_subscripts(result)
    # REMOVED: fix_mid_word_breaks - was removing legitimate paragraph breaks from original RTF
    result = fix_flying_tseg(result)
    
    return result


# =============================================================================
# Question mark placeholder fixes (RTF \u replacement / conversion artifacts)
# =============================================================================

# Context-based replacements for ? that appears between Tibetan characters.
# These occur when RTF \uN replacement count was misparsed or Dedris conversion failed.
# Format: (before_pattern, after_pattern, replacement_char)
# before/after are regex patterns; the ? is in the middle.
# (before_regex, after_regex, replacement) - replace (before)?(after) with (before)(replacement)(after)
# Use replacement '' to remove ? when the following character is already correct (e.g. ག?ྱི་ -> གྱི་)
# Order matters: more specific patterns should come before broader ones.
_QUESTION_MARK_FIXES = [
    # ---- Remove ? (replacement '') when the correct char already follows ----
    # ག?ྱི་ -> གྱི་
    (r'[\u0F40-\u0F6C]', r'ྱི', ''),
    # ཀྱ?ི་, ས་ཀྱ?ི་
    (r'ཀྱ', r'ི[་]?', ''),
    (r'ྱ', r'ི[་]?', ''),
    # འ?དྲེན -> འདྲེན (remove ?)
    (r'འ', r'དྲེན', ''),
    # ་?་ (tseg ? tseg) -> ་་ e.g. ་་་་་་?་་
    (r'་', r'་', ''),
    # ---- Insert ་ (tseg) ----
    (r'པའི', r'་', '\u0F0B'),
    (r'མཛད', r'་', '\u0F0B'),
    (r'བཤད', r'་', '\u0F0B'),
    (r'ཚོང', r'་', '\u0F0B'),
    (r'ཀུན', r'་', '\u0F0B'),
    (r'ཆེན', r'་པ', '\u0F0B'),
    (r'དྲང་བ', r'་', '\u0F0B'),
    (r'བསྟན', r'པ', '\u0F0B'),
    (r'འཆད', r'པ', '\u0F0B'),
    (r'དཀའ', r'ན', '\u0F0B'),
    (r'དམ', r'་ཆོས', '\u0F0B'),
    (r'མི་གནས', r'པ', '\u0F0B'),
    (r'རྣམས', r'་', '\u0F0B'),
    # ---- Insert ར ----
    (r'[དབ]', r'ར', '\u0F62'),
    (r'བ', r'རྩ', '\u0F62'),
    # ---- Insert ུ (vowel u) ----
    (r'དྲ', r'ུ', '\u0F74'),
    (r'བཞ', r'ུགས', '\u0F74'),
    # ---- Insert ྲ (subjoined ra) ----
    (r'སྒ', r'ྲ', '\u0FB2'),
    (r'བར', r'ྗ', '\u0FB2'),
    # ---- Insert ེ (vowel e) ----
    (r'ཤ', r'ེ', '\u0F7A'),
    # ---- Insert ག ----
    (r'མཆོ', r'ག', '\u0F40'),
    (r'ས་', r'གསུམ', '\u0F56'),
    (r'གང་ཞི', r'ག', ''),     # གང་ཞི?ག -> གང་ཞིག (remove ?)
    # ---- Insert བ (or remove ? when བ/ག already follows) ----
    (r'ཀྱི་', r'ས་བཅད', '\u0F56'),  # ཀྱི་?ས་བཅད -> ཀྱི་བས་བཅད
    (r'ད', r'བྱངས', '\u0F56'),  # ད?བྱངས -> དབྱངས
    (r'བ་', r'སྨ', '\u0F66'),   # བ་?སྨོས: insert ས
    (r'ས་', r'བཅད', ''),      # ས་?བཅད -> ས་བཅད (remove ?)
    (r'ས་', r'གསུམ', ''),      # ས་?གསུམ -> ས་གསུམ (remove ?)
    # ---- Insert ྱ (subjoined ya) ----
    (r'ཕ', r'ྱི', '\u0FB1'),
    (r'བསྐུར', r'རྒྱ', '\u0F0B'),  # ་ before རྒྱལ
    # ---- Insert ཚ ----
    (r'རྒྱལ', r'བ', '\u0F5A'),  # ཚ
    # ---- Insert ན ----
    (r'རིན་ཆེ', r'ན', '\u0F53'),
    (r'རང་གཞ', r'ན', '\u0F53'),
    # ---- Insert ལ ----
    (r'ཤཱཀྱ་རྒྱ', r'ལ', '\u0F63'),
    (r'གས', r'ལ', '\u0F63'),
    # ---- Insert ད ----
    (r'ཐམས་ཅ', r'ད', '\u0F51'),
    (r'ས', r'ྡེ', '\u0F51'),     # གཞན་ས?ྡེ -> སྡེ (insert ད)
    # ---- Insert ོ (vowel o) ----
    (r'གཙོ་བ', r'ོར', '\u0F7C'),
    # ---- Insert other common ----
    (r'མི་', r'རིང', '\u0F62'),  # ར
    (r'འཇུག', r'པ', '\u0F0B'),  # ་
    (r'ལུ', r'གས', '\u0F40'),   # ག ལུ?གས -> ལུགས
    (r'ད', r'གོངས', '\u0F40'),  # ག ད?གོངས -> དགོངས
    (r'གས', r'ུང', '\u0F74'),   # ུ གས?ུང་ -> གསུང་
    (r'རྗེ་བ', r'ཙུན', '\u0F5A'),  # ཚ རྗེ་བ?ཙུན -> རྗེ་བཙུན
    (r'གཉིས', r'་པ', '\u0F0B'),  # གཉིས?་པ -> གཉིས་པ
    (r'གསུམ', r'་པ', '\u0F0B'),
    (r'དང་པ', r'ོ', '\u0F7C'),   # དང་པ?ོ -> དང་པོ
    (r'བསྟན', r'བཅོས', '\u0F0B'),  # བསྟན་?བཅོས -> བསྟན་བཅོས
    (r'སྐྱབས', r'འགྲོ', '\u0F0B'),
    (r'བྱང་ཆུབ', r'་སེམས', '\u0F0B'),
    (r'མཐར', r'ཐུག', '\u0F0B'),
    (r'དེ་ལས', r'ཉུང', '\u0F0B'),
    (r'རྒྱུ་འབྲས', r'འབྲེལ', '\u0F0B'),
    (r'དགེ', r'་བ', '\u0F0B'),   # དག?ེ་བའི
    (r'སྟོང', r'་པ', '\u0F0B'),
    (r'ངོ', r'་བོ', '\u0F0B'),
    (r'འཕྲིན', r'་ལས', '\u0F0B'),
    (r'ས', r'ྒྲུབ', '\u0F56'),   # ས?ྒྲུབ -> སྒྲུབ (བ)
    (r'རྣམ', r'་པར', '\u0F0B'),
    (r'གློ་བུ', r'ར', '\u0F62'),  # གློ་བུ?ར
    (r'བྱེ', r'ད', '\u0F0B'),     # བྱེ?ད
    (r'ཡང', r'ཡིན', '\u0F0B'),   # ཡང་?ཡིན
    (r'དཀོན་མཆོག་གསུ', r'མ', '\u0F0B'),  # གསུ?མ
    (r'དོན་གཉ', r'ིས', '\u0F0B'),
    (r'རྒྱུ', r'མཚན', '\u0F0B'),
    (r'ཉེ་བར', r'ལེན', '\u0F0B'),
    (r'ལྷན་ཅིག་བྱེ', r'ད', '\u0F0B'),
    (r'སྔ་', r'མའི', '\u0F0B'),  # སྔ་?མའི
    (r'གཞན་ག', r'ྱི', '\u0F0B'),
    (r'ཐོབ་བྱ', r'འི', '\u0F0B'),
    (r'སྐ', r'ྱོན', '\u0F0B'),    # སྐ?ྱོན -> སྐྱོན
    (r'ཡང་དག', r'་པ', '\u0F0B'),
    (r'རྟེན་འ', r'བྲེལ', '\u0F0B'),  # རྟེན་འ?བྲེལ
    (r'ཐེག་པ', r'་ཆེན', '\u0F0B'),
    (r'ད', r'ང་མཐའ', '\u0F0B'),
    (r'ངོ', r'ས', '\u0F0B'),     # ངོ?ས
    (r'རྟེན', r'འབྲེལ', '\u0F0B'),
    (r'ཁ', r'མས', '\u0F0B'),    # ཁ?མས -> ཁམས (insert ་)
    (r'ད', r'ང་རྐྱེན', '\u0F0B'),  # ད?ང་རྐྱེན
    (r'ད', r'ང་མཐའ', '\u0F44'),  # ད?ང་མཐའ -> དང་ (insert ང)
]


def fix_question_mark_placeholders(text: str) -> str:
    """
    Replace '?' that appear between Tibetan characters with the likely missing character.
    
    These placeholders occur when:
    1. RTF \\uN was followed by a replacement-count digit that was misparsed as part of N,
       causing chr() to fail and output '?'.
    2. Dedris-to-Unicode conversion could not convert a byte and passed through '?'.
    
    Uses context (characters before and after ?) to infer the correct Tibetan character.
    
    Args:
        text: Text that may contain ? placeholders in Tibetan syllables
        
    Returns:
        Text with ? replaced by inferred Tibetan characters where possible
    """
    if not text or '?' not in text:
        return text
    
    result = text
    # Special: རྒྱ?ྱས -> རྒྱས (remove ? and the ྱ that follows it; our tuple format can't delete "after")
    result = re.sub(r'རྒྱ\?ྱ', 'རྒྱ', result)
    # Run two passes so fixes that depend on earlier replacements get applied
    for _ in range(2):
        for before, after, replacement in _QUESTION_MARK_FIXES:
            pattern = rf'({before})\?({after})'
            if replacement:
                result = re.sub(pattern, rf'\1{replacement}\2', result)
            else:
                result = re.sub(pattern, r'\1\2', result)

    # Remove ? when it is between two Tibetan characters (common when RTF replacement
    # char was emitted as literal). No insertion—just drop ?. Run multiple passes for
    # patterns like ཐ?ེ?ག? -> ཐེག.
    tibetan_range = r'[\u0F00-\u0FFF]'
    for _ in range(10):
        prev = result
        result = re.sub(rf'({tibetan_range})\?({tibetan_range})', r'\1\2', result)
        if result == prev:
            break
    # Remove any remaining ? (placeholders that had no context-specific fix)
    result = result.replace('?', '')
    return result


# =============================================================================
# ASCII to Tibetan Character Fixes
# =============================================================================

def fix_ascii_to_tibetan(text: str) -> str:
    """
    Fix ASCII characters that should be Tibetan characters.
    
    These mappings handle cases where ASCII punctuation was incorrectly used
    instead of proper Tibetan characters in the source RTF files.
    
    Mappings:
        . (period)      -> ད (Tibetan letter DA) - preserves ellipsis (2+ dots)
        - (hyphen)      -> ་ (Tibetan tseg/syllable separator) - preserves hyphens between digits (e.g., 22-268)
        0 (zero)        -> པ (Tibetan letter PA) - BUT NOT in digit sequences (preserved as numbers)
        , (comma)       -> ཐ (Tibetan letter THA)
        } (right brace) -> སྔ (Tibetan SA + NGA)
        \\ (backslash)  -> གླ (Tibetan GA + LA subscript)
    
    Note: Ellipsis (sequences of 2+ periods), numbers (digit sequences), and hyphens between digits are preserved.
    
    Args:
        text: Input text with ASCII characters
        
    Returns:
        Text with ASCII characters replaced by Tibetan equivalents
    """
    if not text:
        return text
    
    # Use simple placeholders
    ELLIPSIS_PLACEHOLDER = '\uE000'
    HYPHEN_PLACEHOLDER = '\uE001'
    
    # First, protect ellipsis by temporarily replacing sequences of 2+ periods
    text = re.sub(r'\.{2,}', lambda m: ELLIPSIS_PLACEHOLDER * len(m.group()), text)
    
    # Protect hyphens between digits (e.g., page ranges like "22-268")
    text = re.sub(r'(\d)-(\d)', rf'\1{HYPHEN_PLACEHOLDER}\2', text)
    
    # Apply character replacements (but NOT on zeros that are part of numbers)
    text = text.replace('.', 'ད')  # period -> DA (only single periods now)
    text = text.replace('-', '་')  # hyphen -> tseg
    # Convert ONLY standalone zeros or zeros surrounded by non-digits
    # This regex converts 0 to པ only when NOT part of a digit sequence
    text = re.sub(r'(?<!\d)0(?!\d)', 'པ', text)
    text = text.replace(',', 'ཐ')  # comma -> THA
    text = text.replace('}', 'སྔ')  # right brace -> SA + NGA
    text = text.replace('\\', 'གླ')  # backslash -> GA + LA subscript
    
    # Restore protected characters
    text = text.replace(ELLIPSIS_PLACEHOLDER, '.')
    text = text.replace(HYPHEN_PLACEHOLDER, '-')
    
    return text


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
    if text is None:
        return 0
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

