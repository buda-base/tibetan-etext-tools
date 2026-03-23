"""
Dedris to Unicode Converter Module

This module provides functions to convert Dedris legacy-encoded Tibetan text
to Unicode using the pytiblegenc library.
"""

import logging

logger = logging.getLogger(__name__)

# Global stats for tracking conversion results
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0,
    "skipped_non_dedris": [],
    "converted_suspicious": [],
}


def reset_stats():
    """Reset conversion statistics."""
    global STATS
    STATS = {
        "handled_fonts": {},
        "unhandled_fonts": {},
        "unknown_characters": {},
        "diffs_with_utfc": {},
        "error_characters": 0,
        "skipped_non_dedris": [],
        "converted_suspicious": [],
    }


def get_stats():
    """Get current conversion statistics."""
    return STATS


# Try to import pytiblegenc
try:
    from pytiblegenc import convert_string
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False
    logger.warning(
        "pytiblegenc not available. Install with:\n"
        "  pip install -U git+https://github.com/buda-base/py-tiblegenc.git"
    )
    
    def convert_string(text, font_name, stats):
        """Fallback when pytiblegenc is not available."""
        return text


SUSPICIOUS_FONTS = (
    'simsun', '@simsun', 'simsun western',
    'times new roman', 'arial', 'calibri', 'calibri light',
    'ms gothic', 'ms mincho', 'songti', 'fangsong',
    'kaiti', 'heiti', 'microsoft yahei', 'nsimsun',
    'batang', 'gulim', 'dotum', 'malgun gothic',
)


def is_legacy_tibetan_font(font_name: str) -> bool:
    """Check if font is a legacy Tibetan font (Dedris, TibetanChogyal, TibetanClassic)."""
    if not font_name:
        return False
    lower_name = font_name.lower()
    return lower_name.startswith((
        'dedris', 'ededris',
        'tibetanchogyal', 'tibetanchogyalskt',
        'tibetanclassic', 'tibetanclassicskt',
    ))


def looks_like_dedris(text: str) -> bool:
    """
    Check if text looks like Dedris-encoded Tibetan.
    
    Dedris encoding uses ASCII characters to represent Tibetan.
    Common patterns include letters and punctuation like: o=- .2%- 0
    Key indicators: high density of punctuation like - = . $ % < > mixed with letters
    
    Also detects MIXED content where some characters are already converted to
    Tibetan Unicode but others remain as ASCII Dedris.
    """
    if not text or len(text.strip()) < 2:
        return False
    
    stripped = text.strip()
    
    # Check for mixed content: Tibetan Unicode mixed with ASCII Dedris characters
    # Common unconverted Dedris chars that appear adjacent to Tibetan: . { } 0 \ / ( ) , -
    has_tibetan = any(0x0F00 <= ord(c) <= 0x0FFF for c in stripped)
    dedris_ascii_chars = set('.{}0\\/(),-')
    has_dedris_ascii = any(c in dedris_ascii_chars for c in stripped)
    
    if has_tibetan and has_dedris_ascii:
        # Mixed content detected - likely partially converted Dedris
        return True
    
    # For pure ASCII, check if it looks like Dedris encoding
    if any(ord(c) > 0x0FFF for c in stripped):
        return False
    
    dedris_punctuation = set('=-.$%<>@&!?()[]{}\\/')
    punct_count = sum(1 for c in stripped if c in dedris_punctuation)
    
    if punct_count >= len(stripped) * 0.10:  # Lowered from 0.15 to 0.10
        return True
    
    dedris_patterns = ['=-', '-=', '.$', '$.', '%$', '- ', ' -', '<-', '->', '0-', '-0']
    for pattern in dedris_patterns:
        if pattern in stripped:
            return True
    
    return False


def is_suspicious_font(font_name: str) -> bool:
    """Check if a font might contain misattributed Dedris text."""
    if not font_name:
        return False
    return font_name.lower() in SUSPICIOUS_FONTS


def is_tibetan_vowel_sign(char: str) -> bool:
    """Check if character is a Tibetan vowel sign (combining mark)."""
    code = ord(char)
    # Tibetan vowel signs: ི (U+0F72), ུ (U+0F74), ེ (U+0F7A), ོ (U+0F7C), etc.
    return code in (0x0F71, 0x0F72, 0x0F74, 0x0F7A, 0x0F7B, 0x0F7C, 0x0F7D, 0x0F7E, 0x0F7F,
                    0x0F80, 0x0F81, 0x0F82, 0x0F83, 0x0F84)


# Dedris consonant mapping - ASCII char to Unicode consonant
# These are used when ASCII appears before a Tibetan VOWEL SIGN
# Based on observed patterns in the documents
DEDRIS_CONSONANT_MAP = {
    '.': 'ད',   # da - .ེ་ → དེ་
    '0': 'ས',   # sa - 0ོ་ → སོ་
    '{': 'ཆ',   # cha - {འི་ → ཆའི་
    '\\': 'ས',  # sa (alternate) - \ི → སི
    '/': 'ཤ',   # sha
    '(': 'ཡ',   # ya
    ')': 'འ',   # a-chung
    '}': 'ས',   # sa (alternate)
    ',': 'ཐ',   # tha - ,ུ → ཐུ
}

# Dedris syllable mapping - ASCII char to Unicode syllable (consonant + inherent vowel)
# These are used when ASCII appears before a Tibetan CONSONANT or TSHEG
# Based on observed patterns: ག.ལ་ → གདུལ་ (. = དུ before ལ)
DEDRIS_SYLLABLE_MAP = {
    '.': 'དུ',  # du - ག.ལ་ → གདུལ་
    '0': 'སུ',  # su
    '{': 'ཆུ',  # chu
    '\\': 'སུ', # su (alternate)
    '/': 'ཤུ',  # shu
    '(': 'ཡུ',  # yu
    ')': 'འུ',  # u
    '}': 'སུ',  # su (alternate)
    ',': 'ཐུ',  # thu - མ,ན་ → མཐུན་
    '-': '་',   # tsheg (syllable separator) - འགྲོ-བའི་ → འགྲོ་བའི་
}


def is_tibetan_consonant_or_tsheg(char: str) -> bool:
    """Check if character is a Tibetan consonant, subjoined consonant, or tsheg."""
    code = ord(char)
    # Tibetan consonants: ཀ-ཨ (U+0F40-U+0F6C)
    # Subjoined consonants: (U+0F90-U+0FBC)
    # Tsheg: ་ (U+0F0B)
    # Other marks that indicate start of syllable
    return (0x0F40 <= code <= 0x0F6C or  # Main consonants
            0x0F90 <= code <= 0x0FBC or  # Subjoined consonants
            code == 0x0F0B or             # Tsheg
            code == 0x0F0D or             # Shad
            code == 0x0F14)               # Comma


def convert_mixed_content(text: str, font_name: str) -> str:
    """
    Convert mixed content where some characters are Tibetan Unicode and others are ASCII Dedris.
    
    This handles cases where partial conversion occurred, leaving some ASCII Dedris
    characters mixed with already-converted Tibetan Unicode.
    
    Uses two mappings:
    - DEDRIS_CONSONANT_MAP: for ASCII before vowel signs (e.g., .ེ → དེ)
    - DEDRIS_SYLLABLE_MAP: for ASCII before consonants/tsheg (e.g., ག.ལ → གདུལ)
    """
    if not PYTIBLEGENC_AVAILABLE:
        return text
    
    result = []
    ascii_buffer = []
    effective_font = 'Dedris-a'  # Default for mixed content
    text_len = len(text)
    i = 0
    
    while i < text_len:
        char = text[i]
        char_code = ord(char)
        
        if 0x0F00 <= char_code <= 0x0FFF:
            # Tibetan Unicode character
            if ascii_buffer:
                ascii_text = ''.join(ascii_buffer)
                
                # Check what kind of Tibetan character follows
                if is_tibetan_vowel_sign(char) and len(ascii_text) >= 1:
                    # Vowel sign follows - use CONSONANT map for last char
                    last_ascii = ascii_text[-1]
                    prefix = ascii_text[:-1]
                    
                    # Try to convert the prefix normally
                    if prefix:
                        converted_prefix = convert_string(prefix, effective_font, STATS)
                        if converted_prefix is not None:
                            result.append(converted_prefix)
                        else:
                            result.append(prefix)
                    
                    # Handle the orphaned consonant
                    if last_ascii in DEDRIS_CONSONANT_MAP:
                        result.append(DEDRIS_CONSONANT_MAP[last_ascii])
                    else:
                        converted_last = convert_string(last_ascii, effective_font, STATS)
                        if converted_last is not None and converted_last != last_ascii:
                            result.append(converted_last)
                        else:
                            result.append(last_ascii)  # Keep as-is if can't convert
                            
                elif is_tibetan_consonant_or_tsheg(char) and len(ascii_text) >= 1:
                    # Consonant or tsheg follows - use SYLLABLE map for last char
                    last_ascii = ascii_text[-1]
                    prefix = ascii_text[:-1]
                    
                    # Try to convert the prefix normally
                    if prefix:
                        converted_prefix = convert_string(prefix, effective_font, STATS)
                        if converted_prefix is not None:
                            result.append(converted_prefix)
                        else:
                            result.append(prefix)
                    
                    # Handle the orphaned syllable
                    if last_ascii in DEDRIS_SYLLABLE_MAP:
                        result.append(DEDRIS_SYLLABLE_MAP[last_ascii])
                    else:
                        converted_last = convert_string(last_ascii, effective_font, STATS)
                        if converted_last is not None and converted_last != last_ascii:
                            result.append(converted_last)
                        else:
                            result.append(last_ascii)  # Keep as-is if can't convert
                else:
                    # Other Tibetan char - try normal conversion
                    converted = convert_string(ascii_text, effective_font, STATS)
                    if converted is not None:
                        result.append(converted)
                    else:
                        result.append(ascii_text)
                
                ascii_buffer = []
            
            result.append(char)
            i += 1
        else:
            # Non-Tibetan character - buffer it for potential conversion
            ascii_buffer.append(char)
            i += 1
    
    # Flush remaining ASCII buffer
    if ascii_buffer:
        ascii_text = ''.join(ascii_buffer)
        converted = convert_string(ascii_text, effective_font, STATS)
        if converted is not None:
            result.append(converted)
        else:
            result.append(ascii_text)
    
    return ''.join(result)


def dedris_to_unicode(text: str, font_name: str) -> str:
    """
    Convert legacy Tibetan encoded string to Unicode using pytiblegenc.
    
    Supports Dedris, TibetanChogyal, TibetanClassic and related fonts.
    
    Args:
        text: Text in legacy encoding
        font_name: Font name from RTF/DOCX (e.g., "Dedris-a", "TibetanChogyal")
        
    Returns:
        Unicode text (unchanged if font is not a legacy Tibetan font)
    """
    if not text or not text.strip():
        return text
    
    # Check if this is a legacy Tibetan font
    is_legacy = is_legacy_tibetan_font(font_name)
    
    # Check for mixed content (Tibetan Unicode + ASCII legacy)
    has_tibetan = any(0x0F00 <= ord(c) <= 0x0FFF for c in text)
    legacy_ascii_chars = set('.{}0\\/(),-')
    has_legacy_ascii = any(c in legacy_ascii_chars for c in text)
    is_mixed = has_tibetan and has_legacy_ascii
    
    if is_mixed:
        # Mixed content - convert only the ASCII portions
        return convert_mixed_content(text, font_name)
    
    if not is_legacy:
        # Skip conversion entirely for non-legacy fonts
        # Don't try to guess based on text patterns - only convert if font is explicitly legacy
        return text
    
    # Font is legacy Tibetan - convert using pytiblegenc
    try:
        result = convert_string(text, font_name, STATS)
        if result is None:
            # Font not in conversion tables
            preview = text[:50].replace('\n', '\\n')
            logger.warning(f"UNHANDLED FONT: '{font_name}' | text: '{preview}'")
            return text
        
        return result
    except Exception as e:
        logger.warning(f"Error converting with font {font_name}: {e}")
        return text


def print_conversion_stats():
    """Print comprehensive debug information about the conversion."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("CONVERSION STATISTICS")
    logger.info("=" * 60)
    
    if STATS["handled_fonts"]:
        logger.info("")
        logger.info("HANDLED FONTS (successfully converted):")
        for font, count in sorted(STATS["handled_fonts"].items()):
            logger.info(f"  {font}: {count} characters")
    
    if STATS["unhandled_fonts"]:
        logger.info("")
        logger.info("UNHANDLED FONTS (not in pytiblegenc tables):")
        for font, count in sorted(STATS["unhandled_fonts"].items()):
            logger.info(f"  {font}: {count} characters NOT converted")
    
    if STATS["unknown_characters"]:
        logger.info("")
        logger.info("UNKNOWN CHARACTERS BY FONT:")
        for font, chars in sorted(STATS["unknown_characters"].items()):
            sample_chars = list(chars)[:20]
            char_info = [f"'{c}'({ord(c) if len(c) == 1 else 'multi'})" for c in sample_chars]
            logger.info(f"  {font}: {len(chars)} unknown chars")
            logger.info(f"    Samples: {', '.join(char_info)}")
    
    if STATS["error_characters"] > 0:
        logger.info(f"\nERROR CHARACTERS: {STATS['error_characters']} conversion errors")
    
    logger.info("=" * 60)


def write_stats_file(output_path):
    """Write conversion statistics to a file."""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("CONVERSION STATISTICS\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("HANDLED FONTS:\n")
            if STATS["handled_fonts"]:
                for font, count in sorted(STATS["handled_fonts"].items()):
                    f.write(f"  {font}: {count} characters\n")
            else:
                f.write("  None recorded\n")
            
            f.write("\nUNHANDLED FONTS:\n")
            if STATS["unhandled_fonts"]:
                for font, count in sorted(STATS["unhandled_fonts"].items()):
                    f.write(f"  {font}: {count} characters NOT converted\n")
            else:
                f.write("  None (all fonts were handled)\n")
            
            f.write(f"\nERROR CHARACTERS: {STATS['error_characters']}\n")
            
        logger.info(f"Stats written to: {output_path}")
    except Exception as e:
        logger.warning(f"Could not write stats file: {e}")


